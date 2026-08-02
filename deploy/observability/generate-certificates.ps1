param([string]$OutputDirectory = "$PSScriptRoot/certificates")
$ErrorActionPreference = "Stop"
New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
$openssl = (Get-Command openssl.exe -ErrorAction Stop).Source
$serverExtensions = Join-Path $OutputDirectory "server.ext"
$clientExtensions = Join-Path $OutputDirectory "client.ext"
@(
    "subjectAltName=DNS:collector,DNS:localhost,IP:127.0.0.1"
    "extendedKeyUsage=serverAuth"
) | Set-Content -Encoding ascii $serverExtensions
"extendedKeyUsage=clientAuth" | Set-Content -Encoding ascii $clientExtensions
& $openssl req -x509 -newkey rsa:3072 -nodes -days 3650 -subj "/CN=PocoDDS Local CA" -keyout "$OutputDirectory/ca.key" -out "$OutputDirectory/ca.crt"
& $openssl req -newkey rsa:3072 -nodes -subj "/CN=collector" -keyout "$OutputDirectory/server.key" -out "$OutputDirectory/server.csr"
& $openssl x509 -req -in "$OutputDirectory/server.csr" -CA "$OutputDirectory/ca.crt" -CAkey "$OutputDirectory/ca.key" -CAcreateserial -days 825 -extfile $serverExtensions -out "$OutputDirectory/server.crt"
& $openssl req -newkey rsa:3072 -nodes -subj "/CN=pdr-runtime" -keyout "$OutputDirectory/client.key" -out "$OutputDirectory/client.csr"
& $openssl x509 -req -in "$OutputDirectory/client.csr" -CA "$OutputDirectory/ca.crt" -CAkey "$OutputDirectory/ca.key" -CAcreateserial -days 825 -extfile $clientExtensions -out "$OutputDirectory/client.crt"
Write-Host "Generated local mTLS CA, server and client certificates in $OutputDirectory"
