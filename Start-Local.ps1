param(
    [string]$MetadataRoot = (Join-Path $PSScriptRoot 'metadata\apps'),
    [int]$Port = 8775,
    [switch]$NoBrowser
)
$ErrorActionPreference = 'Stop'
Push-Location -LiteralPath $PSScriptRoot
try {
    if (-not (Get-Command python -ErrorAction SilentlyContinue)) { throw 'Python 3.10+ is required.' }
    python -c "import backend, importlib.util; raise SystemExit(0 if importlib.util.find_spec('sqlglot') else 1)"
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'dist\index.html'))) {
        Write-Host 'Preparing local dependencies and frontend...'
        & (Join-Path $PSScriptRoot 'Setup.ps1')
    }
    if (-not (Test-Path -LiteralPath $MetadataRoot -PathType Container)) { throw "Metadata directory does not exist: $MetadataRoot" }
    $taskUrl = "http://127.0.0.1:$Port"
    $taskRunningCatalog = $null
    try {
        $taskHealth = Invoke-RestMethod -Uri "$taskUrl/api/health" -TimeoutSec 2
        if ($taskHealth.service -eq 'qlik-lineage-studio') {
            $taskRunningCatalog = Invoke-RestMethod -Uri "$taskUrl/api/catalog" -TimeoutSec 3
        }
    } catch { }
    if ($taskRunningCatalog) {
        $taskRequestedRoot = (Resolve-Path -LiteralPath $MetadataRoot).ProviderPath.TrimEnd([char[]]'\/')
        $taskRunningRoot = [IO.Path]::GetFullPath($taskRunningCatalog.root).TrimEnd([char[]]'\/')
        if (-not $taskRequestedRoot.Equals($taskRunningRoot, [StringComparison]::OrdinalIgnoreCase)) {
            throw "The workbench on port $Port uses a different metadata directory. Choose another -Port or change the directory in the workbench."
        }
        Write-Host "Trace is already running: $taskUrl"
        if (-not $NoBrowser) { python -c "import sys, webbrowser; webbrowser.open(sys.argv[1])" $taskUrl }
        return
    }
    $serverArguments = @('-m', 'backend.server', '--metadata-root', $MetadataRoot, '--port', $Port)
    if (-not $NoBrowser) { $serverArguments += '--open' }
    python @serverArguments
    if ($LASTEXITCODE -ne 0) { throw 'The local workbench stopped with an error.' }
} finally { Pop-Location }
