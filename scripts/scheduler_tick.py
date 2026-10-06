"""Explicit scoped periodic entry point; a deployment timer can invoke this safely."""

import argparse
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid7

from operations.composition import compose
from operations.modules.identity.application.contracts import Principal, RequestContext
from operations.platform.config import Settings
from operations.platform.database import create_database_engine
from sqlalchemy.orm import Session


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--organization", required=True, type=UUID)
    parser.add_argument("--workspace", required=True, type=UUID)
    parser.add_argument("--project", type=UUID)
    parser.add_argument("--subject", required=True)
    parser.add_argument("--horizon-days", type=int, choices=range(1, 61), default=30)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    settings = Settings()  # type: ignore[call-arg]
    if not settings.oidc_issuer:
        parser.error("Configured trusted issuer required")
    context = RequestContext(Principal(settings.oidc_issuer, args.subject), uuid7(), uuid7())
    engine = create_database_engine(settings)
    try:
        cursor: UUID | None = None
        now = datetime.now(UTC)
        count = 0
        while True:
            with Session(engine) as session, session.begin():
                services = compose(session, context.principal, settings)
                services.scheduling.require(
                    context, args.organization, args.workspace, args.project, True
                )
                schedules = services.scheduling.store.list_schedules(
                    args.organization, args.workspace, args.project, cursor
                )
                for schedule in schedules[:100]:
                    if schedule.active_number:
                        version = services.scheduling.store.version(
                            args.organization, schedule.id, schedule.active_number
                        )
                        if version and version.state == "active":
                            _, created = services.tasks.materialize(
                                context,
                                args.organization,
                                args.workspace,
                                schedule.id,
                                now,
                                now + timedelta(days=args.horizon_days),
                                not args.apply,
                            )
                            count += created
            if len(schedules) <= 100:
                break
            cursor = schedules[99].id
        if args.apply:
            cursor = None
            while True:
                with Session(engine) as session, session.begin():
                    services = compose(session, context.principal, settings)
                    _, cursor = services.tasks.generate_reminders(
                        context, args.organization, args.workspace, args.project, cursor
                    )
                if cursor is None:
                    break
        print(f"Scheduler tick complete: {count} new tasks; apply={args.apply}")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
