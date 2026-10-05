import socket
import struct
from contextlib import closing
from typing import TYPE_CHECKING
from urllib.parse import quote

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client

from operations.contracts import ServiceError
from operations.platform.config import Settings


class ClamScanner:
    def __init__(self, host: str | None, port: int) -> None:
        self.host, self.port = host, port

    def clean(self, data: bytes) -> bool:
        if not self.host:
            raise ServiceError(503, "scanner_unavailable")
        try:
            with socket.create_connection((self.host, self.port), timeout=10) as connection:
                connection.settimeout(10)
                connection.sendall(b"zINSTREAM\x00")
                for start in range(0, len(data), 65536):
                    chunk = data[start : start + 65536]
                    connection.sendall(struct.pack("!I", len(chunk)) + chunk)
                connection.sendall(struct.pack("!I", 0))
                response = bytearray()
                while len(response) < 4096:
                    part = connection.recv(min(1024, 4096 - len(response)))
                    if not part:
                        break
                    response.extend(part)
                    if b"\x00" in part or b"\n" in part:
                        break
            result = bytes(response).rstrip(b"\x00\r\n")
            if result == b"stream: OK":
                return True
            if result.startswith(b"stream: ") and result.endswith(b" FOUND"):
                return False
            raise ServiceError(503, "scanner_failed")
        except OSError as error:
            raise ServiceError(503, "scanner_unavailable") from error


class S3Storage:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def client(self) -> S3Client:
        return boto3.client(
            "s3",
            endpoint_url=self.settings.s3_endpoint,
            aws_access_key_id=self.settings.s3_access_key.get_secret_value(),
            aws_secret_access_key=self.settings.s3_secret_key.get_secret_value(),
            region_name="us-east-1",
            config=Config(
                signature_version="s3v4",
                connect_timeout=3,
                read_timeout=10,
                retries={"max_attempts": 2},
            ),
        )

    def put(self, key: str, data: bytes, content_type: str) -> None:
        try:
            with closing(self.client()) as client:
                client.put_object(
                    Bucket=self.settings.s3_bucket, Key=key, Body=data, ContentType=content_type
                )
        except (BotoCoreError, ClientError) as error:
            raise ServiceError(503, "storage_unavailable") from error

    def delete(self, key: str) -> None:
        try:
            with closing(self.client()) as client:
                client.delete_object(Bucket=self.settings.s3_bucket, Key=key)
        except (BotoCoreError, ClientError) as error:
            raise ServiceError(503, "storage_cleanup_unavailable") from error

    def signed_download(self, key: str, name: str, content_type: str) -> str:
        try:
            with closing(self.client()) as client:
                return str(
                    client.generate_presigned_url(
                        "get_object",
                        Params={
                            "Bucket": self.settings.s3_bucket,
                            "Key": key,
                            "ResponseContentType": content_type,
                            "ResponseContentDisposition": (
                                f"attachment; filename*=UTF-8''{quote(name)}"
                            ),
                        },
                        ExpiresIn=60,
                    )
                )
        except (BotoCoreError, ClientError) as error:
            raise ServiceError(503, "storage_unavailable") from error
