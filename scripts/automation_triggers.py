"""Preview/apply one scoped, bounded timer or task-deadline trigger batch."""

import argparse
from typing import Literal
from uuid import UUID, uuid7

from operations.composition import compose
from operations.contracts import Command
from operations.modules.automation.application.timers import TimerTick
from operations.modules.identity.application.contracts import Principal, RequestContext
from operations.modules.tasks.application.contracts import DeadlineTick
from operations.platform.config import Settings
from operations.platform.database import create_database_engine
from sqlalchemy.orm import Session


class PeriodicExecution(Command):
    kind: Literal["timer", "deadlines"]
    organization_id: UUID
    workspace_id: UUID
    request_id: UUID
    correlation_id: UUID
    apply: bool
    batch: TimerTick | DeadlineTick


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=["timer", "deadlines"])
    parser.add_argument("--organization", required=True, type=UUID)
    parser.add_argument("--workspace", required=True, type=UUID)
    parser.add_argument("--subject", required=True)
    parser.add_argument("--rule", type=UUID)
    parser.add_argument("--project", type=UUID)
    parser.add_argument("--cursor", type=UUID)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.kind == "timer" and (args.rule is None or args.cursor or args.project):
        parser.error("Timer needs --rule and uses that rule's exact scope; no --project/--cursor")
    if args.kind == "deadlines" and args.rule:
        parser.error("Deadline batches use --project/--cursor, not --rule")
    settings = Settings()  # type: ignore[call-arg]
    if not settings.oidc_issuer:
        parser.error("Configured trusted issuer required")
    actor = RequestContext(Principal(settings.oidc_issuer, args.subject), uuid7(), uuid7())
    engine = create_database_engine(settings)
    try:
        with Session(engine) as session, session.begin():
            services = compose(session, actor.principal, settings)
            batch: TimerTick | DeadlineTick
            if args.kind == "timer":
                batch = services.timers.tick(
                    actor, args.organization, args.workspace, args.rule, not args.apply
                )
            else:
                batch = services.tasks.generate_deadlines(
                    actor,
                    args.organization,
                    args.workspace,
                    args.project,
                    args.cursor,
                    not args.apply,
                )
        print(
            PeriodicExecution(
                kind=args.kind,
                organization_id=args.organization,
                workspace_id=args.workspace,
                request_id=actor.request_id,
                correlation_id=actor.correlation_id,
                apply=args.apply,
                batch=batch,
            ).model_dump_json()
        )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
