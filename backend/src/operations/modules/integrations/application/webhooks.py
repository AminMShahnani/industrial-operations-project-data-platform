"""Pure security contracts for signed, identifiers-only webhook requests.

No network adapter lives here. Callers must connect to a validated IP while
retaining the original hostname for TLS SNI and certificate verification.
"""

import hashlib
import hmac
import ipaddress
import json
import socket
from datetime import UTC, datetime
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import Field

from operations.contracts import Command, ServiceError
from operations.modules.automation.application.events import OperationalEvent

MAX_WEBHOOK_BODY_BYTES = 4096


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
