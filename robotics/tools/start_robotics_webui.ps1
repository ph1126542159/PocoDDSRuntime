param(
    [string] $RuntimeExecutable = '',
    [string] $PythonExecutable = '',
    [int] $RuntimePort = 9080,
    [int] $SimulationPort = 9096,
    [int] $TimeoutSeconds = 30,
    [switch] $OpenBrowser
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$simulationServer = Join-Path $PSScriptRoot 'robotics_web_server.py'
$logDirectory = Join-Path $repoRoot 'build\robotics\logs'

function Test-HttpEndpoint
{
    param([string] $Uri)

    try
    {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $Uri -TimeoutSec 2
        return $response.StatusCode -eq 200
    }
    catch
    {
        return $false
    }
}

function Wait-HttpEndpoint
{
    param(
        [string] $Uri,
        [DateTime] $Deadline
    )

    do
    {
        if (Test-HttpEndpoint $Uri)
        {
            return $true
        }
        Start-Sleep -Milliseconds 250
    }
    while ([DateTime]::UtcNow -lt $Deadline)
    return $false
}

if (-not (Test-Path -LiteralPath $simulationServer -PathType Leaf))
{
    throw "Robot simulation server was not found: $simulationServer"
}

if ([string]::IsNullOrWhiteSpace($RuntimeExecutable))
{
    $runtimeCandidates = @(
        (Join-Path $repoRoot 'build\bin\pdr-runtime.exe'),
        (Join-Path $repoRoot 'build\install\bin\pdr-runtime.exe')
    )
    $RuntimeExecutable = $runtimeCandidates |
        Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } |
        Select-Object -First 1
}
if ([string]::IsNullOrWhiteSpace($RuntimeExecutable) -or
    -not (Test-Path -LiteralPath $RuntimeExecutable -PathType Leaf))
{
    throw 'pdr-runtime.exe was not found. Build the runtime or pass -RuntimeExecutable.'
}
$RuntimeExecutable = (Resolve-Path -LiteralPath $RuntimeExecutable).Path

if ([string]::IsNullOrWhiteSpace($PythonExecutable))
{
    $pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($null -eq $pythonCommand)
    {
        throw 'Python 3 was not found. Pass -PythonExecutable with an absolute path.'
    }
    $PythonExecutable = $pythonCommand.Source
}
if (-not (Test-Path -LiteralPath $PythonExecutable -PathType Leaf))
{
    throw "Python executable was not found: $PythonExecutable"
}
$PythonExecutable = (Resolve-Path -LiteralPath $PythonExecutable).Path

New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null

$runtimeHealth = "http://127.0.0.1:$RuntimePort/health/live"
$tracingPage = "http://127.0.0.1:$RuntimePort/tracing/"
$simulationHealth = "http://127.0.0.1:$SimulationPort/health/live"
$runtimeProcess = $null
$simulationProcess = $null

try
{
    if (-not (Test-HttpEndpoint $runtimeHealth))
    {
        $runtimeProcess = Start-Process -FilePath $RuntimeExecutable `
            -WorkingDirectory (Split-Path -Parent $RuntimeExecutable) `
            -WindowStyle Hidden `
            -PassThru
    }

    if (-not (Test-HttpEndpoint $simulationHealth))
    {
        $stamp = [DateTime]::UtcNow.ToString('yyyyMMdd-HHmmss')
        $simulationProcess = Start-Process -FilePath $PythonExecutable `
            -ArgumentList @('-u', $simulationServer, '--port', [string]$SimulationPort) `
            -WorkingDirectory $repoRoot `
            -RedirectStandardOutput (Join-Path $logDirectory "web-server-$stamp.stdout.log") `
            -RedirectStandardError (Join-Path $logDirectory "web-server-$stamp.stderr.log") `
            -WindowStyle Hidden `
            -PassThru
    }

    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    foreach ($endpoint in @($runtimeHealth, $tracingPage, $simulationHealth))
    {
        if (-not (Wait-HttpEndpoint -Uri $endpoint -Deadline $deadline))
        {
            throw "Endpoint did not become ready within $TimeoutSeconds seconds: $endpoint"
        }
    }

    if ($OpenBrowser)
    {
        Start-Process $tracingPage
    }

    [pscustomobject]@{
        Runtime = 'ready'
        RuntimePid = if ($null -ne $runtimeProcess) { $runtimeProcess.Id } else { 'already-running' }
        Simulation = 'ready'
        SimulationPid = if ($null -ne $simulationProcess) { $simulationProcess.Id } else { 'already-running' }
        WebUI = $tracingPage
    } | Format-List
}
catch
{
    foreach ($process in @($simulationProcess, $runtimeProcess))
    {
        if ($null -ne $process -and -not $process.HasExited)
        {
            Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        }
    }
    throw
}
