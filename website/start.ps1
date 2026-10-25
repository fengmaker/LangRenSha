$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $repoRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw '请先按 website/README.md 安装 Python 依赖。'
}
Set-Location -LiteralPath $repoRoot
& $pythonPath (Join-Path $PSScriptRoot 'run.py') @args
exit $LASTEXITCODE
