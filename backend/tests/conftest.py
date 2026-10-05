import pytest
from operations.platform.config import Settings
from pydantic import SecretStr


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]  # Pydantic Settings runtime constructor option.
        environment="test",
        database_url=SecretStr("postgresql+psycopg://test:test@localhost:1/test"),
        redis_url=SecretStr("redis://localhost:1/0"),
        s3_endpoint="http://localhost:1",
        s3_access_key=SecretStr("not-a-real-key"),
        s3_secret_key=SecretStr("not-a-real-secret"),
        cors_origins=["http://localhost:5173"],
    )
