from typing import Protocol
from uuid import UUID

from operations.modules.iam.domain.policy import Grant as Grant
from operations.modules.iam.domain.policy import Role as Role
from operations.modules.iam.domain.policy import Scope as Scope
from operations.modules.iam.domain.policy import ScopeType as ScopeType


class GrantStore(Protocol):
    def for_user(self, organization_id: UUID, user_id: UUID) -> list[Grant]: ...
    def create(self, grant: Grant) -> None: ...
    def get(self, organization_id: UUID, grant_id: UUID) -> Grant | None: ...
    def revoke(self, organization_id: UUID, grant_id: UUID) -> None: ...
