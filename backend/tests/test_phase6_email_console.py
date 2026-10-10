from datetime import UTC, datetime, timedelta
from typing import Literal
from unittest.mock import patch
from uuid import UUID, uuid7

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from operations.composition import compose
from operations.modules.audit.infrastructure.persistence import AuditRow
from operations.modules.iam.application.contracts import Role, Scope, ScopeType
from operations.modules.iam.infrastructure.persistence import GrantRow
from operations.modules.notifications.application.email_contracts import EmailResult
from operations.modules.notifications.infrastructure.email_persistence import EmailAttemptRow
from sqlalchemy import func, select, text, update
from test_oidc import signing_key as signing_key
from test_phase1_api import Api
from test_phase1_api import api as api
from test_phase6_actions import context
from test_phase6_email_delivery import queued

pytestmark = pytest.mark.integration


def route(org: UUID) -> str:
    return f"/api/v1/organizations/{org}/email-deliveries"


def failed(api: Api, state: Literal["failed", "uncertain"] = "failed") -> tuple[UUID, UUID]:
    org, identifier = queued(api)
    service = compose(api.session).email
    claim = service.claim(org, identifier)
    assert claim
    service.finish(claim, EmailResult(state))
    return org, identifier


def test_operator_scope_minimal_evidence_and_unauthorized_writes(api: Api) -> None:
    org, identifier = failed(api)
    workspace = api.workspace(org)
    api.accept(org, api.invitation(org, workspace, "WorkspaceAdmin"))
    endpoint = route(org) + f"/{identifier}"
    assert api.client.get(route(org)).status_code == 401
    limited = api.headers("invitee", "invitee@example.com")
    for path in (route(org), endpoint):
        assert api.client.get(path, headers=limited).status_code == 403
    assert api.client.post(endpoint + "/replay", headers=limited, json={}).status_code == 403
    foreign = api.organization("foreign")
    assert (
        api.client.get(
            route(foreign) + f"/{identifier}", headers=api.headers("foreign")
        ).status_code
        == 404
    )
    assert (
        api.client.post(
            route(foreign) + f"/{identifier}/replay", headers=api.headers("foreign"), json={}
        ).status_code
        == 404
    )
    detail = api.client.get(endpoint, headers=api.headers("admin"))
    assert detail.status_code == 200 and len(detail.json()["attempts"]) == 1
    assert set(detail.json()) == {"delivery", "attempts"}
    for forbidden in (
        "invitee@example.com",
        "token_digest",
        "subject",
        "password",
        "smtp_profile",
        "content",
    ):
        assert forbidden not in detail.text
    assert (
        api.client.get(
            route(org), headers=api.headers("admin"), params={"state": "bad"}
        ).status_code
        == 422
    )


def test_public_replay_exact_review_reason_duplicate_and_audit(api: Api) -> None:
    org, identifier = failed(api)
    endpoint = route(org) + f"/{identifier}/replay"
    headers = api.headers("admin")
    count = api.session.scalar(select(func.count()).select_from(AuditRow))
    preview = api.client.post(endpoint, headers=headers, json={})
    assert preview.status_code == 200 and not preview.json()["applied"]
    assert api.session.scalar(select(func.count()).select_from(AuditRow)) == count
    digest = preview.json()["review_sha256"]
    assert (
        api.client.post(
            endpoint, headers=headers, json={"dry_run": False, "reason": "repair"}
        ).status_code
        == 409
    )
    for reason in (None, "  ", "x" * 501):
        assert (
            api.client.post(
                endpoint,
                headers=headers,
                json={"dry_run": False, "review_sha256": digest, "reason": reason},
            ).status_code
            == 422
        )
    body = {"dry_run": False, "review_sha256": digest, "reason": " Provider repair reviewed "}
    result = api.client.post(endpoint, headers=headers, json=body)
    assert result.status_code == 200 and result.json()["applied"]
    assert (
        result.json()["delivery"]["state"] == "retry" and result.json()["delivery"]["attempts"] == 1
    )
    assert api.client.post(endpoint, headers=headers, json=body).status_code == 409
    assert api.session.scalar(select(func.count()).select_from(EmailAttemptRow)) == 1
    audit = api.session.scalar(
        select(AuditRow).where(
            AuditRow.aggregate_id == identifier, AuditRow.type == "email.replayed"
        )
    )
    assert audit and audit.payload["reason"] == "Provider repair reviewed"


def test_uncertain_replay_requires_explicit_duplicate_acknowledgement(api: Api) -> None:
    org, identifier = failed(api, "uncertain")
    endpoint = route(org) + f"/{identifier}/replay"
    headers = api.headers("admin")
    preview = api.client.post(endpoint, headers=headers, json={}).json()
    body = {
        "dry_run": False,
        "review_sha256": preview["review_sha256"],
        "reason": "Provider logs reviewed",
    }
    refused = api.client.post(endpoint, headers=headers, json=body)
    assert (
        refused.status_code == 422
        and refused.json()["code"] == "email_uncertain_acknowledgement_required"
    )
    assert (
        api.client.get(route(org) + f"/{identifier}", headers=headers).json()["delivery"]["state"]
        == "uncertain"
    )
    assert (
        api.client.post(
            endpoint, headers=headers, json={**body, "acknowledge_uncertain": True}
        ).status_code
        == 200
    )


