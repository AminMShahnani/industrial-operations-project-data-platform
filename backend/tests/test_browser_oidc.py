import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid7

import pytest
from alembic import command
from alembic.config import Config
from operations.composition import compose
from operations.modules.audit.infrastructure.persistence import AuditRow
from operations.modules.automation.application.contracts import NotifyAction, RuleDefinition
from operations.modules.automation.application.events import DeliveryMessage
from operations.modules.automation.domain.reliability import delivery_id
from operations.modules.iam.application.contracts import Role, Scope, ScopeType
from operations.modules.identity.application.contracts import Principal, RequestContext
from operations.modules.organizations.application.contracts import OrganizationSettings
from operations.modules.projects.application.contracts import ProjectRole
from operations.platform.config import Settings
from operations.platform.database import create_database_engine
from operations.worker import process_automation
from playwright.sync_api import expect, sync_playwright
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.orm import Session

pytestmark = pytest.mark.e2e


def wait_for(url: str, process: subprocess.Popen[bytes]) -> None:
    for _ in range(100):
        if process.poll() is not None:
            raise AssertionError("Owned test service exited before readiness")
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return
        except urllib.error.URLError, TimeoutError:
            time.sleep(0.2)
    raise AssertionError("Owned test service did not become ready")


def test_real_oidc_pkce_login_and_workspace_creation(monkeypatch: pytest.MonkeyPatch) -> None:
    url = os.environ.get("IOP_BROWSER_DATABASE_URL")
    if not url:
        pytest.skip("Opt-in browser suite requires IOP_BROWSER_DATABASE_URL and oidc-dev profile")
    assert url.rsplit("/", 1)[-1].endswith("_browser_test"), "Use a dedicated browser test database"
    issuer = "http://127.0.0.1:58080/realms/operations"
    settings = Settings(  # type: ignore[call-arg]
        database_url=SecretStr(url),
        environment="test",
        oidc_issuer=issuer,
        oidc_jwks_url=issuer + "/protocol/openid-connect/certs",
        oidc_audience="operations-api",
        oidc_profile="keycloak",
    )
    monkeypatch.setenv("IOP_DATABASE_URL", url)
    command.upgrade(Config("alembic.ini"), "head")
    principal = Principal(issuer, "dev-platform")
    engine = create_database_engine(settings)
    with Session(engine) as session, session.begin():
        services = compose(session, principal)
        if not services.identity.store.platform_admin(principal):
            services.identity.bootstrap(principal, "Isolated browser test fixture operator")
        organization = services.organizations.create(
            RequestContext(principal, uuid7(), uuid7()),
            "Browser test organization",
            OrganizationSettings(),
            principal.subject,
            "dev-platform@example.com",
        )
    environment = dict(os.environ)
    environment.update(
        {
            "IOP_ENVIRONMENT": "test",
            "IOP_DATABASE_URL": url,
            "IOP_OIDC_ISSUER": issuer,
            "IOP_OIDC_JWKS_URL": issuer + "/protocol/openid-connect/certs",
            "IOP_OIDC_AUDIENCE": "operations-api",
            "IOP_OIDC_PROFILE": "keycloak",
            "VITE_API_URL": "http://127.0.0.1:8077",
            "VITE_OIDC_AUTHORITY": issuer,
            "VITE_OIDC_CLIENT_ID": "operations-web",
        }
    )
    creation_flags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0)) if os.name == "nt" else 0
    api = subprocess.Popen(
        [
            str(Path(".venv/Scripts/python.exe" if os.name == "nt" else ".venv/bin/python")),
            "-m",
            "uvicorn",
            "operations.main:app_factory",
            "--factory",
            "--host",
            "127.0.0.1",
            "--port",
            "8077",
        ],
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creation_flags,
    )
    web = subprocess.Popen(
        [
            "node",
            "frontend/node_modules/vite/bin/vite.js",
            "frontend",
            "--host",
            "127.0.0.1",
            "--port",
            "5173",
            "--strictPort",
        ],
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creation_flags,
    )
    try:
        wait_for("http://127.0.0.1:8077/api/v1/health/live", api)
        wait_for("http://127.0.0.1:5173", web)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                page = browser.new_page()
                page.goto("http://localhost:5173/")
                page.get_by_role("button", name="Sign in", exact=True).click()
                page.locator("#username").fill("dev-platform")
                page.locator("#password").fill(
                    os.environ.get(
                        "IOP_OIDC_DEV_PASSWORD",
                        "development-only-change-me",
                    )
                )
                with page.expect_response("**/api/v1/me") as identity_response:
                    page.locator("#kc-login").click()
                response = identity_response.value
                assert response.status == 200
                assert str(organization.id) in [
                    item["organization_id"]
                    for item in identity_response.value.json()["memberships"]
                ]
                expect(
                    page.get_by_role("heading", name="Organization and workspace")
                ).to_be_visible()
                page.get_by_label("Organization", exact=True).select_option(str(organization.id))
                page.get_by_label("Workspace name", exact=True).fill("Browser created workspace")
                page.get_by_role("button", name="Create workspace", exact=True).click()
                expect(
                    page.get_by_role("status").filter(has_text="Workspace created.")
                ).to_be_visible()
                page.get_by_label("Project name", exact=True).fill("Browser created project")
                with page.expect_response(
                    lambda response: (
                        response.request.method == "POST" and response.url.endswith("/projects")
                    )
                ) as project_response:
                    page.get_by_role("button", name="Create project", exact=True).click()
                created_project = project_response.value.json()
                notice_workspace = UUID(created_project["workspace_id"])
                notice_project = UUID(created_project["id"])
                actor = RequestContext(principal, uuid7(), uuid7())
                with Session(engine) as session, session.begin():
                    services = compose(session, principal)
                    user = services.authorization.user(actor, organization.id)
                    rule = services.automation.create(
                        actor,
                        organization.id,
                        notice_workspace,
                        notice_project,
                        "Browser notice",
                        RuleDefinition(
                            trigger="project.phase.changed",
                            actions=[NotifyAction(kind="notify", recipients=[user.id])],
                        ),
                    )
                    preview = services.automation.activate(
                        actor, organization.id, notice_workspace, rule.id, 1, 1, True, None
                    )
                    services.automation.activate(
                        actor,
                        organization.id,
                        notice_workspace,
                        rule.id,
                        1,
                        1,
                        False,
                        preview.content_sha256,
                    )
                expect(
                    page.get_by_role("status").filter(has_text="Project created.")
                ).to_be_visible()
                page.get_by_label("Transition reason", exact=True).fill("Browser acceptance review")
                page.get_by_role("button", name="Preview transition", exact=True).click()
                expect(
                    page.get_by_text(
                        "Transition preview ready. Review it before applying.", exact=True
                    )
                ).to_be_visible()
                page.get_by_role("button", name="Apply transition", exact=True).click()
                expect(page.get_by_text("Project state changed.", exact=True)).to_be_visible()
                with Session(engine) as session, session.begin():
                    source = session.scalar(
                        select(AuditRow).where(
                            AuditRow.organization_id == organization.id,
                            AuditRow.aggregate_id == notice_project,
                            AuditRow.type == "project.transitioned",
                        )
                    )
                    assert source
                    notice_message = DeliveryMessage(
                        organization_id=organization.id,
                        delivery_id=delivery_id(source.id, "automation"),
                    )
                    assert process_automation(session, notice_message).state == "completed"
                    assert process_automation(session, notice_message).state == "completed"
                notifications = page.get_by_role("region", name="Notifications")
                notifications.get_by_role("button", name="Refresh notifications").click()
                expect(notifications.get_by_text("Operational notice", exact=True)).to_be_visible()
                notifications.get_by_role("button", name="Mark as read", exact=True).click()
                expect(notifications.get_by_text("Read", exact=True)).to_be_visible()
                notifications.get_by_role("button", name="Refresh notifications").click()
                expect(notifications.get_by_text("Read", exact=True)).to_be_visible()
                page.get_by_label("Group name", exact=True).fill("Browser department")
                page.get_by_role("button", name="Create department or team", exact=True).click()
                expect(page.get_by_text("Department or team created.", exact=True)).to_be_visible()
                page.get_by_text("Create a master data type", exact=True).click()
                page.get_by_label("Type code", exact=True).fill("browser-sites")
                page.get_by_label("Type name", exact=True).fill("Browser sites")
                page.get_by_role("button", name="Create type", exact=True).click()
                expect(page.get_by_text("Master data type created.", exact=True)).to_be_visible()
                page.get_by_label("Record code", exact=True).fill("SITE-1")
                page.get_by_label("Record name", exact=True).fill("Browser site")
                page.get_by_role("button", name="Create record", exact=True).click()
                expect(page.get_by_text("Master data record created.", exact=True)).to_be_visible()
                page.get_by_label("Import file", exact=True).set_input_files(
                    {
                        "name": "sites.csv",
                        "mimeType": "text/csv",
                        "buffer": b"code,name\nSITE-2,Imported site\n",
                    }
                )
                page.get_by_role("button", name="Preview import", exact=True).click()
                expect(
                    page.get_by_text(
                        "Import preview ready. No records have been written.", exact=True
                    )
                ).to_be_visible()
                page.get_by_role("button", name="Apply import", exact=True).click()
                expect(page.get_by_text("Import applied.", exact=True)).to_be_visible()
                with page.expect_download() as download:
                    page.get_by_role("button", name="Export CSV", exact=True).click()
                assert download.value.suggested_filename == "master-data-1.csv"
                page.get_by_label("Component palette", exact=True).select_option("integer")
                page.get_by_role("button", name="Add component", exact=True).click()
                page.get_by_label("Stable field key", exact=True).fill("count")
                page.get_by_label("Field label", exact=True).fill("Reported count")
                page.get_by_label("Form name", exact=True).fill("Browser report")
                page.get_by_role("button", name="Create form draft", exact=True).click()
                expect(
                    page.get_by_role("status").filter(has_text="Form draft created.")
                ).to_be_visible()
                page.get_by_role("button", name="Preview publication", exact=True).click()
                expect(
                    page.get_by_role("button", name="Publish reviewed version", exact=True)
                ).to_be_visible()
                page.get_by_role("button", name="Publish reviewed version", exact=True).click()
                expect(
                    page.get_by_role("status").filter(has_text="Version published.")
                ).to_be_visible()
                page.get_by_role("button", name="Start submission draft", exact=True).click()
                expect(
                    page.get_by_role("status").filter(has_text="Submission draft created.")
                ).to_be_visible()
                page.get_by_label("Reported count", exact=True).fill("invalid")
                expect(
                    page.get_by_role("status").filter(has_text="invalid submission values")
                ).to_be_visible()
                page.get_by_label("Reported count", exact=True).fill("4")
                expect(page.get_by_role("status").filter(has_text="Draft saved.")).to_be_visible()
                page.get_by_role("button", name="Validate form", exact=True).click()
                expect(
                    page.get_by_role("status").filter(has_text="Validation passed.")
                ).to_be_visible()
                page.get_by_label("Submission reason", exact=True).fill("Browser acceptance report")
                page.get_by_role("button", name="Submit form", exact=True).click()
                expect(
                    page.get_by_role("status").filter(
                        has_text="Submission preserved as an immutable snapshot."
                    )
                ).to_be_visible()
                form_id = page.get_by_label("Form", exact=True).input_value()
                workspace_id = page.get_by_label("Workspace", exact=True).input_value()
                project_id = page.get_by_label("Project", exact=True).input_value()
                # Seed the development identity through audited application services.
                # Its subsequent review actions must use a separate real PKCE login.
                with Session(engine) as session, session.begin():
                    services = compose(session, principal)
                    owner_context = RequestContext(principal, uuid7(), uuid7())
                    token = services.identity.invite(
                        owner_context,
                        "dev-reviewer@example.com",
                        Role.APPROVER,
                        Scope(organization.id, ScopeType.WORKSPACE, UUID(workspace_id)),
                    )
                    reviewer_principal = Principal(
                        issuer, "dev-reviewer", "dev-reviewer@example.com", True
                    )
                    reviewer_user = services.identity.accept(
                        RequestContext(reviewer_principal, uuid7(), uuid7()), organization.id, token
                    )
                    services.projects.add_member(
                        owner_context,
                        organization.id,
                        UUID(workspace_id),
                        UUID(project_id),
                        reviewer_user.id,
                        ProjectRole.APPROVER,
                        None,
                        None,
                    )
                page.get_by_text("Workflow administration", exact=True).click()
                page.get_by_role("button", name="Refresh forms for workflow", exact=True).click()
                page.get_by_label("Approver email", exact=True).fill("dev-reviewer@example.com")
                page.get_by_role("button", name="Find eligible approvers", exact=True).click()
                page.get_by_role(
                    "button", name="Add approver dev-reviewer@example.com", exact=True
                ).click()
                page.get_by_label("Workflow name", exact=True).fill("Browser independent approval")
                page.get_by_label("Published form", exact=True).select_option(form_id)
                page.get_by_role("button", name="Create workflow draft", exact=True).click()
                expect(
                    page.get_by_role("button", name="Preview workflow activation", exact=True)
                ).to_be_visible()
                page.get_by_role("button", name="Preview workflow activation", exact=True).click()
                page.get_by_role("button", name="Apply workflow activation", exact=True).click()
                expect(page.get_by_label("Workflow version", exact=True)).to_have_value("1")
                expect(
                    page.get_by_role("button", name="Preview workflow activation", exact=True)
                ).to_have_count(0)
                page.get_by_text("Schedule administration", exact=True).click()
                page.get_by_label("Schedule name", exact=True).fill("Browser scheduled report")
                page.get_by_label("Schedule form ID", exact=True).fill(form_id)
                page.get_by_role("button", name="Create schedule draft", exact=True).click()
                expect(
                    page.get_by_role("status").filter(has_text="Schedule draft created.")
                ).to_be_visible()
                with page.expect_request(
                    lambda request: request.url.endswith("/activate")
                ) as activation_request:
                    page.get_by_role("button", name="Preview activation", exact=True).click()
                authorization = activation_request.value.headers["authorization"]
                expect(
                    page.get_by_role("button", name="Activate reviewed schedule", exact=True)
                ).to_be_visible()
                page.get_by_role("button", name="Activate reviewed schedule", exact=True).click()
                expect(
                    page.get_by_role("status").filter(has_text="Schedule activated.")
                ).to_be_visible()
                schedule_id = page.get_by_label("Schedule", exact=True).input_value()
                workspace_id = page.get_by_label("Workspace", exact=True).input_value()
                route = f"http://127.0.0.1:8077/api/v1/organizations/{organization.id}/workspaces/{workspace_id}"
                now = datetime.now(UTC)
                window = {
                    "start": now.isoformat(),
                    "end": (now + timedelta(days=30)).isoformat(),
                    "dry_run": False,
                }

                def post(url: str, body: dict[str, object]) -> dict[str, object]:
                    request = urllib.request.Request(
                        url,
                        data=json.dumps(body).encode(),
                        headers={
                            "Authorization": authorization,
                            "Content-Type": "application/json",
                        },
                        method="POST",
                    )
                    with urllib.request.urlopen(request, timeout=30) as response:
                        result: dict[str, object] = json.load(response)
                        return result

                with ThreadPoolExecutor(max_workers=2) as pool:
                    futures = [
                        pool.submit(post, route + f"/schedules/{schedule_id}/materialize", window)
                        for _ in range(2)
                    ]
                    results = [future.result() for future in futures]
                assert sum(int(str(result["created"])) for result in results) == 30
                page.get_by_role("button", name="Refresh My Work", exact=True).click()
                expect(
                    page.get_by_role("button", name="Claim task", exact=True).first
                ).to_be_visible()
                with page.expect_request(
                    lambda request: request.url.endswith("/start")
                ) as claim_request:
                    page.get_by_role("button", name="Claim task", exact=True).first.click()
                expect(page.get_by_role("status").filter(has_text="Task claimed.")).to_be_visible()
                with ThreadPoolExecutor(max_workers=2) as pool:
                    futures = [
                        pool.submit(post, claim_request.value.url, {"expected_revision": 1})
                        for _ in range(2)
                    ]
                    claims = [future.result() for future in futures]
                assert claims[0]["submission_id"] == claims[1]["submission_id"]
                page.get_by_label("Reported count", exact=True).fill("7")
                expect(page.get_by_role("status").filter(has_text="Draft saved.")).to_be_visible()
                page.get_by_label("Submission reason", exact=True).fill("Scheduled work complete")
                page.get_by_role("button", name="Submit form", exact=True).click()
                expect(
                    page.get_by_role("status").filter(
                        has_text="Submission preserved as an immutable snapshot."
                    )
                ).to_be_visible()
                page.get_by_role("button", name="Refresh My Work", exact=True).click()
                expect(
                    page.get_by_text("awaiting_review", exact=False)
                    .filter(has_text="Browser scheduled report")
                    .first
                ).to_be_visible()
                reviewer_context = browser.new_context()
                review_page = reviewer_context.new_page()
                review_page.goto("http://localhost:5173/")
                review_page.get_by_role("button", name="Sign in", exact=True).click()
                review_page.locator("#username").fill("dev-reviewer")
                review_page.locator("#password").fill(
                    os.environ.get("IOP_OIDC_DEV_PASSWORD", "development-only-change-me")
                )
                with review_page.expect_response("**/api/v1/me") as reviewer_identity:
                    review_page.locator("#kc-login").click()
                assert reviewer_identity.value.status == 200
                review_page.get_by_label("Organization", exact=True).select_option(
                    str(organization.id)
                )
                review_page.get_by_label("Workspace", exact=True).select_option(workspace_id)
                review_page.get_by_label("Project", exact=True).select_option(project_id)
                review_page.get_by_role("button", name="Refresh review inbox", exact=True).click()
                review_page.get_by_role("button", name="Review record", exact=True).click()
                review_page.get_by_label("Decision reason", exact=True).fill(
                    "Correct the reported count"
                )
                review_page.get_by_role("button", name="Return for correction", exact=True).click()
                expect(
                    review_page.get_by_role("button", name="Approve record", exact=True)
                ).to_have_count(0)
                with page.expect_response(
                    lambda response: "/workflow-instances/" in response.url
                ) as owner_history:
                    page.get_by_role("button", name="Refresh record history", exact=True).click()
                assert owner_history.value.status == 200, owner_history.value.text()
                page.get_by_label("Decision reason", exact=True).fill(
                    "Correct count with preserved original evidence"
                )
                page.get_by_role("button", name="Create correction draft", exact=True).click()
                page.get_by_label("Reported count", exact=True).fill("8")
                expect(page.get_by_role("status").filter(has_text="Draft saved.")).to_be_visible()
                page.get_by_label("Submission reason", exact=True).fill("Corrected scheduled work")
                page.get_by_role("button", name="Submit form", exact=True).click()
                expect(
                    page.get_by_role("status").filter(
                        has_text="Submission preserved as an immutable snapshot."
                    )
                ).to_be_visible()
                review_page.get_by_role("button", name="Refresh review inbox", exact=True).click()
                with review_page.expect_response(
                    lambda response: "/workflow-instances/" in response.url
                ) as review_history:
                    review_page.get_by_role("button", name="Review record", exact=True).click()
                review_page.get_by_label("Decision reason", exact=True).fill(
                    "Independent evidence approval"
                )
                reviewed = review_history.value.json()["instance"]
                approval_authorization = review_history.value.request.headers["authorization"]
                approval_body = {
                    "expected_revision": reviewed["revision"],
                    "idempotency_key": str(uuid7()),
                    "kind": "approve",
                    "reason": "Independent evidence approval",
                }

                def approve() -> dict[str, object]:
                    request = urllib.request.Request(
                        route + f"/workflow-instances/{reviewed['id']}/actions",
                        data=json.dumps(approval_body).encode(),
                        headers={
                            "Authorization": approval_authorization,
                            "Content-Type": "application/json",
                        },
                        method="POST",
                    )
                    with urllib.request.urlopen(request, timeout=30) as response:
                        result: dict[str, object] = json.load(response)
                        return result

                with ThreadPoolExecutor(max_workers=2) as pool:
                    approvals = [pool.submit(approve) for _ in range(2)]
                    outcomes = [future.result() for future in approvals]
                assert outcomes[0] == outcomes[1] and outcomes[0]["state"] == "approved"
                review_page.get_by_role("button", name="Refresh record history", exact=True).click()
                expect(
                    review_page.get_by_role("button", name="Approve record", exact=True)
                ).to_have_count(0)
                page.get_by_role("button", name="Refresh My Work", exact=True).click()
                expect(
                    page.get_by_text("approved", exact=False)
                    .filter(has_text="Browser scheduled report")
                    .first
                ).to_be_visible()
                reviewer_context.close()
                assert page.evaluate(
                    "Object.keys(localStorage).concat(Object.keys(sessionStorage))"
                    ".every(key => !key.startsWith('oidc.user:'))"
                )
                page.get_by_role("button", name="Sign out here").click()
                expect(page.get_by_role("button", name="Sign in", exact=True)).to_be_visible()
            finally:
                browser.close()
        with Session(engine) as session:
            event = session.scalar(
                select(AuditRow).where(
                    AuditRow.organization_id == organization.id,
                    AuditRow.type == "workspace.created",
                )
            )
            assert event is not None and event.actor_subject == "dev-platform"
            approval = session.scalar(
                select(AuditRow).where(
                    AuditRow.organization_id == organization.id,
                    AuditRow.type == "workflow.action.approve",
                )
            )
            assert approval is not None and approval.actor_subject == "dev-reviewer"
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(AuditRow)
                    .where(
                        AuditRow.organization_id == organization.id,
                        AuditRow.type == "workflow.action.approve",
                    )
                )
                == 1
            )
    finally:
        for process in (web, api):
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        engine.dispose()
