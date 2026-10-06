# Builds the service and glassvpnctl into .\out next to the cores (fetch-bins.ps1 -Out <bins>).
param([string]$Bins = (Join-Path $PSScriptRoot 'bin'))
$ErrorActionPreference = 'Stop'
$out = Join-Path $PSScriptRoot 'out'
Remove-Item $out -Recurse -Force -ErrorAction SilentlyContinue
foreach ($p in 'Service', 'Cli') {
    dotnet publish (Join-Path $PSScriptRoot "src\$p") -c Release -nologo -o $out
    if ($LASTEXITCODE) { throw "publish $p failed" }
}
Remove-Item (Join-Path $out '*.pdb') -ErrorAction SilentlyContinue
Copy-Item (Join-Path $Bins '*.exe') $out
