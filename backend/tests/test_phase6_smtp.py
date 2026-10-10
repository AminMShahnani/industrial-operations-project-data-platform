import json
import smtplib
import socketserver
import threading
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from uuid import uuid7

import pytest
from operations.contracts import ServiceError
from operations.modules.notifications.application.email_contracts import EmailContent
from operations.modules.notifications.infrastructure.smtp import (
    SmtpProfile,
    SmtpTransport,
    load_profile,
)
from pydantic import SecretStr, ValidationError


def profile(**changes: Any) -> SmtpProfile:
    return SmtpProfile(
        organization_id=uuid7(),
        host="127.0.0.1",
        sender="sender@example.com",
        tls=False,
        app_origin="http://localhost:5173",
        **changes,
    )


class SmtpSink(socketserver.StreamRequestHandler):
    messages: list[bytes] = []

    def handle(self) -> None:
        self.connection.settimeout(5)
        self.wfile.write(b"220 local test sink\r\n")
        while command := self.rfile.readline():
            if command.upper().startswith(b"DATA"):
                self.wfile.write(b"354 send message\r\n")
                lines: list[bytes] = []
                while (line := self.rfile.readline()) != b".\r\n":
                    if not line:
                        return
                    lines.append(line)
                self.messages.append(b"".join(lines))
                self.wfile.write(b"250 accepted\r\n")
            else:
                self.wfile.write(b"250 OK\r\n")


def test_real_loopback_smtp_message_and_stable_id() -> None:
    SmtpSink.messages = []
    with socketserver.TCPServer(("127.0.0.1", 0), SmtpSink) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            configured = profile(port=server.server_address[1])
            identifier = uuid7()
            content = EmailContent(
                "recipient@example.com",
                "Organization invitation",
                "Fixed text\nhttps://app.example/?invitation=id",
            )
            for _ in range(2):
                assert SmtpTransport(configured).send(identifier, content).state == "sent"
            assert len(SmtpSink.messages) == 2
            for wire in SmtpSink.messages:
                assert f"Message-ID: <{identifier}@operations.invalid>".encode() in wire
                assert b"\r\n" in wire and b"Fixed text" in wire
        finally:
            server.shutdown()
            thread.join(5)


@pytest.mark.parametrize("stage,expected", [("mail", "retry"), ("data", "uncertain")])
def test_disconnect_stage_classification(
    monkeypatch: pytest.MonkeyPatch, stage: str, expected: str
) -> None:
    class Client:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def ehlo(self) -> None:
            pass

        def mail(self, sender: str) -> tuple[int, bytes]:
            if stage == "mail":
                raise smtplib.SMTPServerDisconnected("private provider detail")
            return 250, b"ok"

        def rcpt(self, recipient: str) -> tuple[int, bytes]:
            return 250, b"ok"

        def data(self, wire: bytes) -> tuple[int, bytes]:
            raise smtplib.SMTPServerDisconnected("private provider detail")

        def close(self) -> None:
            pass

    monkeypatch.setattr(smtplib, "SMTP", Client)
    result = SmtpTransport(profile()).send(
        uuid7(), EmailContent("x@example.com", "Notice", "Minimal")
    )
    assert result.state == expected
    assert "private" not in str(result)


@pytest.mark.parametrize("code,expected", [(450, "retry"), (550, "failed")])
def test_explicit_data_rejection_is_safe(
    monkeypatch: pytest.MonkeyPatch, code: int, expected: str
) -> None:
    class Client:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def ehlo(self) -> None:
            pass

        def mail(self, sender: str) -> tuple[int, bytes]:
            return 250, b"ok"

        def rcpt(self, recipient: str) -> tuple[int, bytes]:
            return 250, b"ok"

        def data(self, wire: bytes) -> tuple[int, bytes]:
            return code, b"secret detail"

        def close(self) -> None:
            pass

    monkeypatch.setattr(smtplib, "SMTP", Client)
    assert (
        SmtpTransport(profile())
        .send(uuid7(), EmailContent("x@example.com", "Notice", "Minimal"))
        .state
        == expected
    )


def test_profile_tenant_binding_tls_and_redaction() -> None:
    with TemporaryDirectory(prefix="iop-smtp-profile-") as directory:
        check_profile(Path(directory))


def check_profile(tmp_path: Path) -> None:
    configured = SmtpProfile(
        organization_id=uuid7(),
        host="smtp.example.com",
        sender="sender@example.com",
        username=SecretStr("private-user"),
        password=SecretStr("private-password"),
        app_origin="https://app.example.com",
    )
    assert "private-user" not in repr(configured) and "private-password" not in repr(configured)
    path = tmp_path / (str(configured.organization_id) + ".json")
    # Build test secret material explicitly; the normal DTO serializer is redacted.
    payload = configured.model_dump(mode="json") | {
        "username": "private-user",
        "password": "private-password",
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    loaded = load_profile(str(tmp_path), configured.organization_id, True)
    assert loaded.tls and loaded.password
    assert loaded.password.get_secret_value() == "private-password"
    wrong = uuid7()
    (tmp_path / (str(wrong) + ".json")).write_text(path.read_text(), encoding="utf-8")
    with pytest.raises(ServiceError, match="email_profile_unavailable"):
        load_profile(str(tmp_path), wrong, True)
    with pytest.raises(ServiceError, match="email_not_configured"):
        load_profile(None, wrong, True)
    path.write_text("{invalid-private-password", encoding="utf-8")
    with pytest.raises(ServiceError) as error:
        load_profile(str(tmp_path), configured.organization_id, True)
    assert "private" not in str(error.value) and error.value.__cause__ is None
    with pytest.raises(ValidationError):
        SmtpProfile(
            organization_id=uuid7(),
            host="external.example.com",
            sender="a@example.com",
            tls=False,
            app_origin="https://app.example.com",
        )
    with pytest.raises(ValidationError):
        SmtpProfile(
            organization_id=uuid7(),
            host="localhost",
            sender="a@example.com",
            app_origin="https://user:secret@app.example.com/path",
        )
