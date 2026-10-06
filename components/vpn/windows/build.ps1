# Builds the service, glassvpnctl and the tray app into .\out next to the cores (fetch-bins.ps1 -Out <bins>).
# -Msi also packs .\out into GlassVPN-<version>.msi (needs the wix tool, 5.x, with WixToolset.Util.wixext).
param([string]$Bins = (Join-Path $PSScriptRoot 'bin'), [switch]$Msi, [string]$Wix = 'wix')
$ErrorActionPreference = 'Stop'
$out = Join-Path $PSScriptRoot 'out'
Remove-Item $out -Recurse -Force -ErrorAction SilentlyContinue
foreach ($p in 'Service', 'App') {
    dotnet publish (Join-Path $PSScriptRoot "src\$p") -c Release -nologo -o $out
    if ($LASTEXITCODE) { throw "publish $p failed" }
}
Remove-Item (Join-Path $out '*.pdb') -ErrorAction SilentlyContinue
Copy-Item (Join-Path $Bins '*.exe') $out
Copy-Item (Join-Path $PSScriptRoot 'glassvpnctl.cmd') $out

if ($Msi) {
    $version = ([xml](Get-Content (Join-Path $PSScriptRoot 'Directory.Build.props'))).Project.PropertyGroup.Version | Select-Object -First 1
    $msiPath = Join-Path $PSScriptRoot "GlassVPN-$version.msi"
    & $Wix build -arch x64 -d "Version=$version" -bindpath "out=$out" -ext WixToolset.Util.wixext `
        -o $msiPath (Join-Path $PSScriptRoot 'installer\GlassVPN.wxs')
    if ($LASTEXITCODE) { throw 'msi build failed' }
    Remove-Item ([IO.Path]::ChangeExtension($msiPath, '.wixpdb')) -ErrorAction SilentlyContinue
    Write-Host "MSI: $msiPath"
}
