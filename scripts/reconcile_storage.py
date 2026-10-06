"""Preview or reconcile one bounded page of tenant-private upload orphans."""

import argparse
from uuid import UUID, uuid7

from operations.composition import compose
from operations.modules.identity.application.contracts import Principal, RequestContext
from operations.platform.config import Settings
from operations.platform.database import create_database_engine
from sqlalchemy.orm import Session


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--organization", required=True, type=UUID)
    parser.add_argument("--subject", required=True)
    parser.add_argument("--grace-hours", type=int, default=24)
    parser.add_argument("--cursor")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--reason")
    parser.add_argument("--resume", type=UUID, help="Retry one retained cleanup intent")
    args = parser.parse_args()
    settings = Settings()  # type: ignore[call-arg]
    if not settings.oidc_issuer:
        parser.error("Configured trusted issuer required")
    if not 24 <= args.grace_hours <= 720:
        parser.error("Grace must be between 24 and 720 hours")
    if args.resume and (not args.apply or args.cursor or args.reason):
        parser.error("Resume requires --apply and uses its original intent/reason")
    if args.apply and not args.resume and not args.reason:
        parser.error("Applying a new batch requires --reason")
    actor = RequestContext(Principal(settings.oidc_issuer, args.subject), uuid7(), uuid7())
    engine = create_database_engine(settings)
    try:
        if args.resume:
            intents = [args.resume]
        else:
            with Session(engine) as session, session.begin():
                service = compose(session, actor.principal, settings).file_reconciliation
                plan = service.preview(
                    actor, args.organization, args.grace_hours * 3600, args.cursor
                )
                intents = service.request(actor, plan, args.reason) if args.apply else []
            print(
                f"Scanned={plan.scanned}; candidates={len(plan.candidates)}; "
                f"next_cursor={plan.cursor}"
            )
        # Intents are durably committed before any external delete. Each result commits separately.
        for identifier in intents:
            print(f"Retained cleanup intent={identifier}")
        for identifier in intents:
            with Session(engine) as session, session.begin():
                result = compose(session, actor.principal, settings).file_reconciliation.apply(
                    actor,
                    args.organization,
                    identifier,
                )
            print(f"Cleanup intent={identifier}; outcome={result}")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