def test_inspection_survives_source_expiry_and_delegation_revocation(api: Api) -> None:
    org, identifier = failed(api)
    endpoint = route(org) + f"/{identifier}"
    headers = api.headers("admin")
    with patch("operations.modules.identity.application.service.datetime") as clock:
        clock.now.return_value = datetime.now(UTC) + timedelta(days=8)
        assert api.client.get(endpoint, headers=headers).status_code == 200
        assert api.client.post(endpoint + "/replay", headers=headers, json={}).status_code == 403
    workspace = api.workspace(org)
    replacement = api.accept(org, api.invitation(org, workspace))
    assert (
        api.client.post(
            f"/api/v1/organizations/{org}/grants",
            headers=headers,
            json={
                "user_id": str(replacement),
                "role": "OrganizationAdmin",
                "scope_type": "organization",
                "scope_id": str(org),
            },
        ).status_code
        == 201
    )
    _, admin = context(api, org)
    api.session.execute(
        update(GrantRow)
        .where(GrantRow.organization_id == org, GrantRow.user_id == admin)
        .values(revoked=True)
    )
    replacement_headers = api.headers("invitee", "invitee@example.com")
    assert api.client.get(endpoint, headers=replacement_headers).status_code == 200
    assert (
        api.client.post(endpoint + "/replay", headers=replacement_headers, json={}).status_code
        == 403
    )
    assert api.client.get(endpoint, headers=headers).status_code == 403


@pytest.mark.parametrize("outcome", ["sent", "skipped", "sending", "pending"])
def test_successful_or_in_progress_email_cannot_be_replayed(api: Api, outcome: str) -> None:
    org, identifier = queued(api)
    service = compose(api.session).email
    if outcome != "pending":
        claim = service.claim(org, identifier)
        assert claim
        if outcome == "skipped":
            service.skip(claim)
        elif outcome == "sent":
            service.finish(claim, EmailResult("sent"))
    assert (
        api.client.post(
            route(org) + f"/{identifier}/replay", headers=api.headers("admin"), json={}
        ).status_code
        == 409
    )


def test_chronological_filtered_cursor_pages_ties_and_foreign_cursor(api: Api) -> None:
    org = api.organization()
    workspace = api.workspace(org)
    actor, _ = context(api, org)
    services = compose(api.session)
    boundary = datetime.now(UTC) + timedelta(hours=1)
    expected: list[tuple[datetime, str]] = []
    for number in range(106):
        stamp = boundary + timedelta(seconds=(105 - number) // 4)
        with patch("operations.modules.notifications.application.email_service.datetime") as clock:
            clock.now.return_value = stamp
            source = services.email.invite(
                actor,
                "recipient@example.test",
                Role.VIEWER,
                Scope(org, ScopeType.WORKSPACE, workspace),
                uuid7(),
                True,
                "Pagination fixture",
            )
            row = services.email.queue(actor, org, "invitation", source.id, None)
            if number < 2:
                clock.now.return_value = stamp + timedelta(seconds=1)
                claim = services.email.claim(org, row.id)
                assert claim
                services.email.finish(claim, EmailResult("sent"))
            else:
                expected.append((stamp, str(row.id)))
    headers = api.headers("admin")
    first = api.client.get(route(org), headers=headers, params={"state": "pending"}).json()
    second = api.client.get(
        route(org), headers=headers, params={"state": "pending", "cursor": first["next_cursor"]}
    ).json()
    assert (
        len(first["items"]) == 100 and len(second["items"]) == 4 and second["next_cursor"] is None
    )
    assert [row["id"] for row in first["items"] + second["items"]] == [
        identifier for _, identifier in sorted(expected)
    ]
    foreign, foreign_id = queued(api)
    assert foreign != org
    for cursor in (foreign_id, uuid7()):
        result = api.client.get(route(org), headers=headers, params={"cursor": str(cursor)})
        assert result.status_code == 422 and result.json()["code"] == "email_cursor_invalid"


def test_populated_index_rollback_preserves_email_evidence(api: Api) -> None:
    org, identifier = failed(api)
    service = compose(api.session).email
    actor, _ = context(api, org)
    before = service.history(actor, org, identifier)
    revision = ScriptDirectory.from_config(Config("alembic.ini")).get_revision("ba6e379cc281")
    assert revision
    with Operations.context(MigrationContext.configure(api.session.connection())):
        revision.module.downgrade()
        assert api.session.scalar(text("SELECT to_regclass('ix_email_created_cursor')")) is None
        assert service.history(actor, org, identifier) == before
        revision.module.upgrade()
    assert api.session.scalar(text("SELECT to_regclass('ix_email_state_cursor')"))
    assert service.history(actor, org, identifier) == before


def test_public_replay_lifetime_attempt_cap_preserves_twenty_attempts(api: Api) -> None:
    org, identifier = queued(api)
    service = compose(api.session).email
    headers = api.headers("admin")
    endpoint = route(org) + f"/{identifier}/replay"
    for number in range(1, 21):
        claim = service.claim(org, identifier)
        assert claim and claim.attempts == number
        service.finish(claim, EmailResult("failed", "fixture_failure"))
        if number < 20:
            review = api.client.post(endpoint, headers=headers, json={})
            assert review.status_code == 200
            applied = api.client.post(
                endpoint,
                headers=headers,
                json={
                    "dry_run": False,
                    "review_sha256": review.json()["review_sha256"],
                    "reason": "Reviewed repair",
                },
            )
            assert applied.status_code == 200
    assert api.client.post(endpoint, headers=headers, json={}).status_code == 409
    evidence = api.client.get(route(org) + f"/{identifier}", headers=headers).json()
    assert len(evidence["attempts"]) == evidence["delivery"]["attempts"] == 20
