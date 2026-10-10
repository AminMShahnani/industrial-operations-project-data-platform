from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import UUID, uuid7

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from operations.composition import compose
from operations.contracts import ServiceError
from operations.email_worker import email_service
from operations.modules.automation.application.contracts import NotifyAction, RuleDefinition
from operations.modules.iam.infrastructure.persistence import GrantRow
from operations.modules.notifications.application.email_contracts import EmailResult
from operations.modules.notifications.infrastructure.email_persistence import (
    EmailAttemptRow,
    EmailRow,
)
from operations.worker import process_automation
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError
from test_oidc import signing_key as signing_key
from test_phase1_api import Api
from test_phase1_api import api as api
from test_phase2_api import project
from test_phase6_actions import activate, context
from test_phase6_email_invitations import create
from test_phase6_notifications import message

pytestmark = pytest.mark.integration


def queued(api: Api) -> tuple[UUID, UUID]:
    org = api.organization()
    source = create(api, org, api.workspace(org))
    actor, _ = context(api, org)
    delivery = email_service(api.session).queue(
        actor, org, "invitation", source, None, True, "Send requested invitation"
    )
    return org, delivery.id


def test_queue_preview_dedup_minimal_render_and_tenant_scope(api: Api) -> None:
    org = api.organization()
    workspace = api.workspace(org)
    source = create(api, org, workspace)
    actor, _ = context(api, org)
    service = email_service(api.session)
    preview = service.queue(actor, org, "invitation", source, None)
    assert service.store.get(org, preview.id) is None
    with pytest.raises(ServiceError, match="email_reason_required"):
        service.queue(actor, org, "invitation", source, None, True)
    applied = service.queue(actor, org, "invitation", source, None, True, "Requested")
    assert service.queue(actor, org, "invitation", source, None, True, "Duplicate") == applied
    assert api.session.scalar(select(func.count()).select_from(EmailRow)) == 1
    assert service.store.get(uuid7(), applied.id) is None
    content = service.render(applied, "https://app.example.com")
    assert content.recipient == "invitee@example.com"
    assert str(source) in content.text and str(org) in content.text
    assert "token" not in content.text and "Viewer" not in content.text
    assert "invitee@example.com" not in applied.model_dump_json()
    other = api.organization("other")
    with pytest.raises(ServiceError):
        service.queue(actor, other, "invitation", source, None, True, "Denied")
    api.invitation(org, workspace)
    with pytest.raises(ServiceError, match="email_source_invalid"):
        service.queue(actor, org, "invitation", source, uuid7())


def test_claim_once_terminal_attempt_and_database_evidence_guards(api: Api) -> None:
    org, identifier = queued(api)
    service = email_service(api.session)
    claim = service.claim(org, identifier)
    assert claim and claim.attempts == 1
    assert service.claim(org, identifier) is None
    final = service.finish(claim, EmailResult("sent", None))
    assert final.state == "sent" and service.claim(org, identifier) is None
    assert api.session.scalar(select(func.count()).select_from(EmailAttemptRow)) == 1
    for sql in (
        "UPDATE email_deliveries SET source_id=:replacement WHERE id=:id",
        "DELETE FROM email_deliveries WHERE id=:id",
        "TRUNCATE email_deliveries CASCADE",
        "UPDATE email_attempts SET error_code='changed' WHERE delivery_id=:id",
        "DELETE FROM email_attempts WHERE delivery_id=:id",
        "TRUNCATE email_attempts",
        "UPDATE email_deliveries SET state='retry' WHERE id=:id",
    ):
        with pytest.raises(DBAPIError), api.session.begin_nested():
            api.session.execute(text(sql), {"id": identifier, "replacement": uuid7()})
    actor, _ = context(api, org)
    with pytest.raises(ServiceError, match="email_not_replayable"):
        service.replay(actor, org, identifier)
    revision = ScriptDirectory.from_config(Config("alembic.ini")).get_revision("208f826ca492")
    assert revision
    with (
        Operations.context(MigrationContext.configure(api.session.connection())),
        pytest.raises(RuntimeError, match="Email evidence exists"),
    ):
        revision.module.downgrade()


