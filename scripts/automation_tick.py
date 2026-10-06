"""Scoped automation dispatcher; invoked periodically by a deployment timer."""

import argparse
from datetime import UTC, datetime
from uuid import UUID, uuid7

from dramatiq.brokers.redis import RedisBroker
from operations.composition import compose
from operations.modules.automation.infrastructure.queue import DramatiqPublisher
from operations.modules.iam.application.contracts import Scope, ScopeType
from operations.modules.identity.application.contracts import Principal, RequestContext
from operations.platform.config import Settings
from operations.platform.database import create_database_engine
from sqlalchemy.orm import Session


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--organization", required=True, type=UUID)
    parser.add_argument("--subject", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--consumer", choices=["automation", "notifications"], default="automation")
    args = parser.parse_args()
    settings = Settings()  # type: ignore[call-arg]
    if not settings.oidc_issuer:
        parser.error("Configured trusted issuer required")
    context = RequestContext(Principal(settings.oidc_issuer, args.subject), uuid7(), uuid7())
    engine = create_database_engine(settings)
    broker = RedisBroker(  # type: ignore[no-untyped-call]  # Vendor constructor lacks annotations.
        url=settings.redis_url.get_secret_value(), socket_timeout=5, socket_connect_timeout=5
    )
    try:
        with Session(engine) as session, session.begin():
            services = compose(session, context.principal, settings)
            services.authorization.require(
                context,
                "organization.manage",
                Scope(args.organization, ScopeType.ORGANIZATION, args.organization),
            )
            if args.apply:
                count = services.automation.dispatch(
                    args.organization, DramatiqPublisher(broker), args.consumer
                )
            else:
                count = len(
                    services.automation.store.due_deliveries(
                        args.organization, datetime.now(UTC), args.consumer
                    )
                )
        print(f"{args.consumer} dispatch: {count} deliveries; apply={args.apply}")
    finally:
        broker.close()
        broker.client.close()
        engine.dispose()


if __name__ == "__main__":
    main()
