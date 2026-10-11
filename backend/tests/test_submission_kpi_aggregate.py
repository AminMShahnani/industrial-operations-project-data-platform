from datetime import UTC, datetime
from typing import cast
from unittest.mock import Mock
from uuid import uuid4

import pytest
from operations.contracts import ServiceError
from operations.modules.forms.application.contracts import (
    Component,
    Form,
    FormDefinition,
    FormVersion,
    Section,
)
from operations.modules.forms.application.service import FormService
from operations.modules.identity.application.contracts import Principal, RequestContext
from operations.modules.submissions.application.contracts import (
    SubmissionAggregateGroup,
    SubmissionAggregateQuery,
    SubmissionStore,
)
from operations.modules.submissions.application.service import SubmissionService
from operations.modules.submissions.infrastructure.persistence import SubmissionRepository
from sqlalchemy.sql.elements import ClauseElement

ORG, WORKSPACE, FORM = uuid4(), uuid4(), uuid4()
ACTOR = RequestContext(Principal("https://issuer.test", "manager"), uuid4(), uuid4())


class _Forms:
    def __init__(self, fields: list[Component]) -> None:
        self.form_row = Form(
            id=FORM,
            organization_id=ORG,
            workspace_id=WORKSPACE,
            project_id=None,
            name="Operations KPI source",
            version=1,
        )
        self.version_row = FormVersion(
            id=uuid4(),
            organization_id=ORG,
            workspace_id=WORKSPACE,
            form_id=FORM,
            number=1,
            state="published",
            definition=FormDefinition(
                sections=[Section(key="main", label="Main", components=fields)]
            ),
        )
        self.required: list[str] = []
        self.denied = False

    def form(self, *_args: object, **_kwargs: object) -> Form:
        return self.form_row

    def require(self, *_args: object, **_kwargs: object) -> None:
        self.required.append(cast(str, _args[4]))
        if self.denied:
            raise ServiceError(403, "access_denied")

    def version(self, *_args: object, **_kwargs: object) -> tuple[Form, FormVersion]:
        return self.form_row, self.version_row


class _Store:
    def __init__(self) -> None:
        self.query: SubmissionAggregateQuery | None = None

    def aggregate(
        self, _org: object, _workspace: object, query: SubmissionAggregateQuery
    ) -> list[SubmissionAggregateGroup]:
        self.query = query
        return [SubmissionAggregateGroup(group="high", value=12.5)]


def _fields(*, owner_only: bool = False, user_group: bool = False) -> list[Component]:
    from operations.modules.forms.application.contracts import FieldPermissions

    return [
        Component(key="report_date", kind="date", label="Report date"),
        Component(key="amount", kind="decimal", label="Amount"),
        Component(
            key="severity",
            kind="user" if user_group else "select",
            label="Severity",
            choices=[] if user_group else ["high", "low"],
            permissions=FieldPermissions(read="owner" if owner_only else "all"),
        ),
    ]


def _query() -> SubmissionAggregateQuery:
    today = datetime.now(UTC).date()
    return SubmissionAggregateQuery(
        form_id=FORM,
        form_number=1,
        time_field="report_date",
        start_date=today,
        end_date=today,
        metric="sum",
        source_field="amount",
        group_field="severity",
    )


def test_submission_aggregate_rechecks_scope_and_uses_pinned_form_version() -> None:
    forms, store = _Forms(_fields()), _Store()
    service = SubmissionService(cast(SubmissionStore, store), cast(FormService, forms))

    result = service.aggregate(ACTOR, ORG, WORKSPACE, _query())

    assert forms.required == ["submission.read"]
    assert store.query is not None and store.query.form_number == 1
    assert result.groups[0].group == "high"


@pytest.mark.parametrize(
    ("owner_only", "user_group", "error"),
    [
        (True, False, "aggregate_owner_only_field_not_allowed"),
        (False, True, "aggregate_user_group_not_allowed"),
    ],
)
def test_submission_aggregate_rejects_identity_bearing_fields(
    owner_only: bool, user_group: bool, error: str
) -> None:
    forms, store = _Forms(_fields(owner_only=owner_only, user_group=user_group)), _Store()
    service = SubmissionService(cast(SubmissionStore, store), cast(FormService, forms))

    with pytest.raises(ServiceError, match=error):
        service.aggregate(ACTOR, ORG, WORKSPACE, _query())
    assert store.query is None


def test_submission_aggregate_fails_before_query_without_scoped_permission() -> None:
    forms, store = _Forms(_fields()), _Store()
    forms.denied = True
    service = SubmissionService(cast(SubmissionStore, store), cast(FormService, forms))

    with pytest.raises(ServiceError, match="access_denied"):
        service.aggregate(ACTOR, ORG, WORKSPACE, _query())
    assert store.query is None


def test_postgres_aggregate_sql_is_scoped_submitted_and_identity_free() -> None:
    session = Mock()
    session.execute.return_value.all.return_value = [("high", 12.5)]
    from sqlalchemy.orm import Session

    repository = SubmissionRepository(cast(Session, session))

    result = repository.aggregate(ORG, WORKSPACE, _query())

    statement = cast(ClauseElement, session.execute.call_args.args[0])
    sql = str(statement)
    assert "organization_id" in sql and "workspace_id" in sql
    assert "form_number" in sql and "state" in sql
    assert "owner_id" not in sql and "submissions.id" not in sql
    assert result[0].group == "high" and result[0].value == 12.5
