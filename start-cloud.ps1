# ==============================================================================
# FieldLine Primary Cloud Demo Launcher (Pitch Presentation)
# ==============================================================================
# This script ensures all edge mode session variables are completely cleared,
# restoring the pristine cloud configuration from .env.local:
#   - LiveKit Cloud (wss://fieldline-y34tzh74.livekit.cloud)
#   - Groq Whisper Large v3 Turbo (STT)
#   - Groq Llama 3.3 120B (openai/gpt-oss-120b)
#   - Cartesia Sonic-3 via LiveKit Cloud Inference (TTS)
#   - FastAPI Backend on localhost:8000
#   - Next.js Dashboard on localhost:3000
# ==============================================================================

param (
    [ValidateSet("all", "agent", "dashboard", "backend", "reset-env", "menu")]
    [string]$Component = "menu"
)

$RootDir = $PSScriptRoot

function Clear-EdgeEnv {
    Remove-Item env:FIELDLINE_EDGE_MODE -ErrorAction SilentlyContinue
    Remove-Item env:LIVEKIT_URL -ErrorAction SilentlyContinue
    Remove-Item env:NEXT_PUBLIC_LIVEKIT_URL -ErrorAction SilentlyContinue
    Remove-Item env:FIELDLINE_CLOUD_DEPLOY -ErrorAction SilentlyContinue
    Remove-Item env:WHISPER_MODEL_SIZE -ErrorAction SilentlyContinue
    Remove-Item env:OLLAMA_BASE_URL -ErrorAction SilentlyContinue
    Remove-Item env:OLLAMA_MODEL -ErrorAction SilentlyContinue
    Remove-Item env:PIPER_TTS_BASE_URL -ErrorAction SilentlyContinue
    Write-Host "Edge environment variables cleared from current session." -ForegroundColor Green
}

function Start-CloudBackend {
    Clear-EdgeEnv
    Write-Host "`nStarting FastAPI Backend in Primary Cloud Mode..." -ForegroundColor Cyan
    Set-Location "$RootDir\backend"
    uv run uvicorn main:app --host 0.0.0.0 --port 8000 --reload
}

function Start-CloudAgent {
    Clear-EdgeEnv
    Write-Host "`nStarting FieldLine Voice Agent in Primary Cloud Demo Mode..." -ForegroundColor Cyan
    Write-Host "  Using: LiveKit Cloud + Groq Llama 3.3 120B + Cartesia Sonic-3" -ForegroundColor Yellow
    Set-Location "$RootDir\agent"
    uv run python src/agent.py dev
}

function Start-CloudDashboard {
    Clear-EdgeEnv
    Write-Host "`nStarting Next.js Dashboard in Primary Cloud Mode..." -ForegroundColor Cyan
    Set-Location "$RootDir\dashboard"
    npm run dev
}

function Start-CloudAllInWindows {
    Write-Host "`nStopping any local LiveKit docker container..." -ForegroundColor Yellow
    docker stop livekit-edge 2>$null

    Write-Host "Launching all Primary Cloud Demo components in separate terminal windows..." -ForegroundColor Yellow

    # 1. FastAPI Backend
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$RootDir\backend'; Remove-Item env:FIELDLINE_EDGE_MODE -ErrorAction SilentlyContinue; uv run uvicorn main:app --host 0.0.0.0 --port 8000 --reload"

    # 2. Next.js Dashboard
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$RootDir\dashboard'; Remove-Item env:NEXT_PUBLIC_LIVEKIT_URL -ErrorAction SilentlyContinue; npm run dev"

    # Brief delay for servers to spin up
    Start-Sleep -Seconds 2

    # 3. FieldLine Cloud Agent
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$RootDir\agent'; Remove-Item env:FIELDLINE_EDGE_MODE, env:LIVEKIT_URL -ErrorAction SilentlyContinue; uv run python src/agent.py dev"

    Write-Host "`nPrimary Cloud Demo services launched!" -ForegroundColor Green
    Write-Host "Open http://localhost:3000 in your browser for the primary demo." -ForegroundColor Cyan
}

switch ($Component) {
    "reset-env" { Clear-EdgeEnv }
    "backend"   { Start-CloudBackend }
    "agent"     { Start-CloudAgent }
    "dashboard" { Start-CloudDashboard }
    "all"       { Start-CloudAllInWindows }
    "menu" {
        Write-Host "==========================================================" -ForegroundColor Cyan
        Write-Host "      FIELDLINE PRIMARY CLOUD DEMO (PITCH) LAUNCHER       " -ForegroundColor Yellow
        Write-Host "==========================================================" -ForegroundColor Cyan
        Write-Host " 1. Launch All (Spawns Backend, Dashboard, Cloud Agent)"
        Write-Host " 2. Start Cloud Voice Agent (Groq 120B + Cartesia Sonic-3)"
        Write-Host " 3. Start Backend (localhost:8000)"
        Write-Host " 4. Start Dashboard (localhost:3000)"
        Write-Host " 5. Clear Edge Environment Variables from this session"
        Write-Host " Q. Quit"
        Write-Host "==========================================================" -ForegroundColor Cyan
        $choice = Read-Host "Select an option (1-5, Q)"
        switch ($choice) {
            "1" { Start-CloudAllInWindows }
            "2" { Start-CloudAgent }
            "3" { Start-CloudBackend }
            "4" { Start-CloudDashboard }
            "5" { Clear-EdgeEnv }
            default { Write-Host "Exiting." }
        }
    }
}
