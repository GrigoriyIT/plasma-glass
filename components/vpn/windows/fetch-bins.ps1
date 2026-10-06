# Downloads the cores Glass VPN runs: sing-box (TUN, routing) and Xray (VLESS).
# Versions match the macOS and Linux clients; every archive is checked against a pinned SHA-256.
# Usage: powershell -ExecutionPolicy Bypass -File fetch-bins.ps1 [-Out <dir>]
param([string]$Out = (Join-Path $PSScriptRoot 'bin'))

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$SingBoxVer = '1.14.2'
$XrayVer = '26.3.27'
$Pins = @{
    "sing-box-$SingBoxVer-windows-amd64.zip" = 'c2d8bfff918755808781dfdeeb8581b6c91eb3a243d9a7b55483cfc0c0684d32'
    "Xray-windows-64-$XrayVer.zip"           = 'd004c39288ce9ada487c6f398c7c545f7d749e44bdfdd59dbc9f865afba4e1ad'
}

$tmp = Join-Path ([IO.Path]::GetTempPath()) ('glassvpn-' + [guid]::NewGuid())
New-Item -ItemType Directory -Force $tmp, $Out | Out-Null
try {
    $get = @(
        @{ Name = "sing-box-$SingBoxVer-windows-amd64.zip"
           Url  = "https://github.com/SagerNet/sing-box/releases/download/v$SingBoxVer/sing-box-$SingBoxVer-windows-amd64.zip" },
        @{ Name = "Xray-windows-64-$XrayVer.zip"
           Url  = "https://github.com/XTLS/Xray-core/releases/download/v$XrayVer/Xray-windows-64.zip" }
    )
    foreach ($g in $get) {
        $zip = Join-Path $tmp $g.Name
        Invoke-WebRequest $g.Url -OutFile $zip -UseBasicParsing
        $hash = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower()
        $pin = $Pins[$g.Name]
        if ($pin -notmatch '^[0-9a-f]{64}$') {
            Write-Host "$($g.Name): not pinned yet, sha256 $hash"
        } elseif ($hash -ne $pin) {
            throw "$($g.Name): sha256 $hash does not match the pin $pin"
        }
        Expand-Archive $zip -DestinationPath (Join-Path $tmp ($g.Name + '.d')) -Force
    }
    Copy-Item (Get-ChildItem "$tmp\sing-box-*.d" -Recurse -Filter sing-box.exe | Select-Object -First 1).FullName $Out -Force
    Copy-Item (Join-Path $tmp "Xray-windows-64-$XrayVer.zip.d\xray.exe") $Out -Force
    & (Join-Path $Out 'sing-box.exe') version | Select-Object -First 1
    & (Join-Path $Out 'xray.exe') version | Select-Object -First 1
}
finally {
    Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
}
