param(
    [string]$MetadataRoot = '',
    [ValidateRange(1024, 65535)][int]$Port = 8775,
    [switch]$NoBrowser,
    [switch]$AcceptRuntimeTerms
)
$ErrorActionPreference = 'Stop'
Push-Location -LiteralPath $PSScriptRoot
try {
    $runtimeExe = Join-Path $PSScriptRoot 'runtime\python.exe'
    $entryScript = Join-Path $PSScriptRoot 'run_trace.py'
    foreach ($requiredPath in @($runtimeExe, $entryScript, (Join-Path $PSScriptRoot 'dist\index.html'))) {
        if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
            throw 'Package files are missing. Extract the entire ZIP before starting Trace.'
        }
    }
    $termsPath = Join-Path $PSScriptRoot 'docs\WINDOWS-RUNTIME-TERMS.md'
    if (-not (Test-Path -LiteralPath $termsPath -PathType Leaf)) { throw 'Windows runtime terms are missing.' }
    if (-not $AcceptRuntimeTerms) {
        Write-Host (Get-Content -LiteralPath $termsPath -Raw -Encoding UTF8)
        $answer = Read-Host 'Accept these runtime redistribution/use terms? Type YES to start; anything else exits'
        if ($answer -cne 'YES') { throw 'Runtime terms were not accepted; Trace has not started.' }
    }
    if (-not $MetadataRoot) { $MetadataRoot = Join-Path $PSScriptRoot 'metadata\apps' }
    if (-not [IO.Path]::IsPathRooted($MetadataRoot)) { $MetadataRoot = Join-Path $PSScriptRoot $MetadataRoot }
    if (-not (Test-Path -LiteralPath $MetadataRoot -PathType Container)) { throw "Metadata directory not found: $MetadataRoot" }
    $MetadataRoot = (Resolve-Path -LiteralPath $MetadataRoot).ProviderPath.TrimEnd([char[]]'\/')
    $selectedPort = $null
    $lastPort = [Math]::Min($Port + 30, 65535)
    foreach ($candidatePort in $Port..$lastPort) {
        $probe = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, $candidatePort)
        $available = $false
        try { $probe.Start(); $available = $true } catch { } finally { $probe.Stop() }
        if ($available) { $selectedPort = $candidatePort; break }
        try {
            $candidateUrl = "http://127.0.0.1:$candidatePort"
            $health = Invoke-RestMethod -Uri "$candidateUrl/api/health" -TimeoutSec 2
            if ($health.service -ne 'qlik-lineage-studio') { continue }
            $catalog = Invoke-RestMethod -Uri "$candidateUrl/api/catalog" -TimeoutSec 5
            $runningRoot = [IO.Path]::GetFullPath($catalog.root).TrimEnd([char[]]'\/')
            if ($MetadataRoot.Equals($runningRoot, [StringComparison]::OrdinalIgnoreCase)) {
                Write-Host "Trace is already running: $candidateUrl"
                if (-not $NoBrowser) { & $runtimeExe -I -B -c 'import sys, webbrowser; webbrowser.open(sys.argv[1])' $candidateUrl }
                return
            }
        } catch { }
    }
    if (-not $selectedPort) { throw 'No local port is available. Run Start-Trace.cmd -Port 8875.' }
    Write-Host 'Trace - Qlik lineage and migration workbench'
    Write-Host "Metadata: $MetadataRoot"
    Write-Host "Local URL: http://127.0.0.1:$selectedPort"
    Write-Host 'Open the workbench to select a local metadata export directory.'
    Write-Host 'Keep this window open. Press Ctrl+C to stop the workbench.'
    $serverArguments = @('-I', '-B', $entryScript, '--metadata-root', $MetadataRoot, '--port', $selectedPort)
    if (-not $NoBrowser) { $serverArguments += '--open' }
    & $runtimeExe @serverArguments
    if ($LASTEXITCODE -ne 0) { throw 'Trace stopped with an error. Check that the entire ZIP was extracted.' }
} finally { Pop-Location }
