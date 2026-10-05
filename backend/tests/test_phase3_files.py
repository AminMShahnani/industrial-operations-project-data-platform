import asyncio
import socketserver
import struct
from collections.abc import Iterator
from threading import Thread

import pytest
from operations.contracts import ServiceError
from operations.modules.files.infrastructure.adapters import ClamScanner
from operations.platform.body_limit import RequestBodyLimit
from operations.platform.config import Settings
from starlette.types import Message, Receive, Scope, Send
from test_infrastructure import infrastructure_settings as infrastructure_settings


class ScannerHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        def read(length: int) -> bytes:
            result = bytearray()
            while len(result) < length:
                part = self.request.recv(length - len(result))
                if not part:
                    raise RuntimeError("Incomplete scanner stream")
                result.extend(part)
            return bytes(result)

        assert read(10) == b"zINSTREAM\x00"
        data = bytearray()
        while size := struct.unpack("!I", read(4))[0]:
            data.extend(read(size))
        response = (
            b"stream: Fixture.Test FOUND\x00" if b"malicious-fixture" in data else b"stream: OK\x00"
        )
        # Deliberately split the response to cover TCP fragmentation.
        self.request.sendall(response[:5])
        self.request.sendall(response[5:])


@pytest.fixture
def scanner() -> Iterator[ClamScanner]:
    with socketserver.TCPServer(("127.0.0.1", 0), ScannerHandler) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield ClamScanner("127.0.0.1", int(server.server_address[1]))
        finally:
            server.shutdown()
            thread.join(timeout=2)


def test_scanner_streaming_clean_infected_and_unavailable(scanner: ClamScanner) -> None:
    assert scanner.clean(b"clean-fixture" * 10000)
    assert not scanner.clean(b"malicious-fixture")
    with pytest.raises(ServiceError, match="scanner_unavailable"):
        ClamScanner(None, 3310).clean(b"file")


def test_actual_chunked_body_limit_runs_before_parsing() -> None:
    called = False
    sent: list[Message] = []

    async def application(scope: Scope, receive: Receive, send: Send) -> None:
        nonlocal called
        called = True

    messages: Iterator[Message] = iter(
        [
            {"type": "http.request", "body": b"x" * 3000, "more_body": True},
            {"type": "http.request", "body": b"x" * 2000, "more_body": False},
        ]
    )

    async def receive() -> Message:
        return next(messages)

    async def send(message: Message) -> None:
        sent.append(message)

    asyncio.run(
        RequestBodyLimit(application, 4096)(
            {"type": "http", "state": {"request_id": "fixture"}}, receive, send
        )
    )
    assert not called
    assert sent[0]["status"] == 413
    assert b"request_too_large" in sent[1]["body"]


@pytest.mark.integration
def test_real_private_storage_put_and_sixty_second_signed_download(
    infrastructure_settings: Settings,
) -> None:
    from urllib.parse import parse_qs, urlparse
    from urllib.request import urlopen
    from uuid import uuid7

    from operations.modules.files.infrastructure.adapters import S3Storage

    storage = S3Storage(infrastructure_settings)
    key = f"phase3-tests/{uuid7()}"
    client = storage.client()
    try:
        storage.put(key, b"Attachment fixture", "text/plain")
        signed = storage.signed_download(key, "evidence.txt", "text/plain")
        assert parse_qs(urlparse(signed).query)["X-Amz-Expires"] == ["60"]
        with urlopen(signed, timeout=5) as response:
            assert response.read() == b"Attachment fixture"
            assert "attachment" in response.headers["Content-Disposition"]
            assert response.headers["Content-Type"].startswith("text/plain")
    finally:
        client.delete_object(Bucket=infrastructure_settings.s3_bucket, Key=key)
        client.close()
