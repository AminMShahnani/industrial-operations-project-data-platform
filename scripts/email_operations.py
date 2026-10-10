"""Preview/queue/replay scoped email, or dispatch a bounded due batch."""

import argparse
from datetime import UTC, datetime
from uuid import UUID, uuid7

from dramatiq import Message
from dramatiq.brokers.redis import RedisBroker
from operations.email_worker import email_service
from operations.modules.identity.application.contracts import Principal, RequestContext
from operations.modules.notifications.application.email_contracts import EmailDispatch
from operations.modules.notifications.infrastructure.smtp import load_profile
from operations.platform.config import Settings
from operations.platform.database import create_database_engine
from sqlalchemy.orm import Session


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["queue", "replay", "dispatch"])
    parser.add_argument("--organization", type=UUID, required=True)
    parser.add_argument("--subject", required=True)
    parser.add_argument("--kind", choices=["invitation", "notice"])
    parser.add_argument("--source", type=UUID)
    parser.add_argument("--recipient", type=UUID)
    parser.add_argument("--delivery", type=UUID)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--reason")
    parser.add_argument("--review-sha256")
    args = parser.parse_args()
    if args.command == "queue" and (not args.kind or not args.source):
        parser.error("Queue requires --kind and --source")
    if args.command == "replay" and not args.delivery:
        parser.error("Replay requires --delivery")
    if args.apply and args.command != "dispatch" and not args.reason:
        parser.error("Apply requires --reason")
    if args.apply and args.command == "replay" and not args.review_sha256:
        parser.error("Replay apply requires reviewed --review-sha256")
    settings = Settings()  # type: ignore[call-arg]
    if not settings.oidc_issuer:
        parser.error("Configured trusted issuer required")
    actor = RequestContext(Principal(settings.oidc_issuer, args.subject), uuid7(), uuid7())
    engine = create_database_engine(settings)
    try:
        with Session(engine) as session, session.begin():
            service = email_service(session, settings)
            service.administrator(actor, args.organization)
            if args.command == "queue":
                result = service.queue(
                    actor,
                    args.organization,
                    args.kind,
                    args.source,
                    args.recipient,
                    args.apply,
                    args.reason,
                )
                output = result.model_dump_json()
            elif args.command == "replay":
                review = service.replay(
                    actor,
                    args.organization,
                    args.delivery,
                    args.apply,
                    args.review_sha256,
                    args.reason,
                )
                output = review.model_dump_json()
            else:
                identifiers = service.store.due(args.organization, datetime.now(UTC))
        if args.command == "dispatch":
            if args.apply:
                load_profile(
                    settings.email_profiles_directory,
                    args.organization,
                    settings.environment == "production",
                )
                broker = RedisBroker(
                    url=settings.redis_url.get_secret_value(),
                    socket_timeout=5,
                    socket_connect_timeout=5,
                )  # type: ignore[no-untyped-call]
                try:
                    for identifier in identifiers:
                        broker.enqueue(
                            Message(
                                queue_name="emails",
                                actor_name="consume_email",
                                args=(str(args.organization), str(identifier)),
                                kwargs={},
                                options={},
                            )
                        )
                finally:
                    broker.close()
                    broker.client.close()
            print(
                EmailDispatch(
                    organization_id=args.organization,
                    due=len(identifiers),
                    dispatched=len(identifiers) if args.apply else 0,
                ).model_dump_json()
            )
        else:
            print(output)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
