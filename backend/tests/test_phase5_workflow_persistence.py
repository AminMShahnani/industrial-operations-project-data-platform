from datetime import UTC, datetime
from uuid import UUID, uuid7

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from operations.modules.forms.infrastructure.persistence import FormVersionRow
from operations.modules.workflows.application.contracts import (
    Workflow,
    WorkflowDefinition,
    WorkflowNode,
    WorkflowTransition,
    WorkflowVersion,
)
from operations.modules.workflows.infrastructure.persistence import WorkflowRepository
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from test_oidc import signing_key as signing_key
from test_phase1_api import Api
from test_phase1_api import api as api
from test_phase3_api import publish, setup

pytestmark = pytest.mark.integration


def test_scoped_version_immutability_occ_and_populated_rollback(api: Api) -> None:
    org, workspace, route, form = setup(api)
    publish(api, route, form)
    store = WorkflowRepository(api.session)
    workflow = Workflow(id=uuid7(), organization_id=org, workspace_id=workspace, name="Review")
    store.create(workflow)
    definition = WorkflowDefinition(
        form_id=UUID(form),
        form_number=1,
        nodes=[
            WorkflowNode(key="start", name="Start", kind="start"),
            WorkflowNode(key="end", name="End", kind="end"),
        ],
        transitions=[WorkflowTransition(source="start", target="end")],
    )
    version = WorkflowVersion(
        id=uuid7(),
        organization_id=org,
        workspace_id=workspace,
        workflow_id=workflow.id,
        number=1,
        definition=definition,
    )
    store.add_version(version)
    assert store.get(uuid7(), workspace, workflow.id) is None
    assert store.version(org, uuid7(), workflow.id, 1) is None
    assert store.list_workflows(org, workspace, None, None) == [workflow]
    assert store.versions(org, workspace, workflow.id, None) == [version]
    assert not store.save_version(version.model_copy(update={"revision": 3}), 2)
    pin = api.session.scalar(
        select(FormVersionRow).where(
            FormVersionRow.organization_id == org,
            FormVersionRow.form_id == UUID(form),
            FormVersionRow.number == 1,
        )
    )
    assert pin
    activated = version.model_copy(
        update={
            "state": "active",
            "revision": 2,
            "form_version_id": pin.id,
            "activated_at": datetime.now(UTC),
            "content_sha256": "a" * 64,
        }
    )
    assert store.save_version(activated, 1)
    assert store.save(workflow.model_copy(update={"revision": 2, "active_number": 1}), 1)
    with pytest.raises(DBAPIError), api.session.begin_nested():
        store.save_version(activated.model_copy(update={"revision": 3}), 2)
    for command in (
        "DELETE FROM workflow_versions WHERE id=:id",
        "UPDATE workflow_versions SET definition='{}', revision=revision+1 WHERE id=:id",
        "TRUNCATE workflows CASCADE",
    ):
        with pytest.raises(DBAPIError), api.session.begin_nested():
            api.session.execute(text(command), {"id": version.id})
    migration = ScriptDirectory.from_config(Config("alembic.ini")).get_revision("e049d194ba38")
    assert migration
    with (
        pytest.raises(DBAPIError),
        api.session.begin_nested(),
        Operations.context(MigrationContext.configure(api.session.connection())),
    ):
        migration.module.downgrade()
    assert store.version(org, workspace, workflow.id, 1) == activated


def test_activation_rejects_form_pin_from_another_scope(api: Api) -> None:
    org, workspace, route, form = setup(api)
    publish(api, route, form)
    other = api.workspace(org)
    store = WorkflowRepository(api.session)
    row = Workflow(id=uuid7(), organization_id=org, workspace_id=other, name="Wrong scope")
    store.create(row)
    definition = WorkflowDefinition(
        form_id=UUID(form),
        form_number=1,
        nodes=[
            WorkflowNode(key="start", name="Start", kind="start"),
            WorkflowNode(key="end", name="End", kind="end"),
        ],
        transitions=[WorkflowTransition(source="start", target="end")],
    )
    pin = api.session.scalar(select(FormVersionRow).where(FormVersionRow.form_id == UUID(form)))
    assert pin
    with pytest.raises(DBAPIError), api.session.begin_nested():
        store.add_version(
            WorkflowVersion(
                id=uuid7(),
                organization_id=org,
                workspace_id=other,
                workflow_id=row.id,
                number=1,
                definition=definition,
                state="active",
                activated_at=datetime.now(UTC),
                form_version_id=pin.id,
                content_sha256="a" * 64,
            )
        )
