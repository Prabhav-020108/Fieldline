# ==============================================================================
# FieldLine Edge Mode Launcher (Zero Internet / Offline Demo)
# ==============================================================================
# This script starts FieldLine components configured for 100% offline edge mode.
# It sets in-memory environment variables for the session so your normal .env.local
# files remain 100% untouched for your primary cloud demo.
#
# Usage:
#   .\start-edge.ps1                  # Interactive menu
#   .\start-edge.ps1 -Component all   # Spawns all edge services in separate windows
#   .\start-edge.ps1 -Component agent # Runs just the edge agent in current window
#   .\start-edge.ps1 -Component livekit # Starts the local LiveKit server docker container
# ==============================================================================

param (
    [ValidateSet("all", "livekit", "piper", "agent", "dashboard", "backend", "menu")]
    [string]$Component = "menu"
)

$RootDir = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }

function Get-LiveKitKeysArg {
    $LkKey = $env:LIVEKIT_API_KEY
    $LkSecret = $env:LIVEKIT_API_SECRET
    $envPath = "$RootDir\agent\.env.local"
    if ((-not $LkKey -or -not $LkSecret) -and (Test-Path $envPath)) {
        Get-Content $envPath | ForEach-Object {
            if ($_ -match '^\s*LIVEKIT_API_KEY\s*=\s*["'']?([^"'']+)["'']?') { $LkKey = $matches[1].Trim() }
            if ($_ -match '^\s*LIVEKIT_API_SECRET\s*=\s*["'']?([^"'']+)["'']?') { $LkSecret = $matches[1].Trim() }
        }
    }
    if ($LkKey -and $LkSecret) {
        return "${LkKey}: ${LkSecret}`ndevkey: secret"
    }
    return "devkey: secret"
}

function Get-HostLanIp {
    $ip = (Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
           Where-Object { ($_.InterfaceAlias -match 'Wi-Fi' -or $_.InterfaceAlias -match 'Ethernet') -and $_.IPAddress -notmatch '^(169\.254|127\.|172\.(1[6-9]|2[0-9]|3[0-1]))' } |
           Select-Object -ExpandProperty IPAddress -First 1)
    if (-not $ip) { $ip = "127.0.0.1" }
    return $ip
}

function Start-EdgeLiveKit {
    Write-Host "`n[1/5] Starting Local LiveKit WebRTC Server (Docker)..." -ForegroundColor Cyan
    $keys = Get-LiveKitKeysArg
    $lanIp = Get-HostLanIp
    docker rm -f livekit-edge 2>$null | Out-Null
    docker run -d --name livekit-edge --restart unless-stopped -p 7880:7880 -p 7881:7881 -p 50000-50100:50000-50100/udp -e LIVEKIT_KEYS="$keys" livekit/livekit-server:latest --dev --bind 0.0.0.0 --node-ip "$lanIp"
    Write-Host "LiveKit listening on ws://0.0.0.0:7880 (Advertised WebRTC node-ip: $lanIp)" -ForegroundColor Green
}

function Start-EdgePiper {
    Write-Host "`n[2/5] Starting Local Piper Neural TTS Server..." -ForegroundColor Cyan
    Set-Location "$RootDir\agent"
    uv run python src/local_tts_server.py
}

function Start-EdgeBackend {
    Write-Host "`n[3/5] Starting FastAPI Backend (Edge Mode, 0.0.0.0)..." -ForegroundColor Cyan
    Set-Location "$RootDir\backend"
    $env:FIELDLINE_EDGE_MODE = "1"
    uv run uvicorn main:app --host 0.0.0.0 --port 8000 --reload
}

function Start-EdgeAgent {
    Write-Host "`n[4/5] Starting FieldLine Voice Agent (100% Offline Edge Mode)..." -ForegroundColor Cyan
    Set-Location "$RootDir\agent"
    $env:LIVEKIT_URL = "ws://localhost:7880"
    $env:FIELDLINE_EDGE_MODE = "1"
    $env:FIELDLINE_CLOUD_DEPLOY = "0"
    $env:WHISPER_MODEL_SIZE = "small"
    $env:OLLAMA_BASE_URL = "http://localhost:11434/v1"
    $env:OLLAMA_MODEL = "llama3.2:3b"
    $env:PIPER_TTS_BASE_URL = "http://localhost:8880/v1"
    uv run python src/agent.py dev
}

