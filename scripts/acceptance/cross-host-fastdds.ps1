param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('subscriber', 'publisher', 'control-agent', 'control-client')]
    [string]$Role,

    [Parameter(Mandatory = $true)]
    [string]$Probe,

    [int]$Domain = 166,
    [string]$EvidenceDirectory = '.\cross-host-evidence'
)

$ErrorActionPreference = 'Stop'
$probePath = (Resolve-Path -LiteralPath $Probe).Path
$evidencePath = [System.IO.Path]::GetFullPath($EvidenceDirectory)
[System.IO.Directory]::CreateDirectory($evidencePath) | Out-Null

$hostName = [System.Net.Dns]::GetHostName()
$safeHostName = $hostName -replace '[^A-Za-z0-9_.-]', '_'
$prefix = Join-Path $evidencePath "$Role-$safeHostName"
$marker = "$prefix.marker.txt"
$log = "$prefix.log.txt"
$report = "$prefix.json"
Remove-Item -LiteralPath $marker -ErrorAction SilentlyContinue

$probeRole = switch ($Role) {
    'subscriber' { 'subscribe' }
    'publisher' { 'publish' }
    default { $Role }
}
$arguments = @($probeRole, $Domain.ToString(), 'network')
if ($Role -eq 'subscriber' -or $Role -eq 'control-client') {
    $arguments += $marker
}

$started = [DateTimeOffset]::UtcNow
& $probePath @arguments 2>&1 | Tee-Object -FilePath $log
$probeExitCode = $LASTEXITCODE
$finished = [DateTimeOffset]::UtcNow

$addresses = [System.Net.Dns]::GetHostAddresses($hostName) |
    Where-Object { $_.AddressFamily -eq [System.Net.Sockets.AddressFamily]::InterNetwork } |
    ForEach-Object { $_.IPAddressToString }
$markerText = if (Test-Path -LiteralPath $marker) {
    (Get-Content -LiteralPath $marker -Raw).Trim()
} else {
    ''
}
$evidence = [ordered]@{
    schema = 'PocoDDS.CrossHostEvidence.v1'
    role = $Role
    host = $hostName
    ipv4 = @($addresses)
    domain = $Domain
    transport = 'network-only'
    probe = $probePath
    probe_sha256 = (Get-FileHash -LiteralPath $probePath -Algorithm SHA256).Hash
    started_utc = $started.ToString('O')
    finished_utc = $finished.ToString('O')
    exit_code = $probeExitCode
    marker = $markerText
    log = [System.IO.Path]::GetFileName($log)
}
$evidence | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $report -Encoding utf8

if ($probeExitCode -ne 0) {
    throw "Cross-host Fast-DDS probe failed with exit code $probeExitCode. Evidence: $report"
}
Write-Host "Cross-host evidence written to $report"
