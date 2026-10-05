"""Explicit trusted-issuer operator bootstrap; no HTTP bootstrap endpoint exists."""

import argparse

from operations.composition import compose
from operations.modules.identity.application.contracts import Principal
from operations.platform.config import Settings
from operations.platform.database import create_database_engine
from sqlalchemy.orm import Session

parser = argparse.ArgumentParser()
parser.add_argument("--subject", required=True)
parser.add_argument("--reason", required=True)
args = parser.parse_args()
settings = Settings()  # type: ignore[call-arg]
if not settings.oidc_issuer or not args.subject.strip() or not args.reason.strip():
    raise SystemExit("Configured trusted issuer, known nonempty subject and reason required")
principal = Principal(settings.oidc_issuer, args.subject)
engine = create_database_engine(settings)
try:
    with Session(engine) as session, session.begin():
        compose(session, principal).identity.bootstrap(principal, args.reason)
finally:
    engine.dispose()
print("Platform administrator provisioned with an immutable audit event.")
