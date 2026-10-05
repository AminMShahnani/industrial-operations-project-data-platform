import os

import pytest
from alembic import command
from alembic.config import Config
from botocore.exceptions import ClientError
from fastapi.testclient import TestClient
from operations.main import create_app
from operations.platform.config import Settings
from operations.platform.database import create_database_engine
from operations.platform.health import InfrastructureProbe
from pydantic import SecretStr
from sqlalchemy import inspect, text

pytestmark = pytest.mark.integration


@pytest.fixture
def infrastructure_settings() -> Settings:
    url = os.environ.get("IOP_TEST_DATABASE_URL")
    if not url:
        if os.environ.get("CI"):
            pytest.fail("CI must provide an isolated PostgreSQL test database")
        pytest.skip("Set IOP_TEST_DATABASE_URL to an isolated PostgreSQL database")
    return Settings(database_url=SecretStr(url))  # type: ignore[call-arg]


def test_migration_roundtrip(
    infrastructure_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("IOP_DATABASE_URL", infrastructure_settings.database_url.get_secret_value())
    engine = create_database_engine(infrastructure_settings)
    try:
        # Refuse destructive test operations against any database with business tables.
        assert set(inspect(engine).get_table_names()) <= {"alembic_version"}, (
            "Migration roundtrip requires an isolated empty test database"
        )
        config = Config("alembic.ini")
        command.upgrade(config, "head")
        command.check(config)
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                "0001_foundation"
            )
        command.downgrade(config, "base")
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT count(*) FROM alembic_version")) == 0
        command.upgrade(config, "head")
        command.check(config)
    finally:
        engine.dispose()


def test_real_dependencies_and_private_bucket(infrastructure_settings: Settings) -> None:
    engine = create_database_engine(infrastructure_settings)
    probe = InfrastructureProbe(engine, infrastructure_settings)
    try:
        status = probe.check()
        assert status.database == "up"
        assert status.redis == "up"
        assert status.object_storage == "up"
        # A private bucket must not expose a wildcard anonymous allow policy.
        try:
            policy = probe.storage.get_bucket_policy(Bucket=probe.bucket)
        except ClientError as error:
            assert error.response["Error"]["Code"] == "NoSuchBucketPolicy"
        else:
            pytest.fail(f"Unexpected policy on isolated test bucket: {policy['Policy']}")
    finally:
        probe.close()
        engine.dispose()


def test_real_api_lifespan_and_readiness(infrastructure_settings: Settings) -> None:
    with TestClient(create_app(infrastructure_settings)) as client:
        response = client.get("/api/v1/health/ready")
        assert response.status_code == 200
        assert response.json()["dependencies"] == {
            "database": "up",
            "redis": "up",
            "object_storage": "up",
        }
    missing_bucket = infrastructure_settings.model_copy(
        update={"s3_bucket": "foundation-test-missing-bucket"}
    )
    with TestClient(create_app(missing_bucket)) as client:
        assert client.get("/api/v1/health/live").status_code == 200
        response = client.get("/api/v1/health/ready")
        assert response.status_code == 503
        assert response.json()["dependencies"]["object_storage"] == "down"
