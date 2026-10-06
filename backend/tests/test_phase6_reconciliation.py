from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid7

import pytest
from operations.composition import compose
from operations.contracts import ServiceError
from operations.modules.audit.infrastructure.persistence import AuditRepository, AuditRow
from operations.modules.files.application.contracts import Attachment
from operations.modules.files.application.reconciliation import (
    CleanupPlan,
    FileReconciler,
    InventoryPage,
    StoredObject,
    coordinates,
)
from operations.modules.files.infrastructure.adapters import S3Storage
from operations.modules.files.infrastructure.persistence import FileRepository
from operations.modules.iam.infrastructure.persistence import GrantRow
from operations.modules.identity.application.contracts import Principal, RequestContext
from operations.modules.identity.infrastructure.persistence import UserRow
from operations.platform.config import Settings
from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from test_infrastructure import infrastructure_settings as infrastructure_settings
from test_oidc import signing_key as signing_key
from test_phase1_api import Api
from test_phase1_api import api as api
from test_phase3_api import draft, publish, setup

pytestmark = pytest.mark.integration


class Inventory:
    def __init__(self) -> None:
        self.objects: dict[str, StoredObject] = {}
        self.deleted: list[str] = []
        self.fail = False
        self.conflict = False

    def inventory(self, org: UUID, cursor: str | None) -> InventoryPage:
        start = int(cursor or 0)
        items = [
            item
            for key, item in sorted(self.objects.items())
            if key.startswith(f"organizations/{org}/")
        ]
        return InventoryPage(
            objects=items[start : start + 100],
            cursor=str(start + 100) if len(items) > start + 100 else None,
        )

    def inspect(self, key: str) -> StoredObject | None:
        if self.fail:
            raise ServiceError(503, "fixture_failure")
        return self.objects.get(key)

    def delete_if_match(self, key: str, etag: str) -> bool:
        if self.conflict:
            return False
        assert self.objects[key].etag == etag
        del self.objects[key]
        self.deleted.append(key)
        return True


def fixture(api: Api) -> tuple[FileReconciler, Inventory, RequestContext, UUID, UUID, UUID]:
    org, workspace, route, form = setup(api)
    publish(api, route, form)
    submission = UUID(draft(api, route, form))
    user = api.session.scalar(select(UserRow).where(UserRow.organization_id == org))
    assert user
    actor = RequestContext(Principal(user.issuer, user.subject), uuid7(), uuid7())
    inventory = Inventory()
    services = compose(api.session, actor.principal)
    service = FileReconciler(
        FileRepository(api.session), inventory, services.organizations, AuditRepository(api.session)
    )
    return service, inventory, actor, org, workspace, submission


def object_item(
    org: UUID, workspace: UUID, submission: UUID, *, recent: bool = False
) -> StoredObject:
    return StoredObject(
        key=f"organizations/{org}/workspaces/{workspace}/submissions/{submission}/{uuid7()}",
        etag='"fixture-etag"',
        modified_at=datetime.now(UTC) - timedelta(hours=1 if recent else 48),
    )


def reference(
    service: FileReconciler, actor: RequestContext, org: UUID, item: StoredObject
) -> None:
    location = coordinates(org, item.key)
    assert location
    workspace, submission, file = location
    service.store.add(
        Attachment(
            id=file,
            organization_id=org,
            workspace_id=workspace,
            submission_id=submission,
            owner_id=service.authorize(actor, org),
            name="evidence.txt",
            content_type="text/plain",
            size=4,
            sha256="a" * 64,
            object_key=item.key,
        )
    )


def test_preview_preserves_every_reference_recent_unknown_and_other_tenant(api: Api) -> None:
    service, inventory, actor, org, workspace, submission = fixture(api)
    orphan = object_item(org, workspace, submission)
    linked = object_item(org, workspace, submission)
    recent = object_item(org, workspace, submission, recent=True)
    other = object_item(uuid7(), workspace, submission)
    unknown = orphan.model_copy(update={"key": f"organizations/{org}/" + "x" * 400})
    inventory.objects = {item.key: item for item in [orphan, linked, recent, other, unknown]}
    reference(service, actor, org, linked)
    plan = service.preview(actor, org)
    assert plan.candidates == [orphan] and plan.scanned == 4
    assert not inventory.deleted
    assert service.request(actor, plan, "remove rollback orphan")
    with pytest.raises(ValidationError):
        service.preview(actor, org, 1)
    with pytest.raises(ServiceError, match="cleanup_reason_required"):
        service.request(actor, plan, " ")
    bad = CleanupPlan(organization_id=org, grace_seconds=86400, scanned=1, candidates=[other])
    with pytest.raises(ServiceError, match="invalid_cleanup_object"):
        service.request(actor, bad, "wrong tenant")


