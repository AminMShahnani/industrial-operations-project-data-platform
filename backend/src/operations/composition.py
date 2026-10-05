from dataclasses import dataclass

from sqlalchemy.orm import Session

from operations.modules.audit.infrastructure.persistence import AuditRepository
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
from operations.modules.workspaces.application.group_service import GroupService
from operations.modules.workspaces.application.service import WorkspaceService
from operations.modules.workspaces.infrastructure.groups import GroupRepository
from operations.modules.workspaces.infrastructure.persistence import WorkspaceRepository


@dataclass(frozen=True)
class Services:
    identity: IdentityService
    authorization: Authorization
    organizations: OrganizationService
    workspaces: WorkspaceService
    groups: GroupService
    projects: ProjectService
    master_data: MasterDataService
    master_transfer: MasterDataTransfer


def compose(session: Session, principal: Principal | None = None) -> Services:
    audit = AuditRepository(session, principal)
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
    return Services(
        identity,
        authorization,
        organizations,
        workspaces,
        groups,
        projects,
        master_data,
        MasterDataTransfer(master_data, TabularFiles()),
    )
