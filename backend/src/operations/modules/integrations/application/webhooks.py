"""Pure security contracts for signed, identifiers-only webhook requests.

No network adapter lives here. Callers must connect to a validated IP while
retaining the original hostname for TLS SNI and certificate verification.
"""

import hashlib
import hmac
import http.client
import ipaddress
import json
import socket
import ssl
from contextlib import suppress
from datetime import UTC, datetime
from typing import Protocol
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

from pydantic import Field

from operations.contracts import Command, ServiceError
from operations.modules.automation.application.events import OperationalEvent
from operations.modules.integrations.application.contracts import EndpointVersion

MAX_WEBHOOK_BODY_BYTES = 4096
MAX_WEBHOOK_RESPONSE_BYTES = 8192
WEBHOOK_TIMEOUT_SECONDS = 5.0


def validate_endpoint_url(url: str) -> None:
    parsed = urlsplit(url)
    if (
        url != url.strip()
        or parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ServiceError(422, "webhook_endpoint_url_invalid")
    try:
        _ = parsed.port
    except ValueError:
        raise ServiceError(422, "webhook_endpoint_port_invalid") from None
    if len(url) > 2048:
        raise ServiceError(422, "webhook_endpoint_url_invalid")


class WebhookEnvelope(Command):
    delivery_id: UUID
    organization_id: UUID
    workspace_id: UUID | None
    project_id: UUID | None
    event_id: UUID
    event_type: str = Field(min_length=1, max_length=100)
    aggregate_type: str = Field(min_length=1, max_length=40)
    aggregate_id: UUID
    occurred_at: datetime
    causation_id: UUID | None
    correlation_id: UUID


def envelope_for(event: OperationalEvent, delivery_id: UUID) -> WebhookEnvelope:
    """Project only stable identifiers and routing metadata; never event payload."""
    return WebhookEnvelope(
        delivery_id=delivery_id,
        organization_id=event.organization_id,
        workspace_id=event.workspace_id,
        project_id=event.project_id,
        event_id=event.id,
        event_type=event.type,
        aggregate_type=event.aggregate_type,
        aggregate_id=event.aggregate_id,
        occurred_at=event.occurred_at,
        causation_id=event.causation_id,
        correlation_id=event.correlation_id,
    )


def canonical_body(envelope: WebhookEnvelope) -> bytes:
    body = json.dumps(
        envelope.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    if len(body) > MAX_WEBHOOK_BODY_BYTES:
        raise ServiceError(422, "webhook_body_too_large")
    return body


def signature_headers(
    body: bytes, secret: bytes, delivery_id: UUID, key_version: int
) -> dict[str, str]:
    if not secret or key_version < 1 or len(body) > MAX_WEBHOOK_BODY_BYTES:
        raise ServiceError(422, "webhook_signing_configuration_invalid")
    timestamp = str(int(datetime.now(UTC).timestamp()))
    message = timestamp.encode("ascii") + b"." + body
    digest = hmac.new(secret, message, hashlib.sha256).hexdigest()
    return {
        "Content-Type": "application/json",
        "X-IOP-Delivery": str(delivery_id),
        "X-IOP-Key-Version": str(key_version),
        "X-IOP-Timestamp": timestamp,
        "X-IOP-Signature": "sha256=" + digest,
    }


def resolve_destination(url: str, allowed_private_cidrs: tuple[str, ...] = ()) -> tuple[str, int]:
    """Validate HTTPS and every DNS answer; transport must pin a returned address.

    Rejecting a hostname here is not enough to prevent DNS rebinding. This function
    intentionally does not send requests or perform a second DNS lookup.
    """
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise ServiceError(422, "webhook_endpoint_url_invalid")
    try:
        port = parsed.port or 443
        records = socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)
    except OSError, ValueError:
        raise ServiceError(422, "webhook_endpoint_dns_invalid") from None
    if not records:
        raise ServiceError(422, "webhook_endpoint_dns_invalid")
    allowlist = tuple(ipaddress.ip_network(item, strict=False) for item in allowed_private_cidrs)
    addresses: set[ipaddress.IPv4Address | ipaddress.IPv6Address] = set()
    try:
        addresses = {ipaddress.ip_address(row[4][0]) for row in records}
    except ValueError:
        raise ServiceError(422, "webhook_endpoint_dns_invalid") from None
    for address in addresses:
        forbidden = (
            address.is_loopback
            or address.is_link_local
            or address.is_multicast
            or address.is_unspecified
            or address.is_reserved
        )
        if forbidden:
            raise ServiceError(422, "webhook_endpoint_address_blocked")
        if not address.is_global and not any(
            address.version == network.version and address in network for network in allowlist
        ):
            raise ServiceError(422, "webhook_endpoint_private_address_blocked")
    if len(addresses) != 1:
        raise ServiceError(422, "webhook_endpoint_multiple_addresses_unsupported")
    return str(next(iter(addresses))), port


class TenantSecretResolver(Protocol):
    """Deployment adapter for tenant-isolated, externally stored key versions."""

    def resolve(self, organization_id: UUID, reference: str, version: int) -> bytes: ...


class WebhookTransport(Protocol):
    def post(self, url: str, address: str, body: bytes, headers: dict[str, str]) -> int: ...


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, url: str, address: str, context: ssl.SSLContext) -> None:
        parsed = urlsplit(url)
        assert parsed.hostname is not None
        super().__init__(
            parsed.hostname,
            parsed.port or 443,
            timeout=WEBHOOK_TIMEOUT_SECONDS,
            context=context,
        )
        self._pinned_address = address
        self._ssl_context = context

    def connect(self) -> None:
        raw_socket = socket.create_connection(
            (self._pinned_address, self.port), timeout=WEBHOOK_TIMEOUT_SECONDS
        )
        self.sock = self._ssl_context.wrap_socket(raw_socket, server_hostname=self.host)


