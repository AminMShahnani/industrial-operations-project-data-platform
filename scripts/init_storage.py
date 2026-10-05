"""Create the private development bucket; no anonymous access policy is installed."""

from botocore.exceptions import ClientError
from operations.platform.config import Settings
from operations.platform.database import create_database_engine
from operations.platform.health import InfrastructureProbe

settings = Settings()  # type: ignore[call-arg]
if settings.environment != "development":
    raise SystemExit("Development storage initializer requires IOP_ENVIRONMENT=development")
engine = create_database_engine(settings)
probe = InfrastructureProbe(engine, settings)
try:
    try:
        probe.storage.head_bucket(Bucket=settings.s3_bucket)
    except ClientError as error:
        if error.response["Error"]["Code"] not in {"404", "NoSuchBucket", "NotFound"}:
            raise
        probe.storage.create_bucket(Bucket=settings.s3_bucket)
finally:
    probe.close()
    engine.dispose()
