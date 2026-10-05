import json
import sys
from pathlib import Path

from operations.main import create_app
from operations.platform.config import Settings
from pydantic import SecretStr

settings = Settings(
    _env_file=None,  # type: ignore[call-arg]  # Pydantic Settings runtime constructor option.
    environment="test",
    database_url=SecretStr("postgresql+psycopg://unused:unused@localhost/unused"),
    redis_url=SecretStr("redis://localhost:6379/0"),
    s3_endpoint="http://localhost:9000",
    s3_access_key=SecretStr("unused"),
    s3_secret_key=SecretStr("unused"),
)
content = json.dumps(create_app(settings).openapi(), indent=2, sort_keys=True) + "\n"
destination = Path("contracts/openapi.json")
if "--check" in sys.argv:
    if not destination.exists() or destination.read_text(encoding="utf-8") != content:
        raise SystemExit("OpenAPI drift: run uv run python scripts/export_openapi.py")
else:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(content, encoding="utf-8")
