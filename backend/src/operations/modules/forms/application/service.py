import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID, uuid7
from zoneinfo import ZoneInfo

from operations.contracts import ServiceError
from operations.modules.audit.application.contracts import AuditDetails, AuditEvent, AuditWriter
from operations.modules.forms.application.contracts import (
    Component,
    DefaultContext,
    Form,
    FormDefinition,
    FormStore,
    FormValues,
    FormVersion,
    LibraryArtifact,
    LookupItem,
    LookupPage,
    RuntimeResult,
    Section,
)
from operations.modules.forms.application.runtime import compile_definition, components, runtime
from operations.modules.forms.domain.expressions import ExpressionError
from operations.modules.iam.application.contracts import Scope, ScopeType
from operations.modules.iam.application.service import Authorization
from operations.modules.identity.application.contracts import Principal, RequestContext, User
from operations.modules.master_data.application.service import MasterDataService
from operations.modules.projects.application.service import ProjectService
from operations.modules.workspaces.application.group_service import GroupService
from operations.modules.workspaces.application.service import WorkspaceService


def definition_hash(definition: FormDefinition) -> str:
    content = json.dumps(definition.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(content.encode()).hexdigest()


class FormService:
    def __init__(
        self,
        store: FormStore,
        workspaces: WorkspaceService,
        projects: ProjectService,
        authorization: Authorization,
        master_data: MasterDataService,
        audit: AuditWriter,
        groups: GroupService,
    ) -> None:
        self.store, self.workspaces, self.projects = store, workspaces, projects
        self.authorization, self.master_data, self.audit = authorization, master_data, audit
        self.groups = groups
        self.default_context: DefaultContext | None = None

    def permissions(
        self, actor: RequestContext, org: UUID, workspace: UUID, project: UUID | None
    ) -> frozenset[str]:
        self.workspaces.active(org, workspace)
        if project:
            return self.projects.allowed(actor, org, workspace, project)
        return self.authorization.allowed(actor, Scope(org, ScopeType.WORKSPACE, workspace))

    def require(
        self,
        actor: RequestContext,
        org: UUID,
        workspace: UUID,
        project: UUID | None,
        permission: str,
        write: bool = False,
    ) -> None:
        if permission not in self.permissions(actor, org, workspace, project):
            raise ServiceError(403, "access_denied")
        if write and project:
            row = self.projects.require_access(actor, org, workspace, project, permission)
            if row.state in row.lifecycle.terminal:
                raise ServiceError(409, "terminal_project")

    def event(
        self,
        actor: RequestContext,
        form: Form,
        action: str,
        identifier: UUID,
        version: int | None = None,
        reason: str | None = None,
        *,
        form_number: int | None = None,
    ) -> None:
        user = self.authorization.user(actor, form.organization_id)
        self.audit.append(
            AuditEvent(
                id=uuid7(),
                type=action,
                occurred_at=datetime.now(UTC),
                organization_id=form.organization_id,
                actor_id=user.id,
                correlation_id=actor.correlation_id,
                request_id=actor.request_id,
                aggregate_type=(
                    "submission"
                    if action.startswith("submission.")
                    else "file"
                    if action.startswith("file.")
                    else "form_library_artifact"
                    if action.startswith("form.library.")
                    else "form_version"
                    if action.startswith(("form.version.", "form.draft."))
                    else "form"
                ),
                aggregate_id=identifier,
                payload=AuditDetails(
                    version=version,
                    reason=reason,
                    scope_type="project" if form.project_id else "workspace",
                    scope_id=form.project_id or form.workspace_id,
                    workspace_id=form.workspace_id,
                    project_id=form.project_id,
                    form_id=form.id if form_number is not None else None,
                    form_number=form_number,
                    submission_id=identifier if action.startswith("submission.") else None,
                    subject_user_id=user.id if action.startswith("submission.") else None,
                ),
            )
        )

    def form(
        self,
        actor: RequestContext,
        org: UUID,
        workspace: UUID,
        identifier: UUID,
        permission: str = "form.read",
        write: bool = False,
    ) -> Form:
        self.authorization.user(actor, org)
        form = self.store.get(org, workspace, identifier)
        if not form:
            raise ServiceError(404, "not_found")
        self.require(actor, org, workspace, form.project_id, permission, write)
        return form

    def create(
        self,
        actor: RequestContext,
        org: UUID,
        workspace: UUID,
        project: UUID | None,
        name: str,
        definition: FormDefinition,
    ) -> Form:
        self.require(actor, org, workspace, project, "form.manage", True)
        form = Form(
            id=uuid7(), organization_id=org, workspace_id=workspace, project_id=project, name=name
        )
        self.store.create(form)
        self.store.add_version(
            FormVersion(
                id=uuid7(),
                organization_id=org,
                workspace_id=workspace,
                form_id=form.id,
                number=1,
                definition=definition,
            )
        )
        self.event(actor, form, "form.created", form.id, 1)
        return form

    def list_forms(
        self,
        actor: RequestContext,
        org: UUID,
        workspace: UUID,
        project: UUID | None,
        cursor: UUID | None,
    ) -> tuple[list[Form], UUID | None]:
        self.require(actor, org, workspace, project, "form.read")
        rows = self.store.list_forms(org, workspace, project, cursor)
        return rows[:100], rows[99].id if len(rows) > 100 else None

    def version(
        self,
        actor: RequestContext,
        org: UUID,
        workspace: UUID,
        form_id: UUID,
        number: int,
        manage: bool = False,
    ) -> tuple[Form, FormVersion]:
        form = self.form(
            actor, org, workspace, form_id, "form.manage" if manage else "form.read", manage
        )
        version = self.store.version(org, form_id, number)
        if not version:
            raise ServiceError(404, "not_found")
        if version.state == "draft" and "form.manage" not in self.permissions(
            actor, org, workspace, form.project_id
        ):
            raise ServiceError(403, "draft_definition_private")
        return form, version

    def public_version(
        self, actor: RequestContext, org: UUID, workspace: UUID, form_id: UUID, number: int
    ) -> FormVersion:
        form, version = self.version(actor, org, workspace, form_id, number)
        if "form.manage" in self.permissions(actor, org, workspace, form.project_id):
            return version
        sections = [
            section.model_copy(
                update={
                    "components": [
                        field.model_copy(
                            update={
                                "children": [
                                    child
                                    for child in field.children
                                    if child.permissions.read != "manager"
                                ]
                            }
                        )
                        for field in section.components
                        if field.permissions.read != "manager"
                    ]
                }
            )
            for section in version.definition.sections
        ]
        return version.model_copy(
            update={"definition": version.definition.model_copy(update={"sections": sections})}
        )

    def save(
        self,
        actor: RequestContext,
        org: UUID,
        workspace: UUID,
        form_id: UUID,
        number: int,
        definition: FormDefinition,
        expected: int,
    ) -> FormVersion:
        form, version = self.version(actor, org, workspace, form_id, number, True)
        if version.state != "draft":
            raise ServiceError(409, "immutable_form_version")
        changed = version.model_copy(
            update={"definition": definition, "revision": version.revision + 1}
        )
        if version.revision != expected or not self.store.save_version(changed, expected):
            raise ServiceError(409, "version_conflict")
        self.event(actor, form, "form.draft.updated", version.id, changed.revision)
        return changed

    def clone(
        self,
        actor: RequestContext,
        org: UUID,
        workspace: UUID,
        form_id: UUID,
        source: int,
        number: int,
    ) -> FormVersion:
        form, previous = self.version(actor, org, workspace, form_id, source, True)
        if number <= source:
            raise ServiceError(422, "new_version_number_required")
        result = FormVersion(
            id=uuid7(),
            organization_id=org,
            workspace_id=workspace,
            form_id=form_id,
            number=number,
            definition=previous.definition,
        )
        self.store.add_version(result)
        self.event(actor, form, "form.version.created", result.id, number)
        return result

    def resolve(
        self, actor: RequestContext, form: Form, definition: FormDefinition
    ) -> FormDefinition:
        sections: list[Section] = []
        for section in definition.sections:
            fields = list(section.components)
            for pin in section.references:
                artifact = self.store.artifact(form.organization_id, form.workspace_id, pin)
                if not artifact or artifact.kind == "form":
                    raise ServiceError(422, "invalid_component_pin")
                fields.extend(components(artifact.definition))
            if len(fields) > 100:
                raise ServiceError(422, "too_many_components")
            sections.append(section.model_copy(update={"components": fields, "references": []}))
        result = FormDefinition(sections=sections)
        try:
            compile_definition(result)
        except ExpressionError as error:
            raise ServiceError(422, str(error)) from error
        for field in components(result):
            self.validate_sources(actor, form, field)
        return result

    def validate_sources(self, actor: RequestContext, form: Form, field: Component) -> None:
        if field.source and field.source.type_id:
            definition = self.master_data.definition(
                actor, form.organization_id, field.source.type_id
            )
            # A definition visible to its publisher must also belong to the target scope.
            from operations.modules.master_data.application.references import visible_at

            if not visible_at(definition, form.organization_id, form.workspace_id, form.project_id):
                raise ServiceError(422, "invalid_lookup_scope")
        for child in field.children:
            self.validate_sources(actor, form, child)

    def publish(
        self,
        actor: RequestContext,
        org: UUID,
        workspace: UUID,
        form_id: UUID,
        number: int,
        expected: int,
        dry_run: bool,
        expected_sha256: str | None,
    ) -> FormVersion:
        form, version = self.version(actor, org, workspace, form_id, number, True)
        self.require(actor, org, workspace, form.project_id, "form.publish", True)
        if version.state != "draft" or version.revision != expected:
            raise ServiceError(409, "version_conflict")
        definition = self.resolve(actor, form, version.definition)
        digest = definition_hash(definition)
        changed = version.model_copy(
            update={
                "definition": definition,
                "state": "published",
                "revision": expected + 1,
                "published_at": datetime.now(UTC),
                "content_sha256": digest,
            }
        )
        if not dry_run:
            if expected_sha256 != digest:
                raise ServiceError(409, "publication_preview_required")
            if not self.store.save_version(changed, expected):
                raise ServiceError(409, "version_conflict")
            self.event(actor, form, "form.version.published", version.id, number)
        return changed

    def lifecycle(
        self,
        actor: RequestContext,
        org: UUID,
        workspace: UUID,
        form_id: UUID,
        number: int,
        state: str,
        expected: int,
        dry_run: bool,
        reason: str,
    ) -> FormVersion:
        form, version = self.version(actor, org, workspace, form_id, number, True)
        self.require(actor, org, workspace, form.project_id, "form.publish", True)
        if (version.state, state) not in {
            ("published", "deprecated"),
            ("published", "retired"),
            ("deprecated", "retired"),
        }:
            raise ServiceError(422, "invalid_form_transition")
        result = version.model_copy(update={"state": state, "revision": expected + 1})
        if expected != version.revision:
            raise ServiceError(409, "version_conflict")
        if not dry_run:
            if not self.store.save_version(result, expected):
                raise ServiceError(409, "version_conflict")
            self.event(actor, form, "form.version." + state, version.id, number, reason)
        return result

    def evaluate(
        self,
        actor: RequestContext,
        form: Form,
        version: FormVersion,
        values: FormValues,
        complete: bool,
        defaults: bool = True,
        preserved: FormValues | None = None,
    ) -> RuntimeResult:
        user = self.authorization.user(actor, form.organization_id)
        manager = "form.manage" in self.permissions(
            actor, form.organization_id, form.workspace_id, form.project_id
        )
        definition = (
            self.resolve(actor, form, version.definition)
            if version.state == "draft"
            else version.definition
        )
        now = datetime.now(UTC)
        if defaults:
            fields = dict(values.fields)
            for field in components(definition):
                if (
                    field.source
                    and field.source.previous_approved_key
                    and fields.get(field.key) is None
                    and self.default_context
                ):
                    fields[field.key] = self.default_context.previous_approved(
                        form.organization_id,
                        form.workspace_id,
                        form.id,
                        user.id,
                        field.source.previous_approved_key,
                    )
                if field.source and field.source.record_id and fields.get(field.key) is None:
                    record = self.master_data.references.require(
                        form.organization_id,
                        form.workspace_id,
                        form.project_id,
                        field.source.record_id,
                        type_id=field.source.type_id,
                    )
                    fields[field.key] = str(record.id)
            values = FormValues(fields=fields)
        return runtime(
            definition,
            values,
            {
                "current_user": str(user.id),
                "current_date": now.astimezone(
                    ZoneInfo(
                        self.workspaces.organizations.active(form.organization_id).settings.timezone
                    )
                )
                .date()
                .isoformat(),
                "current_datetime": now.isoformat(),
                "project": str(form.project_id) if form.project_id else None,
                "shift": self.default_context.shift(
                    form.organization_id, form.workspace_id, form.project_id, user.id
                )
                if self.default_context
                else None,
            },
            True,
            manager,
            defaults,
            complete,
            preserved,
        )

    def library(self, actor: RequestContext, artifact: LibraryArtifact) -> LibraryArtifact:
        self.require(
            actor, artifact.organization_id, artifact.workspace_id, None, "form.manage", True
        )
        try:
            compile_definition(artifact.definition)
        except ExpressionError as error:
            raise ServiceError(422, str(error)) from error
        fields = components(artifact.definition)
        if artifact.kind == "field" and len(fields) != 1:
            raise ServiceError(422, "field_library_requires_one_component")
        self.store.add_artifact(artifact)
        dummy = Form(
            id=artifact.id,
            organization_id=artifact.organization_id,
            workspace_id=artifact.workspace_id,
            name=artifact.code,
        )
        self.event(actor, dummy, "form.library.published", artifact.id, artifact.version)
        return artifact

    def eligible_user(self, actor: RequestContext, form: Form, user: User) -> bool:
        target = RequestContext(
            Principal(user.issuer, user.subject), actor.request_id, actor.correlation_id
        )
        return user.active and "form.read" in self.permissions(
            target, form.organization_id, form.workspace_id, form.project_id
        )

    def lookup(
        self,
        actor: RequestContext,
        org: UUID,
        workspace: UUID,
        form_id: UUID,
        number: int,
        key: str,
        email: str | None,
        cursor: UUID | None,
    ) -> LookupPage:
        form, version = self.version(actor, org, workspace, form_id, number)
        fields = components(version.definition)
        field: Component | None = None
        for part in key.split("."):
            field = next((item for item in fields if item.key == part), None)
            if not field:
                raise ServiceError(404, "not_found")
            if field.permissions.read == "manager" and "form.manage" not in self.permissions(
                actor, org, workspace, form.project_id
            ):
                raise ServiceError(403, "access_denied")
            fields = field.children
        if not field:
            raise ServiceError(404, "not_found")
        if field.kind == "user":
            if not email:
                return LookupPage(items=[])
            users = self.authorization.identities.active_by_email(org, email)
            return LookupPage(
                items=[
                    LookupItem(id=user.id, label=user.email)
                    for user in users
                    if self.eligible_user(actor, form, user)
                ]
            )
        if field.kind == "department":
            groups = self.groups.list_groups(actor, org, workspace, cursor)
            return LookupPage(
                items=[
                    LookupItem(id=group.id, label=group.name)
                    for group in groups[:100]
                    if group.active and group.kind == "department"
                ],
                next_cursor=groups[99].id if len(groups) > 100 else None,
            )
        if field.kind == "project":
            projects = self.projects.list_projects(actor, org, workspace, cursor)
            return LookupPage(
                items=[LookupItem(id=project.id, label=project.name) for project in projects[:100]],
                next_cursor=projects[99].id if len(projects) > 100 else None,
            )
        if field.kind == "master_data" and field.source and field.source.type_id:
            records, after = self.master_data.references.lookup(
                org, workspace, form.project_id, field.source.type_id, cursor
            )
            return LookupPage(
                items=[LookupItem(id=record.id, label=record.name) for record in records],
                next_cursor=after,
            )
        raise ServiceError(422, "component_has_no_lookup")
