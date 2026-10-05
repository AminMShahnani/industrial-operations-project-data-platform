# Industrial Operations Platform

Industry-neutral modular monolith. Product and architecture source of truth:
`AGENTS.md` and numbered documents under `docs/`. Domain semantics are delivered
through Domain Packs. Phase gates and current evidence: `docs/progress/`.

## Local development

Prerequisites: Python 3.14, uv, Node 24/npm and a running Docker engine.
Commands run from repository root unless stated otherwise. PowerShell users can
use `npm.cmd` when script execution policy blocks `npm.ps1`.

```powershell
Copy-Item .env.example .env
uv sync --frozen
npm.cmd ci --prefix frontend
docker compose up -d --wait
uv run python scripts/init_storage.py
uv run alembic upgrade head
uv run uvicorn operations.main:app_factory --factory --host 127.0.0.1 --port 8000
```

In a second terminal run `npm.cmd run dev --prefix frontend`. Frontend:
http://localhost:5173. API schema: http://127.0.0.1:8000/docs.
`/api/v1/health/live` checks the process; `/api/v1/health/ready` checks PostgreSQL,
Redis and the private storage bucket, returning 503 on dependency failure.
The administration shell supports OIDC login, organization/workspace selection,
workspace creation and scoped invitations. Configure login and bootstrap the
operator using [the identity runbook](docs/operations/IDENTITY_RUNBOOK.md).

## Quality gates

```powershell
uv run ruff check .
uv run ruff format --check .
uv run mypy
docker compose exec -T postgres createdb -U operations operations_test
$env:IOP_TEST_DATABASE_URL = 'postgresql+psycopg://operations:operations_dev@127.0.0.1:55432/operations_test'
uv run pytest
uv run alembic check
uv run python scripts/export_openapi.py --check
npm.cmd run lint --prefix frontend
npm.cmd run typecheck --prefix frontend
npm.cmd run test --prefix frontend
npm.cmd run build --prefix frontend
```

Create the test database once. Integration tests require an isolated test database;
they refuse populated operational tables. For browser acceptance also create
`operations_browser_test`, set `IOP_BROWSER_DATABASE_URL`, start `oidc-dev` and
install Playwright Chromium as described in the identity runbook. Without the URLs, local
integration tests skip and do **not** satisfy the phase gate. CI treats a missing
test URL as failure. `.github/workflows/quality.yml` runs these gates on Linux.

Regenerate intentional schema changes with `uv run python scripts/export_openapi.py`
and run `npm.cmd run generate:api --prefix frontend`; review both diffs. Alembic
schema drift is checked against registered model metadata; new module models must
be explicitly registered in migration composition.

## Migration and shutdown

See `docs/operations/FOUNDATION_RUNBOOK.md`. `docker compose down` stops this
project's services while retaining volumes. Do not remove volumes containing data.
Development credentials in `.env.example` are local-only; secrets never belong
in Git. Production deployment, provider provisioning, backups and UAT remain gated work.
