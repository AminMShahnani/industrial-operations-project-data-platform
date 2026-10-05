from datetime import UTC, datetime, timedelta
from uuid import uuid7

from operations.modules.iam.domain.policy import Grant, Role, Scope, ScopeType, permissions


def test_isolation_inheritance_and_validity_matrix() -> None:
    organization, other, workspace, user, stranger = [uuid7() for _ in range(5)]
    now = datetime.now(UTC)
    scope = Scope(organization, ScopeType.WORKSPACE, workspace)
    admin = Grant(
        uuid7(),
        organization,
        user,
        Role.ORGANIZATION_ADMIN,
        ScopeType.ORGANIZATION,
        organization,
        True,
    )
    assert "workspace.manage" in permissions([admin], user, scope, now)
    assert not permissions([admin], stranger, scope, now)
    assert not permissions([admin], user, Scope(other, ScopeType.WORKSPACE, workspace), now)
    no_inherit = Grant(
        uuid7(), organization, user, Role.VIEWER, ScopeType.ORGANIZATION, organization, False
    )
    assert not permissions([no_inherit], user, scope, now)
    for valid_from, valid_until, revoked in (
        (now + timedelta(days=1), None, False),
        (None, now, False),
        (None, None, True),
    ):
        invalid = Grant(
            uuid7(),
            organization,
            user,
            Role.WORKSPACE_ADMIN,
            ScopeType.WORKSPACE,
            workspace,
            False,
            valid_from,
            valid_until,
            revoked,
        )
        assert not permissions([invalid], user, scope, now)
    viewer = Grant(uuid7(), organization, user, Role.VIEWER, ScopeType.WORKSPACE, workspace, False)
    assert "workspace.read" in permissions([viewer], user, scope, now)
    assert "workspace.manage" not in permissions([viewer], user, scope, now)
    assert not permissions([viewer], user, Scope(organization, ScopeType.WORKSPACE, uuid7()), now)
