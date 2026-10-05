import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from uuid import uuid7

import pytest
from alembic import command
from alembic.config import Config
from operations.composition import compose
from operations.modules.audit.infrastructure.persistence import AuditRow
from operations.modules.identity.application.contracts import Principal, RequestContext
from operations.modules.organizations.application.contracts import OrganizationSettings
from operations.platform.config import Settings
from operations.platform.database import create_database_engine
from playwright.sync_api import expect, sync_playwright
from pydantic import SecretStr
from sqlalchemy import select
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
                expect(page.get_by_role("status")).to_have_text("Workspace created.")
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
    finally:
        for process in (web, api):
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        engine.dispose()
