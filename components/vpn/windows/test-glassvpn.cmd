<# : batch part
@echo off
rem Glass VPN field test: subscription, sleep/resume, Wi-Fi reconnect. Double-click it.
rem Elevated: restarting the Wi-Fi adapter needs it.
net session >nul 2>&1 || (
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)
powershell -NoProfile -ExecutionPolicy Bypass -Command "iex ([IO.File]::ReadAllText('%~f0', [Text.Encoding]::UTF8))"
exit /b
#>
$ErrorActionPreference = 'Continue'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$report = Join-Path ([Environment]::GetFolderPath('Desktop')) 'glassvpn-test.txt'
$ctl = Join-Path $env:ProgramFiles 'GlassVPN\glassvpnctl.cmd'
function St { try { & $ctl status | ConvertFrom-Json } catch { $null } }
function Line($s) { Write-Host ("{0:HH:mm:ss} {1}" -f (Get-Date), $s) }
function Watch($what, $seconds) {
    # state changes, second by second, until "on" or the time runs out
    $t0 = Get-Date; $last = ''
    while (((Get-Date) - $t0).TotalSeconds -lt $seconds) {
        $s = St
        $cur = if ($s) { "$($s.state) probe=$($s.probe_ms)" } else { 'no answer from the service' }
        if ($cur -ne $last) { Line ("  {0} +{1:N0}s: {2}" -f $what, ((Get-Date) - $t0).TotalSeconds, $cur); $last = $cur }
        if ($s -and $s.state -eq 'on') { return }
        Start-Sleep 1
    }
}
function Sites {
    foreach ($u in 'https://ipinfo.io/country', 'https://ya.ru/', 'https://api.anthropic.com/', 'https://www.youtube.com/') {
        $r = curl.exe -s -m 10 -o "$env:TEMP\gv.out" -w '%{http_code} %{time_total}s' $u
        $body = if ($u -like '*country') { ' ' + (Get-Content "$env:TEMP\gv.out" -Raw).Trim() } else { '' }
        Line "  $u -> $r$body"
    }
}

Write-Host '=== Glass VPN test ==='
Write-Host ''
$url = Read-Host 'Ссылка на подписку (Enter — пропустить, если уже добавлена)'
# the report starts after the link: it must not end up in the file
Start-Transcript -Path $report -Force | Out-Null
if ($url.Trim()) {
    & $ctl add $url.Trim() | Out-Null
    $first = ((& $ctl servers | ConvertFrom-Json).servers | Where-Object { $_.source -ne 'key' } | Select-Object -First 1).name
    if ($first) { Line "subscription added, connecting to the first server"; & $ctl connect $first | Out-Null }
    else { Line 'subscription: no servers came back (see the log below)' }
}
$s = St
Line "now: $($s.state), server: $($s.server)"
Watch 'connect' 30
Sites

Write-Host ''
Write-Host 'Сейчас ноутбук уснёт. Подождите минуту и разбудите его (кнопка питания или клавиша).'
Write-Host 'Тест продолжится сам. Enter — начать, Ctrl+C — отменить.'
Read-Host | Out-Null
Add-Type -AssemblyName System.Windows.Forms
Line 'going to sleep'
[System.Windows.Forms.Application]::SetSuspendState('Suspend', $false, $false) | Out-Null
Start-Sleep 2
Line 'woke up'
Watch 'resume' 90
Sites

# netsh can't name the network without location access (Windows 11 24H2): restart the adapter
$wifi = Get-NetAdapter -Physical | Where-Object { $_.Status -eq 'Up' -and $_.NdisPhysicalMedium -eq 9 } | Select-Object -First 1
if ($wifi) {
    Write-Host ''
    Line "Wi-Fi: restarting adapter '$($wifi.Name)'"
    Restart-NetAdapter -Name $wifi.Name -Confirm:$false
    Watch 'wi-fi' 90
    Sites
}

Write-Host ''
Write-Host '--- service log ---'
& $ctl logs service 60 | Select-String -NotMatch 'xray: ' | ForEach-Object { $_.Line }
Stop-Transcript | Out-Null
Write-Host ''
Write-Host "Отчёт сохранён: $report"
Read-Host 'Enter — закрыть'
