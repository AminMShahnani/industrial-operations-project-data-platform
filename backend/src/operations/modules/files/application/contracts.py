from typing import Protocol
from uuid import UUID

from operations.contracts import Command


class Attachment(Command):
    id: UUID
    organization_id: UUID
    workspace_id: UUID
    submission_id: UUID
    owner_id: UUID
    name: str
    content_type: str
    size: int
    sha256: str
    object_key: str


class FileStore(Protocol):
    def add(self, attachment: Attachment) -> None: ...
    def get(self, org: UUID, workspace: UUID, identifier: UUID) -> Attachment | None: ...
    def lock_key(self, key: str, wait: bool = False) -> bool: ...
    def referenced(self, org: UUID, key: str) -> bool: ...


class MalwareScanner(Protocol):
    def clean(self, data: bytes) -> bool: ...


class PrivateStorage(Protocol):
    def put(self, key: str, data: bytes, content_type: str) -> None: ...
    def delete(self, key: str) -> None: ...
    def signed_download(self, key: str, name: str, content_type: str) -> str: ...
