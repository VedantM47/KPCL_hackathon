<#
  KPCL one-shot demo launcher.
    - frees ports 8000 (API) and 5173 (dashboard) if something is already using them
    - starts the API on all interfaces (so the phone can reach it) and the dashboard dev server
    - opens the firewall for the phone when run as Administrator
    - waits until the API is ready and prints the address to type into the phone app

  Usage (from the project folder):   powershell -ExecutionPolicy Bypass -File .\run-demo.ps1
  Options:  -Breach   jump the live replay to the highest-demand day so a real critical alert fires
            -NoBrowser  don't open the dashboard
#>
param([switch]$Breach, [switch]$NoBrowser)

$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

function Stop-Port($port) {
    $pids = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($p in $pids) {
        Write-Host "  freeing port $port (pid $p)"
        Stop-Process -Id $p -Force -ErrorAction SilentlyContinue
    }
}

Write-Host "`n[1/5] Closing anything on ports 8000 and 5173..." -ForegroundColor Cyan
Stop-Port 8000
Stop-Port 5173
Start-Sleep -Seconds 1

Write-Host "[2/5] Firewall rule for the phone (needs Administrator)..." -ForegroundColor Cyan
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if ($isAdmin) {
    netsh advfirewall firewall delete rule name="KPCL API" | Out-Null
    netsh advfirewall firewall add rule name="KPCL API" dir=in action=allow protocol=TCP localport=8000 | Out-Null
    Write-Host "  rule added for TCP 8000"
} else {
    Write-Host "  skipped (not Administrator). If the phone cannot connect, re-run this script as Administrator once." -ForegroundColor Yellow
}

Write-Host "[3/5] Starting API (all interfaces, port 8000)..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList '-NoExit', '-Command', "Set-Location '$root'; `$host.UI.RawUI.WindowTitle='KPCL API'; python -m uvicorn api.main:app --host 0.0.0.0 --port 8000"

Write-Host "[4/5] Starting dashboard (port 5173)..." -ForegroundColor Cyan
# cmd, not powershell: a fresh PowerShell window blocks npm.ps1 under the default execution policy
if (-not (Test-Path "$root\web_template\node_modules")) {
    Write-Host "  installing dashboard dependencies first (one-time)..." -ForegroundColor Yellow
    Start-Process cmd -ArgumentList '/c', "cd /d `"$root\web_template`" && npm install" -Wait
}
Start-Process cmd -ArgumentList '/k', "title KPCL Dashboard && cd /d `"$root\web_template`" && npm run dev -- --host --port 5173"

Write-Host "[5/5] Waiting for the API to finish loading (models train on startup, ~1-2 min)..." -ForegroundColor Cyan
$ready = $false
for ($i = 0; $i -lt 120; $i++) {
    try {
        Invoke-RestMethod -Uri 'http://127.0.0.1:8000/plants' -TimeoutSec 2 | Out-Null
        $ready = $true
        break
    } catch { Start-Sleep -Seconds 3 }
}
if (-not $ready) { Write-Host "API did not come up - check the 'KPCL API' window for errors." -ForegroundColor Red; exit 1 }

$dashUp = $false
for ($i = 0; $i -lt 20; $i++) {
    try { Invoke-WebRequest -Uri 'http://localhost:5173/' -UseBasicParsing -TimeoutSec 2 | Out-Null; $dashUp = $true; break }
    catch { Start-Sleep -Seconds 2 }
}
if (-not $dashUp) {
    Write-Host "  WARNING: dashboard is not answering on 5173 - read the 'KPCL Dashboard' window for the error." -ForegroundColor Red
}

if ($Breach) {
    $day = (Invoke-RestMethod -Uri 'http://127.0.0.1:8000/schedule/days?top_n=1').date
    Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8000/live/control' -ContentType 'application/json' `
        -Body (@{ jump_to = "$day 05:30"; speed = 1; paused = $false } | ConvertTo-Json) | Out-Null
    Write-Host "  replay jumped to $day - a contract-breach alert fires about 90 seconds in"
}

$ips = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } |
    Select-Object -ExpandProperty IPAddress

Write-Host "`n=== READY ===" -ForegroundColor Green
Write-Host "Dashboard : http://localhost:5173   (Live Monitor -> 'Simulate critical alert' button)"
Write-Host "Phone app : enter one of these as the server address, then START MONITORING:"
foreach ($ip in $ips) { Write-Host "            http://${ip}:8000" }
Write-Host "            (laptop hotspot is usually http://192.168.137.1:8000)"
Write-Host "To stop everything, close the two PowerShell windows (or run this script again).`n"

if (-not $NoBrowser) { Start-Process 'http://localhost:5173/live' }