function Start-EdgeDashboard {
    Write-Host "`n[5/5] Starting Next.js Dashboard (Bound to 0.0.0.0 for Mobile Hotspot)..." -ForegroundColor Cyan
    Set-Location "$RootDir\dashboard"
    $env:NEXT_PUBLIC_LIVEKIT_URL = "ws://localhost:7880"
    npm run dev -- -H 0.0.0.0
}

function Start-AllInWindows {
    Write-Host "`nLaunching all FieldLine Edge components in separate terminal windows..." -ForegroundColor Yellow

    # 1. LiveKit Server
    Start-EdgeLiveKit

    # 2. Piper TTS
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$RootDir\agent'; uv run python src/local_tts_server.py"

    # 3. FastAPI Backend
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$RootDir\backend'; `$env:FIELDLINE_EDGE_MODE='1'; uv run uvicorn main:app --host 0.0.0.0 --port 8000 --reload"

    # Brief delay to allow Piper & LiveKit to bind ports
    Start-Sleep -Seconds 3

    # 4. FieldLine Agent (Edge Mode)
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$RootDir\agent'; `$env:LIVEKIT_URL='ws://localhost:7880'; `$env:FIELDLINE_EDGE_MODE='1'; `$env:FIELDLINE_CLOUD_DEPLOY='0'; `$env:WHISPER_MODEL_SIZE='small'; `$env:OLLAMA_BASE_URL='http://localhost:11434/v1'; `$env:OLLAMA_MODEL='llama3.2:3b'; `$env:PIPER_TTS_BASE_URL='http://localhost:8880/v1'; uv run python src/agent.py dev"

    # 5. Dashboard
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$RootDir\dashboard'; `$env:NEXT_PUBLIC_LIVEKIT_URL='ws://localhost:7880'; npm run dev -- -H 0.0.0.0"

    Write-Host "`nAll 5 Edge services have been launched!" -ForegroundColor Green
    Write-Host "Connect your phone to your laptop's Wi-Fi hotspot and navigate to: http://<laptop-ip>:3000" -ForegroundColor Cyan
}

switch ($Component) {
    "livekit"   { Start-EdgeLiveKit }
    "piper"     { Start-EdgePiper }
    "backend"   { Start-EdgeBackend }
    "agent"     { Start-EdgeAgent }
    "dashboard" { Start-EdgeDashboard }
    "all"       { Start-AllInWindows }
    "menu" {
        Write-Host "==========================================================" -ForegroundColor Cyan
        Write-Host "         FIELDLINE EDGE MODE (ZERO INTERNET) LAUNCHER     " -ForegroundColor Yellow
        Write-Host "==========================================================" -ForegroundColor Cyan
        Write-Host " 1. Launch All (Spawns 5 Edge terminals automatically)"
        Write-Host " 2. Start LiveKit WebRTC Server (Docker)"
        Write-Host " 3. Start Local Piper Neural TTS (port 8880)"
        Write-Host " 4. Start FastAPI Backend (Edge mode on 0.0.0.0:8000)"
        Write-Host " 5. Start Voice Agent (Edge mode: local Whisper + Llama + Piper)"
        Write-Host " 6. Start Dashboard (Bound to 0.0.0.0:3000 for Phone Wi-Fi)"
        Write-Host " Q. Quit"
        Write-Host "==========================================================" -ForegroundColor Cyan
        $choice = Read-Host "Select an option (1-6, Q)"
        switch ($choice) {
            "1" { Start-AllInWindows }
            "2" { Start-EdgeLiveKit }
            "3" { Start-EdgePiper }
            "4" { Start-EdgeBackend }
            "5" { Start-EdgeAgent }
            "6" { Start-EdgeDashboard }
            default { Write-Host "Exiting." }
        }
    }
}
