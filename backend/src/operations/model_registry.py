"""Schema composition only. Business modules never use each other's repositories."""

from operations.modules.audit.infrastructure.persistence import AuditRow as AuditRow
from operations.modules.iam.infrastructure.persistence import GrantRow as GrantRow
from operations.modules.identity.infrastructure.persistence import InvitationRow as InvitationRow
from operations.modules.identity.infrastructure.persistence import (
    PlatformAdminRow as PlatformAdminRow,
)
from operations.modules.identity.infrastructure.persistence import UserRow as UserRow
from operations.modules.organizations.infrastructure.persistence import (
    OrganizationRow as OrganizationRow,
)
from operations.modules.workspaces.infrastructure.persistence import WorkspaceRow as WorkspaceRow
