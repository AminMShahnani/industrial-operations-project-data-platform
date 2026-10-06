from dataclasses import dataclass

from sqlalchemy.orm import Session

from operations.modules.audit.infrastructure.persistence import AuditRepository
from operations.modules.automation.application.event_bus import AuditedEventBus
from operations.modules.automation.application.service import EventCapture
from operations.modules.automation.infrastructure.persistence import AutomationRepository
from operations.modules.files.application.service import FileService
from operations.modules.files.infrastructure.adapters import ClamScanner, S3Storage
from operations.modules.files.infrastructure.persistence import FileRepository
from operations.modules.forms.application.service import FormService
from operations.modules.forms.infrastructure.persistence import FormRepository
from operations.modules.iam.application.service import Authorization
from operations.modules.iam.infrastructure.persistence import GrantRepository
from operations.modules.identity.application.contracts import Principal
from operations.modules.identity.application.service import IdentityService
from operations.modules.identity.infrastructure.persistence import IdentityRepository
from operations.modules.master_data.application.import_export import MasterDataTransfer
from operations.modules.master_data.application.references import DataReferences
from operations.modules.master_data.application.service import MasterDataService
from operations.modules.master_data.infrastructure.persistence import DataRepository
from operations.modules.master_data.infrastructure.tabular import TabularFiles
from operations.modules.organizations.application.service import OrganizationService
from operations.modules.organizations.infrastructure.persistence import OrganizationRepository
from operations.modules.projects.application.service import ProjectService
from operations.modules.projects.infrastructure.persistence import ProjectRepository
from operations.modules.scheduling.application.service import SchedulingDefaults, SchedulingService
from operations.modules.scheduling.infrastructure.persistence import ScheduleRepository
from operations.modules.submissions.application.service import SubmissionService
from operations.modules.submissions.infrastructure.persistence import SubmissionRepository
from operations.modules.tasks.application.service import TaskService
from operations.modules.tasks.infrastructure.persistence import TaskRepository
from operations.modules.workflows.application.assignments import AssignmentResolver
from operations.modules.workflows.application.defaults import WorkflowDefaults
from operations.modules.workflows.application.runtime import SubmissionLifecycle, WorkflowRuntime
from operations.modules.workflows.application.service import WorkflowService
from operations.modules.workflows.infrastructure.persistence import WorkflowRepository
from operations.modules.workflows.infrastructure.runtime import RuntimeRepository
from operations.modules.workspaces.application.group_service import GroupService
from operations.modules.workspaces.application.service import WorkspaceService
from operations.modules.workspaces.infrastructure.groups import GroupRepository
from operations.modules.workspaces.infrastructure.persistence import WorkspaceRepository
from operations.platform.config import Settings


@dataclass(frozen=True)
class Services:
    workflows: WorkflowService
    workflow_runtime: WorkflowRuntime
    scheduling: SchedulingService
    tasks: TaskService
    forms: FormService
    submissions: SubmissionService
    files: FileService
    identity: IdentityService
    authorization: Authorization
    organizations: OrganizationService
    workspaces: WorkspaceService
    groups: GroupService
    projects: ProjectService
    master_data: MasterDataService
    master_transfer: MasterDataTransfer


def compose(
    session: Session, principal: Principal | None = None, settings: Settings | None = None
) -> Services:
    audit = AuditedEventBus(AuditRepository(session, principal))
    audit.capture = EventCapture(AutomationRepository(session), audit).capture
    identities = IdentityRepository(session)
    grants = GrantRepository(session)
    authorization = Authorization(identities, grants, audit)
    organizations = OrganizationService(
        OrganizationRepository(session),
        identities,
        grants,
        authorization,
        audit,
    )
    workspaces = WorkspaceService(WorkspaceRepository(session), organizations, authorization, audit)
    groups = GroupService(GroupRepository(session), workspaces, authorization, identities, audit)
    data = DataRepository(session)
    references = DataReferences(data)
    projects = ProjectService(
        ProjectRepository(session), workspaces, groups, authorization, identities, references, audit
    )
    identity = IdentityService(identities, organizations, authorization, audit, [groups, projects])
    workspaces.project_visibility = projects
    master_data = MasterDataService(
        data, organizations, workspaces, projects, authorization, references, audit
    )
    forms = FormService(
        FormRepository(session), workspaces, projects, authorization, master_data, audit, groups
    )
    submissions = SubmissionService(SubmissionRepository(session), forms)
    settings = settings or Settings()  # type: ignore[call-arg]
    files = FileService(
        FileRepository(session),
        submissions,
        ClamScanner(settings.scanner_host, settings.scanner_port),
        S3Storage(settings),
    )
    submissions.attachments = files
    schedules = SchedulingService(ScheduleRepository(session), forms)
    forms.default_context = SchedulingDefaults(schedules.store)
    tasks = TaskService(TaskRepository(session), schedules, submissions)
    workflows = WorkflowService(WorkflowRepository(session), forms, AssignmentResolver(schedules))
    workflow_runtime = WorkflowRuntime(RuntimeRepository(session), workflows, submissions)
    workflow_runtime.tasks = tasks
    forms.default_context = WorkflowDefaults(
        SchedulingDefaults(schedules.store), workflow_runtime.store, submissions
    )
    submissions.review_access = workflow_runtime
    submissions.observer = SubmissionLifecycle(tasks, workflow_runtime)
    return Services(
        workflows,
        workflow_runtime,
        schedules,
        tasks,
        forms,
        submissions,
        files,
        identity,
        authorization,
        organizations,
        workspaces,
        groups,
        projects,
        master_data,
        MasterDataTransfer(master_data, TabularFiles()),
    )
