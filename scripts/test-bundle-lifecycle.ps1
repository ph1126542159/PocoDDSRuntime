param(
    [string]$BuildDirectory = (Join-Path $PSScriptRoot '..\build')
)

$ErrorActionPreference = 'Stop'
$buildRoot = (Resolve-Path -LiteralPath $BuildDirectory).Path
$sourceProcess = Join-Path $buildRoot 'bin'
$sourceBundles = Join-Path $sourceProcess 'bundles'
$testRoot = Join-Path $buildRoot (
    'tests\pdr-runtime-lifecycle-' + [DateTime]::UtcNow.ToString('yyyyMMddHHmmss'))
$testBundles = Join-Path $testRoot 'bundles'
$testLogs = Join-Path $testRoot 'logs'

New-Item -ItemType Directory -Path $testRoot, $testBundles, $testLogs | Out-Null
Copy-Item -LiteralPath (Join-Path $sourceProcess 'pdr-runtime.exe') -Destination $testRoot
Copy-Item -LiteralPath (Join-Path $sourceProcess 'PDRBundleManagement.dll') -Destination $testRoot
Copy-Item -LiteralPath (Join-Path $sourceProcess 'PDRProcessManagement.dll') -Destination $testRoot
Copy-Item -LiteralPath (Join-Path $sourceProcess 'pdr-runtime.properties') -Destination $testRoot
Copy-Item -LiteralPath (Join-Path $PSScriptRoot '..\server\tests\subprocess-order-smoke.properties') `
    -Destination (Join-Path $testRoot 'pdr-subprocesses.properties')
Copy-Item -LiteralPath (Join-Path $sourceProcess 'processes') `
    -Destination $testRoot -Recurse
Copy-Item -LiteralPath (Join-Path $sourceBundles 'osp.core_1.7.0.bndl') `
    -Destination $testBundles

$stdout = Join-Path $testRoot 'stdout.log'
$stderr = Join-Path $testRoot 'stderr.log'
$runtimeLog = Join-Path $testLogs 'pdr-runtime.log'
$config = Join-Path $PSScriptRoot '..\server\tests\bundle-manager-smoke.properties'
$executable = Join-Path $testRoot 'pdr-runtime.exe'
$process = $null

function Wait-LogCount
{
    param(
        [string]$Pattern,
        [int]$Count,
        [int]$TimeoutSeconds
    )

    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do
    {
        $content = if (Test-Path -LiteralPath $runtimeLog)
        {
            Get-Content -LiteralPath $runtimeLog -Raw -ErrorAction SilentlyContinue
        }
        else
        {
            ''
        }
        if ($null -eq $content)
        {
            $content = ''
        }
        if ([regex]::Matches([string]$content, [regex]::Escape($Pattern)).Count -ge $Count)
        {
            return $true
        }
        Start-Sleep -Milliseconds 200
    }
    while ([DateTime]::UtcNow -lt $deadline)
    return $false
}

try
{
    $process = Start-Process -FilePath $executable `
        -ArgumentList @('/config-file=' + $config) `
        -WorkingDirectory $testRoot `
        -RedirectStandardOutput $stdout `
        -RedirectStandardError $stderr `
        -WindowStyle Hidden `
        -PassThru

    if (-not (Wait-LogCount 'PocoDDSRuntime server ready' 1 20))
    {
        throw 'Runtime did not become ready.'
    }
    if (-not (Wait-LogCount "Subprocess 'second' started" 1 10))
    {
        throw 'Configured subprocesses did not start.'
    }
    $startupContent = Get-Content -LiteralPath $runtimeLog -Raw
    $firstPosition = $startupContent.IndexOf("Starting subprocess 1/2 'first'")
    $secondPosition = $startupContent.IndexOf("Starting subprocess 2/2 'second'")
    if ($firstPosition -lt 0 -or $secondPosition -le $firstPosition)
    {
        throw 'Subprocess startup order was not preserved.'
    }

    $probeSource = Join-Path $sourceBundles 'pdr.webui.home_1.0.0.bndl'
    $probeTarget = Join-Path $testBundles 'pdr.webui.home_1.0.0.bndl'

    Copy-Item -LiteralPath $probeSource -Destination $probeTarget
    if (-not (Wait-LogCount 'Bundle repository reload completed.' 1 15))
    {
        throw 'Add reload did not complete.'
    }

    $replacement = Join-Path $testBundles 'pdr.webui.home_1.0.0.bndl.new'
    Copy-Item -LiteralPath $probeSource -Destination $replacement
    Move-Item -LiteralPath $replacement -Destination $probeTarget -Force
    if (-not (Wait-LogCount 'Bundle repository reload completed.' 2 15))
    {
        throw 'Replace reload did not complete.'
    }

    Remove-Item -LiteralPath $probeTarget
    if (-not (Wait-LogCount 'Bundle repository reload completed.' 3 15))
    {
        throw 'Delete reload did not complete.'
    }

    $content = Get-Content -LiteralPath $runtimeLog -Raw
    $reloads =
        [regex]::Matches($content, [regex]::Escape('Bundle repository reload completed.')).Count
    $failures =
        [regex]::Matches($content, [regex]::Escape('Bundle repository reload failed')).Count

    Write-Output "LIFECYCLE_TEST_DIR=$testRoot"
    Write-Output "LIFECYCLE_RELOADS=$reloads"
    Write-Output "LIFECYCLE_FAILURES=$failures"
    Write-Output 'SUBPROCESS_START_ORDER=first,second'
    if ($reloads -ne 3 -or $failures -ne 0)
    {
        exit 1
    }
}
finally
{
    if ($process -and -not $process.HasExited)
    {
        Stop-Process -Id $process.Id -Force
    }
}
