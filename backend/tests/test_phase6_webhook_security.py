import hmac
import socket
import ssl
from datetime import UTC, datetime
from hashlib import sha256
from typing import cast
from uuid import UUID, uuid7

import pytest
from operations.contracts import ServiceError
from operations.modules.automation.application.events import EventContext, OperationalEvent
from operations.modules.integrations.application.contracts import EndpointVersion
from operations.modules.integrations.application.webhooks import (
    PinnedHTTPSWebhookTransport,
    UnconfiguredTenantSecretResolver,
    _PinnedHTTPSConnection,
    canonical_body,
    deliver_webhook,
    envelope_for,
    resolve_destination,
    signature_headers,
)
from operations.platform.config import Settings
from pydantic import SecretStr, ValidationError


def event() -> OperationalEvent:
    return OperationalEvent(
        id=uuid7(),
        type="submission.submitted",
        occurred_at=datetime.now(UTC),
        organization_id=uuid7(),
        workspace_id=uuid7(),
        project_id=uuid7(),
        correlation_id=uuid7(),
        aggregate_type="submission",
        aggregate_id=uuid7(),
        payload=EventContext(form_id=uuid7(), form_number=8, phase="secret-project-phase"),
    )


def test_webhook_envelope_contains_only_documented_identifiers() -> None:
    source = event()
    body = canonical_body(envelope_for(source, uuid7()))
    assert b"secret-project-phase" not in body
    assert b"form_number" not in body
    assert str(source.aggregate_id).encode() in body


def test_signature_is_hmac_sha256_over_timestamp_and_exact_body() -> None:
    body, secret, delivery = b'{"event_type":"task.due"}', b"test-secret", uuid7()
    headers = signature_headers(body, secret, delivery, 4)
    message = headers["X-IOP-Timestamp"].encode() + b"." + body
    expected = hmac.new(secret, message, sha256).hexdigest()
    assert headers["X-IOP-Signature"] == "sha256=" + expected
    assert headers["X-IOP-Delivery"] == str(delivery)
    assert headers["X-IOP-Key-Version"] == "4"


def test_destination_rejects_http_credentials_and_redirect_fragments() -> None:
    for url in (
        "http://example.test/hook",
        "https://user:pass@example.test/hook",
        "https://example.test/hook#fragment",
    ):
        with pytest.raises(ServiceError, match="webhook_endpoint_url_invalid"):
            resolve_destination(url)


def test_destination_blocks_any_private_or_loopback_dns_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def mixed_answers(*_args: object, **_kwargs: object) -> list[tuple[object, ...]]:
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443)),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", mixed_answers)
    with pytest.raises(ServiceError, match="webhook_endpoint_address_blocked"):
        resolve_destination("https://hooks.example.test/endpoint")


def test_destination_requires_private_network_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    def private_answer(*_args: object, **_kwargs: object) -> list[tuple[object, ...]]:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.2.3.4", 443))]

    monkeypatch.setattr(socket, "getaddrinfo", private_answer)
    with pytest.raises(ServiceError, match="webhook_endpoint_private_address_blocked"):
        resolve_destination("https://hooks.example.test/endpoint")
    assert resolve_destination("https://hooks.example.test/endpoint", ("10.2.0.0/16",)) == (
        "10.2.3.4",
        443,
    )


class FixedSecrets:
    def __init__(self) -> None:
        self.requests: list[tuple[object, ...]] = []

    def resolve(self, organization_id: UUID, reference: str, version: int) -> bytes:
        self.requests.append((organization_id, reference, version))
        return b"k" * 32


class CaptureTransport:
    def __init__(self) -> None:
        self.request: tuple[str, str, bytes, dict[str, str]] | None = None

    def post(self, url: str, address: str, body: bytes, headers: dict[str, str]) -> int:
        self.request = (url, address, body, headers)
        return 202


def endpoint(source: OperationalEvent) -> EndpointVersion:
    return EndpointVersion(
        audit_id=uuid7(),
        endpoint_id=uuid7(),
        organization_id=source.organization_id,
        workspace_id=source.workspace_id,
        project_id=source.project_id,
        version=3,
        signing_key_version=9,
        name="Test receiver",
        url="https://hooks.example.test:8443/v1/events",
        secret_reference="tenant/webhooks/key-v9",
        created_by_id=uuid7(),
        created_at=datetime.now(UTC),
    )


def test_delivery_resolves_tenant_key_version_and_sends_pinned_identifiers_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 8443))],
    )
    source, delivery = event(), uuid7()
    target, secrets, transport = endpoint(source), FixedSecrets(), CaptureTransport()
    assert deliver_webhook(source, delivery, target, target, secrets, transport) == 202
    assert secrets.requests == [(source.organization_id, target.secret_reference, 9)]
    assert transport.request is not None
    url, address, body, headers = transport.request
    assert address == "8.8.8.8" and url == target.url
    assert b"secret-project-phase" not in body
    assert headers["X-IOP-Delivery"] == str(delivery)
    assert headers["X-IOP-Key-Version"] == "9"


