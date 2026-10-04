param(
    [ValidateSet("7.3.5","12.1.0")]
    [string]$Version = "12.1.0",
    [Parameter(Mandatory=$true)]
    [string]$WowInterfacePath
)

$root = Split-Path -Parent $PSScriptRoot
$source = Join-Path $root ("addon\AIPlayerControllerExport-{0}" -f $Version)
$target = Join-Path $WowInterfacePath "AddOns\AIPlayerControllerExport"

if (-not (Test-Path $source)) { throw "Addon source not found: $source" }
New-Item -ItemType Directory -Force -Path $target | Out-Null
Copy-Item (Join-Path $source "*") $target -Recurse -Force
Write-Host "Installed AIPlayerControllerExport for WoW $Version -> $target" -ForegroundColor Green
