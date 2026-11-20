$ErrorActionPreference = 'Stop'
Push-Location -LiteralPath $PSScriptRoot
try {
    foreach ($command in @('python', 'node', 'npm.cmd')) {
        if (-not (Get-Command $command -ErrorAction SilentlyContinue)) { throw "Required command not found: $command" }
    }
    python -m pip install --target .deps -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed.' }
    npm.cmd ci --no-audit --fund=false
    if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed.' }
    npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
    Write-Host 'Ready. Run Start-Local.cmd.'
} finally { Pop-Location }
