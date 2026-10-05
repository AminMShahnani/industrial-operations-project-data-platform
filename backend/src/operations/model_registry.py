"""Schema composition only. Business modules never use each other's repositories."""

from operations.modules.audit.infrastructure.persistence import AuditRow as AuditRow
from operations.modules.files.infrastructure.persistence import FileRow as FileRow
from operations.modules.forms.infrastructure.persistence import (
    FormRow as FormRow,
)
from operations.modules.forms.infrastructure.persistence import (
    FormVersionRow as FormVersionRow,
)
from operations.modules.forms.infrastructure.persistence import (
    LibraryArtifactRow as LibraryArtifactRow,
)
from operations.modules.iam.infrastructure.persistence import GrantRow as GrantRow
from operations.modules.identity.infrastructure.persistence import InvitationRow as InvitationRow
from operations.modules.identity.infrastructure.persistence import (
    PlatformAdminRow as PlatformAdminRow,
)
from operations.modules.identity.infrastructure.persistence import UserRow as UserRow
from operations.modules.master_data.infrastructure.persistence import (
    DataRecordRow as DataRecordRow,
)
from operations.modules.master_data.infrastructure.persistence import (
    DataTypeRow as DataTypeRow,
)
from operations.modules.organizations.infrastructure.persistence import (
    OrganizationRow as OrganizationRow,
)
from operations.modules.projects.infrastructure.persistence import (
    DepartmentProjectGrantRow as DepartmentProjectGrantRow,
)
from operations.modules.projects.infrastructure.persistence import (
    ProjectMembershipRow as ProjectMembershipRow,
)
from operations.modules.projects.infrastructure.persistence import (
    ProjectRow as ProjectRow,
)
from operations.modules.submissions.infrastructure.persistence import SubmissionRow as SubmissionRow
from operations.modules.workspaces.infrastructure.groups import (
    GroupMembershipRow as GroupMembershipRow,
)
from operations.modules.workspaces.infrastructure.groups import (
    GroupRow as GroupRow,
)
from operations.modules.workspaces.infrastructure.persistence import WorkspaceRow as WorkspaceRow
