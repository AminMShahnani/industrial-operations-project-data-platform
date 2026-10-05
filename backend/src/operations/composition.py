from dataclasses import dataclass

from sqlalchemy.orm import Session

from operations.modules.audit.infrastructure.persistence import AuditRepository
from operations.modules.iam.application.service import Authorization
from operations.modules.iam.infrastructure.persistence import GrantRepository
from operations.modules.identity.application.contracts import Principal
from operations.modules.identity.application.service import IdentityService
from operations.modules.identity.infrastructure.persistence import IdentityRepository
from operations.modules.organizations.application.service import OrganizationService
from operations.modules.organizations.infrastructure.persistence import OrganizationRepository
from operations.modules.workspaces.application.service import WorkspaceService
from operations.modules.workspaces.infrastructure.persistence import WorkspaceRepository


@dataclass(frozen=True)
class Services:
    identity: IdentityService
    authorization: Authorization
    organizations: OrganizationService
    workspaces: WorkspaceService


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
    identity = IdentityService(identities, organizations, authorization, audit)
    workspaces = WorkspaceService(WorkspaceRepository(session), organizations, authorization, audit)
    return Services(identity, authorization, organizations, workspaces)
