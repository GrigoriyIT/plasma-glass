# Installs (or updates) Glass VPN from a build folder (build.ps1): the service, the cores,
# glassvpnctl and the tray app, which starts at every sign-in. Run elevated.
#   powershell -ExecutionPolicy Bypass -File install.ps1 -Source <dir>
#   powershell -ExecutionPolicy Bypass -File install.ps1 -Uninstall [-KeepData]
param([string]$Source = (Join-Path $PSScriptRoot 'out'), [switch]$Uninstall, [switch]$KeepData)

$ErrorActionPreference = 'Stop'
$Name = 'GlassVPN'
$Dir = Join-Path $env:ProgramFiles 'GlassVPN'
$Data = Join-Path $env:ProgramData 'GlassVPN'

function Stop-Glass {
    $svc = Get-Service $Name -ErrorAction SilentlyContinue
    if ($svc -and $svc.Status -ne 'Stopped') {
        Stop-Service $Name -Force
        $svc.WaitForStatus('Stopped', [TimeSpan]::FromSeconds(30))
    }
    # the job object takes the cores down with the service; this is for a crashed one
    $ours = { Get-Process GlassVPN, GlassVpnService, sing-box, xray -ErrorAction SilentlyContinue |
              Where-Object { $_.Path -like "$Dir\*" } }
    & $ours | Stop-Process -Force -ErrorAction SilentlyContinue
    for ($i = 0; $i -lt 50 -and (& $ours); $i++) { Start-Sleep -Milliseconds 200 }
}

function Set-MachinePath([bool]$add) {
    $p = [Environment]::GetEnvironmentVariable('Path', 'Machine').Split(';') | Where-Object { $_ -and $_ -ne $Dir }
    if ($add) { $p += $Dir }
    [Environment]::SetEnvironmentVariable('Path', ($p -join ';'), 'Machine')
}

$RunKey = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Run'
$Shortcut = Join-Path $env:ProgramData 'Microsoft\Windows\Start Menu\Programs\Glass VPN.lnk'

if ($Uninstall) {
    Stop-Glass
    Remove-ItemProperty $RunKey -Name $Name -ErrorAction SilentlyContinue
    Remove-Item $Shortcut -ErrorAction SilentlyContinue
    if (Get-Service $Name -ErrorAction SilentlyContinue) { sc.exe delete $Name | Out-Null }
    Set-MachinePath $false
    Remove-Item $Dir -Recurse -Force -ErrorAction SilentlyContinue
    if (-not $KeepData) { Remove-Item $Data -Recurse -Force -ErrorAction SilentlyContinue }
    Write-Host 'Glass VPN removed'
    return
}

foreach ($f in 'GlassVpnService.exe', 'glassvpnctl.cmd', 'sing-box.exe', 'xray.exe', 'GlassVPN.exe') {
    if (-not (Test-Path (Join-Path $Source $f))) { throw "$f is missing in $Source" }
}
Stop-Glass
# a clean folder: no leftovers from an older layout
Remove-Item $Dir -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $Dir | Out-Null
Copy-Item (Join-Path $Source '*') $Dir -Recurse -Force

$bin = "`"$Dir\GlassVpnService.exe`""
if (-not (Get-Service $Name -ErrorAction SilentlyContinue)) {
    New-Service -Name $Name -BinaryPathName $bin -DisplayName 'Glass VPN' -StartupType Automatic `
        -Description 'Glass VPN tunnel: sing-box (TUN) and Xray (VLESS).' | Out-Null
}
# restart after a crash: 5 s, 10 s, then every 30 s; the counter resets after a day
sc.exe failure $Name reset= 86400 actions= restart/5000/restart/10000/restart/30000 | Out-Null
sc.exe failureflag $Name 1 | Out-Null
sc.exe sidtype $Name unrestricted | Out-Null
Set-MachinePath $true
Set-ItemProperty $RunKey -Name $Name -Value "`"$Dir\GlassVPN.exe`""
# the Start menu entry opens the window (a second launch hands over to the running tray app)
$lnk = (New-Object -ComObject WScript.Shell).CreateShortcut($Shortcut)
$lnk.TargetPath = "$Dir\GlassVPN.exe"
$lnk.Arguments = '--show'
$lnk.WorkingDirectory = $Dir
$lnk.Description = 'Glass VPN'
$lnk.Save()
Start-Service $Name
Write-Host "Glass VPN installed in $Dir, service: $((Get-Service $Name).Status)"