def test_delivery_blocks_revoked_or_cross_scope_endpoint_before_secret_resolution() -> None:
    source, secrets, transport = event(), FixedSecrets(), CaptureTransport()
    target = endpoint(source).model_copy(update={"state": "revoked"})
    with pytest.raises(ServiceError, match="webhook_endpoint_revoked"):
        deliver_webhook(source, uuid7(), target, target, secrets, transport)
    target = endpoint(source).model_copy(update={"workspace_id": uuid7()})
    with pytest.raises(ServiceError, match="webhook_endpoint_scope_mismatch"):
        deliver_webhook(source, uuid7(), target, target, secrets, transport)
    assert secrets.requests == [] and transport.request is None


def test_later_revocation_blocks_old_active_pin_before_resolving_secret() -> None:
    source, secrets, transport = event(), FixedSecrets(), CaptureTransport()
    pinned = endpoint(source)
    latest = pinned.model_copy(update={"version": pinned.version + 1, "state": "revoked"})
    with pytest.raises(ServiceError, match="webhook_endpoint_revoked"):
        deliver_webhook(source, uuid7(), pinned, latest, secrets, transport)
    assert secrets.requests == [] and transport.request is None


def test_later_active_revision_keeps_old_rule_pin_but_rejects_invalid_latest_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 8443))],
    )
    source, delivery = event(), uuid7()
    pinned = endpoint(source)
    latest = pinned.model_copy(
        update={"version": pinned.version + 1, "url": "https://new.example.test/events"}
    )
    secrets, transport = FixedSecrets(), CaptureTransport()
    assert deliver_webhook(source, delivery, pinned, latest, secrets, transport) == 202
    assert secrets.requests == [(source.organization_id, pinned.secret_reference, 9)]
    assert transport.request is not None and transport.request[0] == pinned.url
    mismatched = latest.model_copy(update={"endpoint_id": uuid7()})
    with pytest.raises(ServiceError, match="webhook_endpoint_version_integrity"):
        deliver_webhook(source, delivery, pinned, mismatched, secrets, transport)


def test_missing_tenant_secret_fails_closed_without_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))],
    )

    class MissingSecrets:
        def resolve(self, _organization_id: UUID, _reference: str, _version: int) -> bytes:
            raise RuntimeError("provider detail must not escape")

    source, transport = event(), CaptureTransport()
    with pytest.raises(ServiceError, match="webhook_signing_secret_unavailable"):
        target = endpoint(source)
        deliver_webhook(source, uuid7(), target, target, MissingSecrets(), transport)
    assert transport.request is None


def test_unconfigured_secret_resolver_fails_closed_and_redacts_reference() -> None:
    reference = "private/tenant-specific/path"
    with pytest.raises(ServiceError, match="webhook_signing_secret_unavailable") as error:
        UnconfiguredTenantSecretResolver().resolve(uuid7(), reference, 9)
    assert reference not in str(error.value)


def test_https_connection_pins_ip_but_keeps_original_tls_server_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}
    raw_socket = object()
    tls_socket = object()

    def connect(address: tuple[str, int], timeout: float) -> object:
        observed["address"] = address
        observed["timeout"] = timeout
        return raw_socket

    class Context:
        def wrap_socket(self, sock: object, *, server_hostname: str) -> object:
            observed["raw_socket"] = sock
            observed["server_hostname"] = server_hostname
            return tls_socket

    monkeypatch.setattr(socket, "create_connection", connect)
    connection = _PinnedHTTPSConnection(
        "https://hooks.example.test:8443/events", "8.8.8.8", cast(ssl.SSLContext, Context())
    )
    connection.connect()
    assert observed["address"] == ("8.8.8.8", 8443)
    assert observed["server_hostname"] == "hooks.example.test"
    assert connection.sock is tls_socket


def test_pinned_transport_refuses_redirects_without_following_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Response:
        status = 302

        def read(self, _size: int) -> bytes:
            return b"redirect"

    class Connection:
        requested_path: str | None = None
        closed = False

        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def request(self, method: str, path: str, **_kwargs: object) -> None:
            assert method == "POST"
            self.requested_path = path

        def getresponse(self) -> Response:
            return Response()

        def close(self) -> None:
            self.closed = True

    created: list[Connection] = []

    def factory(*args: object, **kwargs: object) -> Connection:
        connection = Connection(*args, **kwargs)
        created.append(connection)
        return connection

    monkeypatch.setattr(
        "operations.modules.integrations.application.webhooks._PinnedHTTPSConnection", factory
    )
    transport = PinnedHTTPSWebhookTransport()
    with pytest.raises(ServiceError, match="webhook_redirect_rejected"):
        transport.post("https://hooks.example.test/events", "8.8.8.8", b"{}", {})
    assert created[0].requested_path == "/events"
    assert created[0].closed


def test_settings_accept_only_private_deployment_egress_cidrs() -> None:
    def configured(cidrs: list[str]) -> Settings:
        return Settings(
            _env_file=None,  # type: ignore[call-arg]
            environment="test",
            database_url=SecretStr("postgresql+psycopg://unused:unused@localhost/unused"),
            redis_url=SecretStr("redis://localhost:6379/0"),
            s3_endpoint="http://localhost:9000",
            s3_access_key=SecretStr("unused"),
            s3_secret_key=SecretStr("unused"),
            webhook_private_egress_cidrs=cidrs,
        )

    trusted = configured(["10.20.0.0/16"])
    assert trusted.webhook_private_egress_cidrs == ["10.20.0.0/16"]
    with pytest.raises(ValidationError):
        configured(["8.8.8.8/32"])
    with pytest.raises(ValidationError):
        configured(["not-a-cidr"])
