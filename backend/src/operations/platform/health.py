from typing import Literal, Protocol

import boto3
from botocore.config import Config
from pydantic import BaseModel
from redis import Redis
from sqlalchemy import Engine, text

from operations.platform.config import Settings


class DependencyStatus(BaseModel):
    database: Literal["up", "down"]
    redis: Literal["up", "down"]
    object_storage: Literal["up", "down"]


class HealthResponse(BaseModel):
    status: Literal["ok", "ready", "unavailable"]
    dependencies: DependencyStatus | None = None


class ReadinessProbe(Protocol):
    def check(self) -> DependencyStatus: ...


class InfrastructureProbe:
    def __init__(self, engine: Engine, settings: Settings) -> None:
        self.engine = engine
        self.redis: Redis = Redis.from_url(
            settings.redis_url.get_secret_value(), socket_timeout=2, socket_connect_timeout=2
        )
        self.storage = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint,
            aws_access_key_id=settings.s3_access_key.get_secret_value(),
            aws_secret_access_key=settings.s3_secret_key.get_secret_value(),
            region_name="us-east-1",
            config=Config(connect_timeout=2, read_timeout=2, retries={"max_attempts": 0}),
        )
        self.bucket = settings.s3_bucket

    def check(self) -> DependencyStatus:
        result = DependencyStatus(database="down", redis="down", object_storage="down")
        try:
            with self.engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            result.database = "up"
        except Exception:
            pass  # Public diagnostics must never expose connection strings or credentials.
        try:
            if self.redis.ping():
                result.redis = "up"
        except Exception:
            pass
        try:
            self.storage.head_bucket(Bucket=self.bucket)
            result.object_storage = "up"
        except Exception:
            pass
        return result

    def close(self) -> None:
        self.redis.close()
        self.storage.close()
