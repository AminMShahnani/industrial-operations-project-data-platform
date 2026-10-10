import hmac
import socket
from datetime import UTC, datetime
from hashlib import sha256
from uuid import uuid7

import pytest
from operations.contracts import ServiceError
from operations.modules.automation.application.events import EventContext, OperationalEvent
from operations.modules.integrations.application.webhooks import (
    canonical_body,
    envelope_for,
    resolve_destination,
    signature_headers,
)


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
