"""Schema composition only. Business modules never use each other's repositories."""

from operations.modules.audit.infrastructure.persistence import AuditRow as AuditRow
from operations.modules.automation.infrastructure.persistence import EventRow as EventRow
from operations.modules.automation.infrastructure.timers import (
    TimerOccurrenceRow as TimerOccurrenceRow,
)
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
from operations.modules.notifications.infrastructure.persistence import NoticeRow as NoticeRow
from operations.modules.organizations.infrastructure.persistence import (
    OrganizationRow as OrganizationRow,
)
from operations.modules.projects.infrastructure.persistence import (
    DepartmentProjectGrantRow as DepartmentProjectGrantRow,
)
from operations.modules.projects.infrastructure.persistence import MilestoneRow as MilestoneRow
from operations.modules.projects.infrastructure.persistence import (
    ProjectMembershipRow as ProjectMembershipRow,
)
from operations.modules.projects.infrastructure.persistence import (
    ProjectRow as ProjectRow,
)
from operations.modules.scheduling.infrastructure.persistence import ScheduleRow as ScheduleRow
from operations.modules.scheduling.infrastructure.persistence import (
    ScheduleVersionRow as ScheduleVersionRow,
)
from operations.modules.scheduling.infrastructure.persistence import ShiftRow as ShiftRow
from operations.modules.scheduling.infrastructure.persistence import TriggerRow as TriggerRow
from operations.modules.submissions.infrastructure.persistence import SubmissionRow as SubmissionRow
from operations.modules.tasks.infrastructure.persistence import RecipientRow as RecipientRow
from operations.modules.tasks.infrastructure.persistence import ReminderRow as ReminderRow
from operations.modules.tasks.infrastructure.persistence import TaskRow as TaskRow
from operations.modules.workflows.infrastructure.persistence import WorkflowRow as WorkflowRow
from operations.modules.workflows.infrastructure.persistence import (
    WorkflowVersionRow as WorkflowVersionRow,
)
from operations.modules.workflows.infrastructure.runtime import InstanceRow as InstanceRow
from operations.modules.workflows.infrastructure.runtime import StepRow as StepRow
from operations.modules.workspaces.infrastructure.groups import (
    GroupMembershipRow as GroupMembershipRow,
)
from operations.modules.workspaces.infrastructure.groups import (
    GroupRow as GroupRow,
)
from operations.modules.workspaces.infrastructure.persistence import WorkspaceRow as WorkspaceRow
