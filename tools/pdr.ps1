param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $Arguments
)

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    throw "Python 3.9 or newer is required to run pdr."
}
& $python.Source (Join-Path $PSScriptRoot 'pdr.py') @Arguments
exit $LASTEXITCODE
