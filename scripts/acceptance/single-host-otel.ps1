param(
    [Parameter(Mandatory = $true)]
    [string]$Collector,

    [string]$BuildDirectory = '.\build-qt',
    [int]$Domain = 191
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$build = (Resolve-Path $BuildDirectory).Path
$collectorPath = (Resolve-Path $Collector).Path
$hostPath = Join-Path $build 'demos\QtOpenGLMultiProcess\pdr-qt-opengl-host.exe'
$configuration = Join-Path $root 'config\otel-collector-acceptance.yaml'
$evidence = Join-Path $build 'otel-single-host-evidence.json'
$marker = Join-Path $build 'qt-otel-single-host.txt'
$stdout = Join-Path $build 'otel-single-host-collector.out.log'
$stderr = Join-Path $build 'otel-single-host-collector.err.log'

$env:PDR_OTEL_EVIDENCE = $evidence
$collectorProcess = Start-Process -FilePath $collectorPath `
    -ArgumentList '--config', $configuration `
    -WorkingDirectory $root `
    -WindowStyle Hidden `
    -RedirectStandardOutput $stdout `
    -RedirectStandardError $stderr `
    -PassThru

try {
    $ready = $false
    for ($attempt = 0; $attempt -lt 50; ++$attempt) {
        $connection = Test-NetConnection 127.0.0.1 -Port 4318 -WarningAction SilentlyContinue
        if ($connection.TcpTestSucceeded) {
            $ready = $true
            break
        }
        Start-Sleep -Milliseconds 100
    }
    if (-not $ready) {
        throw 'OpenTelemetry Collector did not open 127.0.0.1:4318.'
    }

    $env:PDR_OTLP_ENDPOINT = 'http://127.0.0.1:4318'
    $env:QT_QPA_PLATFORM = 'windows'
    & $hostPath --acceptance $marker $Domain
    if ($LASTEXITCODE -ne 0) {
        throw "Qt multi-process acceptance failed with exit code $LASTEXITCODE."
    }
    Start-Sleep -Milliseconds 500
}
finally {
    if (-not $collectorProcess.HasExited) {
        Stop-Process -Id $collectorProcess.Id
        $collectorProcess.WaitForExit(5000) | Out-Null
    }
}

$traceText = Get-Content $evidence -Raw
$requiredEvidence = @(
    'qt.opengl.host',
    'qt.render.surface',
    'request-render',
    'render-command',
    'render state queued on Qt GUI thread'
)
foreach ($expected in $requiredEvidence) {
    if (-not $traceText.Contains($expected)) {
        throw "Collector evidence is missing '$expected'."
    }
}

$markerText = (Get-Content $marker -Raw).Trim()
if (-not $markerText.Contains('QT_DDS_TRACE_CRASH_RESTART_PASS')) {
    throw 'Qt acceptance marker is invalid.'
}

Write-Output "OTEL_OFFICIAL_COLLECTOR_SINGLE_HOST_PASS bytes=$($traceText.Length)"
Write-Output $markerText
