param(
    [string]$EvidenceDirectory = '.\cross-host-evidence'
)

$ErrorActionPreference = 'Stop'
$evidencePath = (Resolve-Path -LiteralPath $EvidenceDirectory).Path
$reports = @{}
Get-ChildItem -LiteralPath $evidencePath -Filter '*.json' | ForEach-Object {
    $report = Get-Content -LiteralPath $_.FullName -Raw | ConvertFrom-Json
    if ($report.schema -eq 'PocoDDS.CrossHostEvidence.v1') {
        $reports[$report.role] = $report
    }
}

$requiredRoles = @('subscriber', 'publisher', 'control-agent', 'control-client')
foreach ($role in $requiredRoles) {
    if (-not $reports.ContainsKey($role)) {
        throw "Missing evidence for role '$role'."
    }
    if ($reports[$role].exit_code -ne 0) {
        throw "Role '$role' failed with exit code $($reports[$role].exit_code)."
    }
    $logPath = Join-Path $evidencePath $reports[$role].log
    if (-not (Test-Path -LiteralPath $logPath)) {
        throw "Missing raw log for role '$role': $logPath"
    }
}

$domains = @($requiredRoles | ForEach-Object { $reports[$_].domain } | Select-Object -Unique)
$hashes = @($requiredRoles | ForEach-Object { $reports[$_].probe_sha256 } | Select-Object -Unique)
if ($domains.Count -ne 1) { throw 'Evidence uses different DDS domains.' }
if ($hashes.Count -ne 1) { throw 'Evidence uses different probe binaries.' }
if ($reports['subscriber'].host -eq $reports['publisher'].host) {
    throw 'Payload evidence came from one host; two physical hosts are required.'
}
if ($reports['control-agent'].host -eq $reports['control-client'].host) {
    throw 'Control evidence came from one host; two physical hosts are required.'
}
if ($reports['subscriber'].marker -ne 'FAST_DDS_TWO_PROCESS_PASS') {
    throw 'Subscriber payload marker is invalid.'
}
if ($reports['control-client'].marker -ne 'FAST_DDS_CONTROL_PASS') {
    throw 'Control-client marker is invalid.'
}

$requiredLogs = @{
    publisher = 'FAST_DDS_PUBLISH_PASS'
    'control-agent' = 'FAST_DDS_CONTROL_AGENT_PASS'
}
foreach ($role in $requiredLogs.Keys) {
    $logPath = Join-Path $evidencePath $reports[$role].log
    if (-not (Select-String -LiteralPath $logPath -SimpleMatch $requiredLogs[$role] -Quiet)) {
        throw "Role '$role' log does not contain '$($requiredLogs[$role])'."
    }
}

Write-Output "FAST_DDS_PHYSICAL_TWO_HOST_ACCEPTANCE_PASS domain=$($domains[0]) sha256=$($hashes[0])"
