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
    @('run', 'pytest'),
    @('run', 'alembic', 'check'),
    @('run', 'python', 'scripts/export_openapi.py', '--check')
)
foreach ($qualityCommand in $qualityCommands) {
    & uv @qualityCommand
    if ($LASTEXITCODE -ne 0) { throw "Quality gate failed: uv $qualityCommand" }
}
foreach ($frontendGate in @('lint', 'typecheck', 'test', 'build')) {
    & npm.cmd run $frontendGate --prefix frontend
    if ($LASTEXITCODE -ne 0) { throw "Frontend gate failed: $frontendGate" }
}