class PinnedHTTPSWebhookTransport:
    """Direct HTTPS with DNS-pinned TCP and the original TLS/HTTP hostname."""

    def __init__(self, context: ssl.SSLContext | None = None) -> None:
        self.context = context or ssl.create_default_context()

    def post(self, url: str, address: str, body: bytes, headers: dict[str, str]) -> int:
        parsed = urlsplit(url)
        path = urlunsplit(("", "", parsed.path or "/", "", ""))
        connection = _PinnedHTTPSConnection(url, address, self.context)
        try:
            connection.request("POST", path, body=body, headers=headers)
            response = connection.getresponse()
            if 300 <= response.status < 400:
                raise ServiceError(502, "webhook_redirect_rejected")
            response_body = response.read(MAX_WEBHOOK_RESPONSE_BYTES + 1)
            if len(response_body) > MAX_WEBHOOK_RESPONSE_BYTES:
                raise ServiceError(502, "webhook_response_too_large")
            if not 200 <= response.status < 300:
                raise ServiceError(502, "webhook_receiver_rejected")
            return response.status
        except ServiceError:
            raise
        except TimeoutError, OSError, ssl.SSLError, http.client.HTTPException:
            # A timeout after request bytes were written has an uncertain outcome.
            raise ServiceError(503, "webhook_delivery_uncertain") from None
        finally:
            with suppress(OSError):
                connection.close()


def deliver_webhook(
    event: OperationalEvent,
    delivery_identifier: UUID,
    endpoint: EndpointVersion,
    secrets: TenantSecretResolver,
    transport: WebhookTransport,
    allowed_private_cidrs: tuple[str, ...] = (),
) -> int:
    """Send one bounded attempt. Durable scheduling/retries belong to the worker."""
    if endpoint.state != "active":
        raise ServiceError(409, "webhook_endpoint_revoked")
    if endpoint.organization_id != event.organization_id or (
        endpoint.workspace_id,
        endpoint.project_id,
    ) != (event.workspace_id, event.project_id):
        raise ServiceError(409, "webhook_endpoint_scope_mismatch")
    validate_endpoint_url(endpoint.url)
    body = canonical_body(envelope_for(event, delivery_identifier))
    address, _port = resolve_destination(endpoint.url, allowed_private_cidrs)
    try:
        secret = secrets.resolve(
            endpoint.organization_id, endpoint.secret_reference, endpoint.signing_key_version
        )
    except Exception:
        raise ServiceError(503, "webhook_signing_secret_unavailable") from None
    if len(secret) < 32:
        raise ServiceError(503, "webhook_signing_secret_unavailable")
    headers = signature_headers(body, secret, delivery_identifier, endpoint.signing_key_version)
    return transport.post(endpoint.url, address, body, headers)