def test_cleanup_retries_after_effect_transaction_rollback_without_losing_intent(api: Api) -> None:
    service, inventory, actor, org, workspace, submission = fixture(api)
    item = object_item(org, workspace, submission)
    inventory.objects[item.key] = item
    intent = service.request(actor, service.preview(actor, org), "failed upload cleanup")[0]
    api.session.commit()
    with pytest.raises(RuntimeError, match="crash after delete"), api.session.begin_nested():
        assert service.apply(actor, org, intent) == "deleted"
        raise RuntimeError("crash after delete")
    assert inventory.deleted == [item.key]
    assert service.evidence.get(org, intent)
    assert service.apply(actor, org, intent) == "missing"
    assert inventory.deleted == [item.key]
    events = api.session.scalars(
        select(AuditRow).where(AuditRow.type == "file.cleanup.result")
    ).all()
    assert len(events) == 1 and events[0].payload["outcome"] == "missing"
    assert events[0].payload["target_id"] == str(intent)
    assert "object_key" not in events[0].payload


@pytest.mark.parametrize("case", ["referenced", "changed", "failed", "conflict", "busy"])
def test_apply_rechecks_reference_age_etag_storage_failure_and_upload_lock(
    api: Api, case: str
) -> None:
    service, inventory, actor, org, workspace, submission = fixture(api)
    item = object_item(org, workspace, submission)
    inventory.objects[item.key] = item
    intent = service.request(actor, service.preview(actor, org), "controlled cleanup")[0]
    with Session(api.session.get_bind().engine) as other:
        if case == "referenced":
            reference(service, actor, org, item)
        elif case == "changed":
            inventory.objects[item.key] = item.model_copy(update={"modified_at": datetime.now(UTC)})
        elif case == "failed":
            inventory.fail = True
        elif case == "conflict":
            inventory.conflict = True
        else:
            assert FileRepository(other).lock_key(item.key, wait=True)
        expected = "changed" if case == "conflict" else case
        assert service.apply(actor, org, intent) == expected
        assert item.key in inventory.objects and not inventory.deleted
        other.rollback()
    if case == "busy":
        assert service.apply(actor, org, intent) == "deleted"


def test_cleanup_fresh_authority_cross_tenant_and_platform_do_not_bypass(api: Api) -> None:
    service, inventory, actor, org, workspace, submission = fixture(api)
    item = object_item(org, workspace, submission)
    inventory.objects[item.key] = item
    intent = service.request(actor, service.preview(actor, org), "authorized request")[0]
    second = api.organization("other")
    other_actor = RequestContext(Principal(actor.principal.issuer, "other"), uuid7(), uuid7())
    with pytest.raises(ServiceError, match="cleanup_intent_not_found"):
        service.apply(other_actor, second, intent)
    platform = RequestContext(Principal(actor.principal.issuer, "platform"), uuid7(), uuid7())
    with pytest.raises(ServiceError, match="access_denied"):
        service.preview(platform, org)
    api.session.execute(
        update(GrantRow).where(GrantRow.organization_id == org).values(revoked=True)
    )
    with pytest.raises(ServiceError, match="access_denied"):
        service.apply(actor, org, intent)
    assert not inventory.deleted


def test_real_s3_bounded_inventory_and_conditional_delete(
    infrastructure_settings: Settings,
) -> None:
    storage = S3Storage(infrastructure_settings)
    org, workspace, submission = uuid7(), uuid7(), uuid7()
    keys = [object_item(org, workspace, submission).key for _ in range(101)]
    try:
        for key in keys:
            storage.put(key, b"orphan fixture", "text/plain")
        first = storage.inventory(org, None)
        assert len(first.objects) == 100 and first.cursor
        second = storage.inventory(org, first.cursor)
        assert len(second.objects) == 1 and second.cursor is None
        assert {item.key for item in first.objects + second.objects} == set(keys)
        item = storage.inspect(keys[0])
        assert item
        assert not storage.delete_if_match(item.key, '"wrong-etag"')
        assert storage.inspect(item.key) == item
        storage.put(item.key, b"changed fixture", "text/plain")
        assert not storage.delete_if_match(item.key, item.etag)
        changed = storage.inspect(item.key)
        assert changed and changed.etag != item.etag
        assert storage.delete_if_match(changed.key, changed.etag)
        assert storage.inspect(changed.key) is None
    finally:
        # Only this uniquely generated fixture prefix is touched.
        for key in keys:
            storage.delete(key)


def test_cleanup_refuses_stale_transaction_isolation(infrastructure_settings: Settings) -> None:
    from operations.platform.database import create_database_engine

    engine = create_database_engine(infrastructure_settings)
    try:
        with (
            engine.connect().execution_options(isolation_level="REPEATABLE READ") as connection,
            Session(connection) as session,
            pytest.raises(ServiceError, match="cleanup_isolation_not_supported"),
        ):
            FileRepository(session).lock_key(f"fixture/{uuid7()}")
    finally:
        engine.dispose()
