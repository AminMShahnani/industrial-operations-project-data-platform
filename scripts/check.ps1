# Fail-fast backend gates. Invoke from repository root with a configured test DB.
$ErrorActionPreference = 'Stop'
if (-not $env:IOP_TEST_DATABASE_URL) {
    throw 'Set IOP_TEST_DATABASE_URL to an isolated test database; integration skips are not a gate pass.'
}
if (-not $env:IOP_BROWSER_DATABASE_URL) {
    throw 'Set IOP_BROWSER_DATABASE_URL and start the oidc-dev profile; browser skips are not a gate pass.'
}
$qualityCommands = @(
    @('sync', '--frozen'),
    @('run', 'ruff', 'check', '.'),
    @('run', 'ruff', 'format', '--check', '.'),
    @('run', 'mypy'),
    @('run', 'mypy', '--platform', 'linux'),
    @('run', 'pytest', '-m', 'not e2e'),
    @('run', 'python', 'scripts/export_openapi.py', '--check')
)
foreach ($qualityCommand in $qualityCommands) {
    & uv @qualityCommand
    if ($LASTEXITCODE -ne 0) { throw "Quality gate failed: uv $qualityCommand" }
}
$previousDatabaseUrl = $env:IOP_DATABASE_URL
$env:IOP_DATABASE_URL = $env:IOP_TEST_DATABASE_URL
try {
    & uv run alembic upgrade head
    if ($LASTEXITCODE -ne 0) { throw 'Quality gate failed: uv run alembic upgrade head' }
    & uv run alembic check
    if ($LASTEXITCODE -ne 0) { throw 'Quality gate failed: uv run alembic check' }
}
finally {
    $env:IOP_DATABASE_URL = $previousDatabaseUrl
}
& uv run pytest -m e2e
if ($LASTEXITCODE -ne 0) { throw 'Quality gate failed: uv run pytest -m e2e (start the oidc-dev profile first)' }
foreach ($frontendGate in @('lint', 'typecheck', 'test', 'build')) {
    & npm.cmd run $frontendGate --prefix frontend
    if ($LASTEXITCODE -ne 0) { throw "Frontend gate failed: $frontendGate" }
}
