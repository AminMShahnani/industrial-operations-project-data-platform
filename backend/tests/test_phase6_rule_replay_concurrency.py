import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid7

import pytest
from alembic import command
from alembic.config import Config
from operations.composition import compose
from operations.contracts import ServiceError
from operations.modules.audit.infrastructure.persistence import AuditRow
from operations.modules.automation.application.contracts import MetadataAction, RuleDefinition
from operations.modules.automation.application.events import DeliveryMessage
from operations.modules.automation.domain.reliability import delivery_id
from operations.modules.identity.application.contracts import Principal, RequestContext
from operations.modules.organizations.application.contracts import OrganizationSettings
from operations.modules.projects.application.contracts import LifecycleDefinition, ProjectContext
from operations.platform.config import Settings
from operations.platform.database import create_database_engine
from operations.worker import process_automation
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.orm import Session

pytestmark = pytest.mark.e2e


def test_committed_run_review_concurrent_apply_preserves_one_effect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = os.environ.get("IOP_BROWSER_DATABASE_URL")
    if not url:
        pytest.skip("Dedicated committed browser database required")
    assert url.rsplit("/", 1)[-1].endswith("_browser_test")
    settings = Settings(database_url=SecretStr(url), environment="test")  # type: ignore[call-arg]
    monkeypatch.setenv("IOP_DATABASE_URL", url)
    command.upgrade(Config("alembic.ini"), "head")
    principal = Principal("https://rule-replay.example.test", str(uuid7()))
    actor = RequestContext(principal, uuid7(), uuid7())
    engine = create_database_engine(settings)
    try:
        with Session(engine) as session, session.begin():
            services = compose(session, principal)
            services.identity.bootstrap(principal, "Committed automation replay fixture")
            org = services.organizations.create(
                actor,
                "Rule replay",
                OrganizationSettings(),
                principal.subject,
                "rule-replay@example.test",
            ).id
            workspace = services.workspaces.create(actor, org, "Rule replay").id
            project = services.projects.create(
                actor, org, workspace, "Rule replay", ProjectContext(), LifecycleDefinition()
            ).id
            rule = services.automation.create(
                actor,
                org,
                workspace,
                project,
                "Rule replay",
                RuleDefinition(
                    trigger="project.phase.changed",
                    actions=[MetadataAction(kind="set_metadata", description="Recovered once")],
                ),
            )
            preview = services.automation.activate(actor, org, workspace, rule.id, 1, 1, True, None)
            services.automation.activate(
                actor, org, workspace, rule.id, 1, 1, False, preview.content_sha256
            )
            services.projects.transition(actor, org, workspace, project, "active", 1, "Fixture")
            source = session.scalar(
                select(AuditRow).where(
                    AuditRow.organization_id == org, AuditRow.type == "project.transitioned"
                )
            )
            assert source
            run = services.automation.store.event_runs(org, source.id)[0]
            message = DeliveryMessage(
                organization_id=org, delivery_id=delivery_id(source.id, "automation")
            )
            services.automation.failed(org, run.id, "fixture_failure", False)
            review = services.automation.review_replay(actor, org, workspace, rule.id, run.id)

        def apply(_: int) -> str:
            with Session(engine) as session, session.begin():
                try:
                    result = compose(session, principal).automation.review_replay(
                        actor,
                        org,
                        workspace,
                        rule.id,
                        run.id,
                        dry_run=False,
                        review_sha256=review.review_sha256,
                        reason="Concurrent reviewed recovery",
                    )
                    assert result.applied and result.run.attempts == 1
                    return "applied"
                except ServiceError as error:
                    assert error.code == "automation_replay_review_required"
                    return "stale"

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(apply, range(8)))
        assert results.count("applied") == 1 and results.count("stale") == 7
        with Session(engine) as session, session.begin():
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(AuditRow)
                    .where(
                        AuditRow.aggregate_id == run.id, AuditRow.type == "automation.run.replayed"
                    )
                )
                == 1
            )
            assert process_automation(session, message).state == "completed"
            assert process_automation(session, message).state == "completed"
            history = compose(session, principal).automation.history(
                actor, org, workspace, rule.id, run.id
            )
            assert len(history.attempts) == 2 and len(history.receipts) == 1
    finally:
        engine.dispose()
