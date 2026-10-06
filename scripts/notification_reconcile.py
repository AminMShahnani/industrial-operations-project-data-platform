"""Preview/apply one reviewed page of retained task/workflow notification intents."""

import argparse
from uuid import UUID, uuid7

from operations.composition import compose
from operations.modules.identity.application.contracts import Principal, RequestContext
from operations.modules.notifications.application.reconciliation import NotificationReconciler
from operations.platform.config import Settings
from operations.platform.database import create_database_engine
from sqlalchemy.orm import Session


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--organization", required=True, type=UUID)
    parser.add_argument("--workspace", required=True, type=UUID)
    parser.add_argument("--subject", required=True)
    parser.add_argument("--kind", required=True, choices=["task_reminder", "workflow_notify"])
    parser.add_argument("--after", type=UUID)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--review-sha256")
    parser.add_argument("--reason")
    args = parser.parse_args()
    if args.apply and (not args.review_sha256 or not args.reason):
        parser.error("Apply requires --review-sha256 and --reason from a reviewed preview")
    settings = Settings()  # type: ignore[call-arg]
    if not settings.oidc_issuer:
        parser.error("Configured trusted issuer required")
    actor = RequestContext(Principal(settings.oidc_issuer, args.subject), uuid7(), uuid7())
    engine = create_database_engine(settings)
    try:
        with Session(engine) as session, session.begin():
            services = compose(session, actor.principal, settings)
            result = NotificationReconciler(
                services.automation, services.tasks, services.workflow_runtime
            ).reconcile(
                actor,
                args.organization,
                args.workspace,
                args.kind,
                args.after,
                dry_run=not args.apply,
                review_sha256=args.review_sha256,
                reason=args.reason,
            )
        print(result.model_dump_json())
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