def test_expired_claim_uncertain_exact_replay_and_stale_review(api: Api) -> None:
    org, identifier = queued(api)
    actor, _ = context(api, org)
    service = email_service(api.session)
    claimed = service.claim(org, identifier)
    assert claimed
    with patch("operations.modules.notifications.application.email_service.datetime") as clock:
        clock.now.return_value = datetime.now(UTC) + timedelta(seconds=100)
        assert service.claim(org, identifier) is None
    recovered = service.store.get(org, identifier)
    assert recovered and recovered.state == "uncertain" and recovered.attempts == 1
    assert service.claim(org, identifier) is None
    review = service.replay(actor, org, identifier)
    with pytest.raises(ServiceError, match="email_review_stale"):
        service.replay(actor, org, identifier, True, "0" * 64, "Reviewed")
    with pytest.raises(ServiceError, match="email_reason_required"):
        service.replay(actor, org, identifier, True, review.review_sha256)
    service.replay(actor, org, identifier, True, review.review_sha256, "Provider reviewed")
    with pytest.raises(ServiceError, match="email_review_stale"):
        service.replay(actor, org, identifier, True, review.review_sha256, "Old review")
    second = service.claim(org, identifier)
    assert second and second.attempts == 2
    service.finish(second, EmailResult("sent", None))
    assert api.session.scalar(select(func.count()).select_from(EmailAttemptRow)) == 2


def test_retry_backoff_auto_and_controlled_attempt_limits(api: Api) -> None:
    org, identifier = queued(api)
    actor, _ = context(api, org)
    service = email_service(api.session)
    for number in range(1, 21):
        claim = service.claim(org, identifier)
        assert claim and claim.attempts == number
        result = service.finish(claim, EmailResult("retry", "smtp_unavailable"))
        assert result.state == ("retry" if number < 8 else "failed")
        assert service.claim(org, identifier) is None
        if number < 20:
            review = service.replay(actor, org, identifier)
            service.replay(actor, org, identifier, True, review.review_sha256, "Reviewed retry")
    with pytest.raises(ServiceError, match="email_not_replayable"):
        service.replay(actor, org, identifier)
    assert api.session.scalar(select(func.count()).select_from(EmailAttemptRow)) == 20


def test_original_operator_revocation_prevents_render_and_replay(api: Api) -> None:
    org, identifier = queued(api)
    actor, user = context(api, org)
    service = email_service(api.session)
    claim = service.claim(org, identifier)
    assert claim
    api.session.execute(
        update(GrantRow)
        .where(GrantRow.organization_id == org, GrantRow.user_id == user)
        .values(revoked=True)
    )
    with pytest.raises(ServiceError):
        service.render(claim, "https://app.example.com")
    skipped = service.skip(claim)
    assert skipped.state == "skipped" and skipped.error_code == "email_authority_unavailable"
    with pytest.raises(ServiceError):
        service.replay(actor, org, identifier)


def test_retained_notice_uses_current_owning_source_access(api: Api) -> None:
    org = api.organization()
    workspace = api.workspace(org)
    project_id = UUID(project(api, org, workspace))
    actor, user = context(api, org)
    activate(
        api,
        actor,
        org,
        workspace,
        project_id,
        RuleDefinition(
            trigger="project.phase.changed",
            actions=[NotifyAction(kind="notify", recipients=[user])],
        ),
    )
    services = compose(api.session)
    services.projects.transition(actor, org, workspace, project_id, "active", 1, "Begin")
    assert (
        process_automation(api.session, message(api, org, "project.transitioned")).state
        == "completed"
    )
    notice = services.notifications.inbox(actor, org, workspace)[0][0].notice
    service = email_service(api.session)
    delivery = service.queue(actor, org, "notice", notice.id, user, True, "Requested notice")
    content = service.render(delivery, "https://app.example.com")
    assert content.recipient == "admin@example.com"
    assert content.text.endswith("https://app.example.com/")
    assert str(project_id) not in content.text and "payload" not in content.text
    services.projects.transition(actor, org, workspace, project_id, "closing", 2, "Complete")
    # The owner still resolves the exact retained notice after project state changes.
    assert service.render(delivery, "https://app.example.com") == content
