import hashlib
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode
from uuid import NAMESPACE_URL, UUID, uuid5, uuid7

from operations.contracts import ServiceError
from operations.modules.audit.application.contracts import AuditDetails, AuditEvent
from operations.modules.iam.application.contracts import Role, Scope, ScopeType
from operations.modules.identity.application.contracts import Invitation, RequestContext
from operations.modules.notifications.application.email_contracts import (
    EmailAttempt,
    EmailContent,
    EmailDelivery,
    EmailDeliveryPage,
    EmailHistory,
    EmailKind,
    EmailResult,
    EmailReview,
    EmailState,
    EmailStore,
)
from operations.modules.notifications.application.service import NotificationService


class EmailService:
    def __init__(self, store: EmailStore, notices: NotificationService) -> None:
        self.store, self.notices = store, notices
        self.identity = notices.identity

    def invite(
        self,
        actor: RequestContext,
        email: str,
        role: Role,
        scope: Scope,
        identifier: UUID,
        email_delivery: bool = False,
        email_reason: str | None = None,
    ) -> Invitation:
        if email_delivery:
            self.administrator(actor, scope.organization_id)
            if not email_reason or not 1 <= len(email_reason.strip()) <= 500:
                raise ServiceError(422, "email_reason_required")
        invitation = self.identity.invite_verified_email(actor, email, role, scope, identifier)
        if email_delivery:
            self.queue(
                actor,
                scope.organization_id,
                "invitation",
                invitation.id,
                None,
                True,
                email_reason,
            )
        return invitation

    def administrator(self, actor: RequestContext, org: UUID) -> UUID:
        self.identity.organizations.active(org)
        return self.identity.authorization.require(
            actor, "organization.manage", Scope(org, ScopeType.ORGANIZATION, org)
        ).id

    def render(self, delivery: EmailDelivery, origin: str) -> EmailContent:
        org = delivery.organization_id
        source = self.identity.background_context(
            org, delivery.operator_id, delivery.request_id, delivery.correlation_id
        )
        self.administrator(source, org)
        if delivery.source_kind == "invitation":
            invitation = self.identity.email_invitation(org, delivery.source_id)
            link = (
                origin.rstrip("/")
                + "/?"
                + urlencode({"organization": org, "invitation": invitation.id})
            )
            return EmailContent(
                invitation.email,
                "Organization invitation",
                "You have an organization invitation. Sign in with your verified invited email "
                "and review it before accepting.\n" + link,
            )
        if delivery.recipient_id is None:
            raise ServiceError(409, "email_source_invalid")
        recipient = self.identity.active_context(org, delivery.recipient_id, source)
        notice = self.notices.store.get(org, delivery.recipient_id, delivery.source_id)
        if notice is None:
            raise ServiceError(404, "notification_not_found")
        self.notices.require(recipient, notice)
        user = self.identity.authorization.user(recipient, org)
        return EmailContent(
            user.email,
            "Operational notice",
            "You have an operational notice. Sign in to review your authorized work.\n"
            + origin.rstrip("/")
            + "/",
        )

    def audit(
        self,
        delivery: EmailDelivery,
        event: str,
        actor: UUID | None = None,
        reason: str | None = None,
        context: RequestContext | None = None,
    ) -> None:
        self.identity.audit.append(
            AuditEvent(
                id=uuid7(),
                type=event,
                occurred_at=datetime.now(UTC),
                organization_id=delivery.organization_id,
                actor_id=actor,
                correlation_id=context.correlation_id if context else delivery.correlation_id,
                request_id=context.request_id if context else delivery.request_id,
                aggregate_type="email_delivery",
                aggregate_id=delivery.id,
                payload=AuditDetails(
                    outcome=delivery.state, version=delivery.attempts, reason=reason
                ),
            )
        )

    def queue(
        self,
        actor: RequestContext,
        org: UUID,
        kind: EmailKind,
        source: UUID,
        recipient: UUID | None,
        apply: bool = False,
        reason: str | None = None,
    ) -> EmailDelivery:
        operator = self.administrator(actor, org)
        if (kind == "invitation") != (recipient is None):
            raise ServiceError(422, "email_source_invalid")
        identifier = uuid5(NAMESPACE_URL, f"operations:email:{org}:{kind}:{source}:{recipient}")
        existing = self.store.get(org, identifier)
        now = datetime.now(UTC)
        delivery = existing or EmailDelivery(
            id=identifier,
            organization_id=org,
            source_kind=kind,
            source_id=source,
            recipient_id=recipient,
            operator_id=operator,
            correlation_id=actor.correlation_id,
            request_id=actor.request_id,
            created_at=now,
            next_at=now,
        )
        self.render(delivery, "https://unconfigured.invalid")
        if apply and existing is None:
            if not reason or not 1 <= len(reason.strip()) <= 500:
                raise ServiceError(422, "email_reason_required")
            self.store.add(delivery)
            self.audit(delivery, "email.queued", operator, reason.strip(), actor)
        return delivery

    def claim(self, org: UUID, identifier: UUID) -> EmailDelivery | None:
        self.identity.organizations.lock(org)
        delivery = self.store.get(org, identifier)
        now = datetime.now(UTC)
        if (
            delivery is None
            or delivery.state not in {"pending", "retry", "sending"}
            or delivery.next_at > now
        ):
            return None
        if delivery.state == "sending":
            self.finish(delivery, EmailResult("uncertain", "smtp_claim_expired"))
            return None
        if delivery.attempts >= 20:
            raise ServiceError(409, "email_attempt_limit")
        claimed = delivery.model_copy(
            update={
                "state": "sending",
                "attempts": delivery.attempts + 1,
                "next_at": now + timedelta(seconds=90),
                "error_code": None,
            }
        )
        self.store.save(claimed)
        self.audit(claimed, "email.claimed")
        return claimed

    def finish(self, claimed: EmailDelivery, result: EmailResult) -> EmailDelivery:
        current = self.store.get(claimed.organization_id, claimed.id)
        if current is None or current.state != "sending" or current.attempts != claimed.attempts:
            raise ServiceError(409, "email_claim_conflict")
        state = "failed" if result.state == "retry" and current.attempts >= 8 else result.state
        finished = current.model_copy(
            update={
                "state": state,
                "error_code": result.code,
                "next_at": datetime.now(UTC) + timedelta(seconds=min(3600, 2**current.attempts)),
            }
        )
        self.store.save(finished)
        self.audit(finished, "email.attempted")
        self.store.attempt(
            EmailAttempt(
                id=uuid7(),
                organization_id=current.organization_id,
                delivery_id=current.id,
                number=current.attempts,
                outcome=finished.state,
                error_code=result.code,
                occurred_at=datetime.now(UTC),
            )
        )
        return finished

    def skip(self, claimed: EmailDelivery) -> EmailDelivery:
        current = self.store.get(claimed.organization_id, claimed.id)
        if current is None or current.state != "sending" or current.attempts != claimed.attempts:
            raise ServiceError(409, "email_claim_conflict")
        skipped = current.model_copy(
            update={"state": "skipped", "error_code": "email_authority_unavailable"}
        )
        self.store.save(skipped)
        self.audit(skipped, "email.attempted")
        self.store.attempt(
            EmailAttempt(
                id=uuid7(),
                organization_id=current.organization_id,
                delivery_id=current.id,
                number=current.attempts,
                outcome="skipped",
                error_code=skipped.error_code,
                occurred_at=datetime.now(UTC),
            )
        )
        return skipped

    def replay(
        self,
        actor: RequestContext,
        org: UUID,
        identifier: UUID,
        apply: bool = False,
        review_sha256: str | None = None,
        reason: str | None = None,
    ) -> EmailReview:
        operator = self.administrator(actor, org)
        delivery = self.store.get(org, identifier)
        if delivery is None:
            raise ServiceError(404, "email_not_found")
        if delivery.state not in {"retry", "failed", "uncertain"} or delivery.attempts >= 20:
            raise ServiceError(409, "email_not_replayable")
        self.render(delivery, "https://unconfigured.invalid")
        digest = hashlib.sha256(delivery.model_dump_json().encode()).hexdigest()
        if apply:
            if review_sha256 != digest:
                raise ServiceError(409, "email_review_stale")
            if not reason or not 1 <= len(reason.strip()) <= 500:
                raise ServiceError(422, "email_reason_required")
            updated = delivery.model_copy(
                update={"state": "retry", "next_at": datetime.now(UTC), "error_code": None}
            )
            self.store.save(updated)
            self.audit(updated, "email.replayed", operator, reason.strip(), actor)
        return EmailReview(delivery=delivery, review_sha256=digest, applied=apply)

    def page(
        self,
        actor: RequestContext,
        org: UUID,
        state: EmailState | None = None,
        cursor: UUID | None = None,
    ) -> EmailDeliveryPage:
        self.administrator(actor, org)
        rows = self.store.page(org, state, cursor)
        return EmailDeliveryPage(
            items=rows[:100], next_cursor=rows[99].id if len(rows) > 100 else None
        )

    def history(self, actor: RequestContext, org: UUID, identifier: UUID) -> EmailHistory:
        self.administrator(actor, org)
        row = self.store.get(org, identifier)
        if row is None:
            raise ServiceError(404, "email_not_found")
        return EmailHistory(delivery=row, attempts=self.store.attempts(org, identifier))

    def reviewed_replay(
        self,
        actor: RequestContext,
        org: UUID,
        identifier: UUID,
        *,
        dry_run: bool = True,
        review_sha256: str | None = None,
        reason: str | None = None,
        acknowledge_uncertain: bool = False,
    ) -> EmailReview:
        row = self.history(actor, org, identifier).delivery
        if not dry_run and row.state == "uncertain" and not acknowledge_uncertain:
            raise ServiceError(422, "email_uncertain_acknowledgement_required")
        result = self.replay(actor, org, identifier, not dry_run, review_sha256, reason)
        if result.applied:
            current = self.store.get(org, identifier)
            if current is None:
                raise ServiceError(409, "email_source_invalid")
            return result.model_copy(update={"delivery": current})
        return result
