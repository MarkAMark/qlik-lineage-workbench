$ErrorActionPreference = 'Stop'
Push-Location -LiteralPath $PSScriptRoot
try {
    foreach ($command in @('python', 'node', 'npm.cmd')) {
        if (-not (Get-Command $command -ErrorAction SilentlyContinue)) { throw "Required command not found: $command" }
    }
    node -e "const [major,minor]=process.versions.node.split('.').map(Number); if (!((major===20 && minor>=19)||(major===22 && minor>=12)||major>22)) { console.error('Node.js 20.19+ or 22.12+ required; Node 24 LTS recommended.'); process.exit(1); }"
    if ($LASTEXITCODE -ne 0) { throw 'Unsupported Node.js version. No dependencies have been installed.' }
    python -m pip install --target .deps -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed.' }
    npm.cmd ci --no-audit --fund=false
    if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed.' }
    npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
    Write-Host 'Ready. Run Start-Local.cmd.'
} finally { Pop-Location }
