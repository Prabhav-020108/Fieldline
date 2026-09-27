# FieldLine Operational Runbook: Dual-Mode Demonstration Guide

This runbook is the definitive operational manual for deploying and demonstrating **FieldLine** across its two core operational profiles:
1. **Mode 1: Primary Laptop Cloud Demo** (High-fidelity, ultra-low latency cloud stack for the main pitch).
2. **Mode 2: Zero-Internet Edge Showcase** (100% offline, on-device stack running over local Wi-Fi hotspot to a smartphone).

---

## 1. System Architecture Overview

```
                                  FIELDLINE DUAL-MODE ARCHITECTURE
                                  
  ┌─────────────────────────────────────────────────────────────────────────────────────────────┐
  │                                MODE 1: PRIMARY CLOUD DEMO                                   │
  │                                                                                             │
  │   Technician (PC Browser)                                                                   │
  │          │                                                                                  │
  │          ▼                                                                                  │
  │   LiveKit Cloud  ───▶  Groq Whisper v3 Turbo  ───▶  Groq 120B (gpt-oss)  ───▶  Cartesia     │
  │   (Global WebRTC)      (Cloud Speech-to-Text)       (120B High-Reasoning)      Sonic-3 TTS  │
  │          ▲                                                    │                     │       │
  │          │                                                    ▼                     │       │
  │   Next.js 16 (Port 3000) ───▶ FastAPI Backend (Port 8000) ──▶ Moss Cloud Session   ◀────────┘
  │                               (Supabase Postgres)             (Multi-Tenant Semantic Index)
  └─────────────────────────────────────────────────────────────────────────────────────────────┘
  
  ┌─────────────────────────────────────────────────────────────────────────────────────────────┐
  │                                MODE 2: ZERO-INTERNET EDGE SHOWCASE                          │
  │                                                                                             │
  │   Technician (Phone on Hotspot)                                                             │
  │          │                                                                                  │
  │          ▼ (Local Wi-Fi LAN - NO INTERNET)                                                  │
  │   Docker LiveKit  ───▶  faster-whisper CPU    ───▶  Ollama Llama 3.2 3B  ───▶  Piper ONNX   │
  │   (Port 7880)           (Offline STT Engine)        (Local 3B Model)           TTS (:8880)  │
  │          ▲                                                    │                     │       │
  │          │                                                    ▼                     │       │
  │   Next.js LAN Proxy ───▶ FastAPI (0.0.0.0:8000) ──▶ Local SessionIndex  ◀───────────┘       │
  │   (:3000 /api/backend)   (SQLite System of Record)  (Durable SQLite Sync Queue)             │
  └─────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Fast Launch Comparison

We have created two master orchestrator scripts in the repository root:

| Script | Intended Audience / Setting | Stack Used |
| :--- | :--- | :--- |
| **`.\start-cloud.ps1 -Component all`** | Main hackathon pitch, judge evaluation on laptop | Groq Whisper + Groq 120B + Cartesia Sonic-3 + LiveKit Cloud |
| **`.\start-edge.ps1 -Component all`** | Hardware/Edge demonstration, offline proof on phone | faster-whisper + Ollama 3B + Piper ONNX + Local Docker LiveKit |

> [!IMPORTANT]
> **Windows PowerShell Environment Hygiene:**
> PowerShell environment variables (`$env:VAR = "val"`) persist for the entire lifetime of that terminal window.
> - Always run `.\start-cloud.ps1` or run `Remove-Item env:FIELDLINE_EDGE_MODE, env:LIVEKIT_URL -ErrorAction SilentlyContinue` when returning to the cloud demo from edge testing.

---

## 3. Mode 1: Primary Laptop Cloud Demo (Pitch Mode)

### 3.1 Pre-Flight Verification
Verify that cloud API keys are present in `agent/.env.local`, `backend/.env`, and `dashboard/.env.local`:
- `LIVEKIT_URL="wss://fieldline-y34tzh74.livekit.cloud"`
- `GROQ_API_KEY="gsk_..."`
- `MOSS_PROJECT_ID="..."` & `MOSS_PROJECT_KEY="..."`

### 3.2 Automated Startup
Open PowerShell in the project root:
```powershell
.\start-cloud.ps1 -Component all
```
*This command stops any conflicting local Docker containers, resets all edge environment variables, and launches Backend, Dashboard, and Cloud Agent in separate windows.*

### 3.3 Manual Startup (Alternative)
In **Terminal 1** (Backend):
```powershell
cd backend
uv run uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

In **Terminal 2** (Dashboard):
```powershell
cd dashboard
npm run dev
```

In **Terminal 3** (Voice Agent):
```powershell
cd agent
Remove-Item env:FIELDLINE_EDGE_MODE, env:LIVEKIT_URL -ErrorAction SilentlyContinue
uv run python src/agent.py dev
```

### 3.4 Verification
1. Open `http://localhost:3000` in Google Chrome.
2. Select **Site Demo Electrical Co.** (`site-demo`).
3. Navigate to **Talk to agent** (`/companies/site-demo/call`).
4. Select the **Dispatcher** or **Supervisor** role and click **Join Call**.
5. The agent will greet you immediately: *"FieldLine here, go ahead."*

---

## 4. Mode 2: Zero-Internet Edge Showcase (Phone Demo)

### 4.1 Prerequisites
1. **Windows Wi-Fi Mobile Hotspot**: Enable Windows Mobile Hotspot (Settings → Network & Internet → Mobile Hotspot).
   - Default Host IP: `192.168.137.1`
2. **Smartphone**: Connect phone's Wi-Fi to your laptop's hotspot.
3. **Ollama**: Ensure Ollama is running (`ollama serve`) with `llama3.2:3b` pulled.
4. **Piper TTS**: Voice model `agent/models/en_US-lessac-medium.onnx` present.

### 4.2 Automated Startup
Open PowerShell in the project root:
```powershell
.\start-edge.ps1 -Component all
```
*This starts:*
1. Local LiveKit Docker container (`livekit-edge`, port 7880).
2. Local Piper Neural TTS server (`localhost:8880`).
3. FastAPI Backend bound to `0.0.0.0:8000` with `FIELDLINE_EDGE_MODE=1`.
4. FieldLine Voice Agent in pure offline Edge mode (`FIELDLINE_EDGE_MODE=1`).
5. Next.js Dashboard bound to `0.0.0.0:3000`.

> [!NOTE]
> `docker-compose.edge.yml` defines the core headless edge infrastructure (`livekit`, `backend`, and `agent`). When demonstrating to a mobile phone over a Wi-Fi hotspot, the dashboard is run with host networking via `npm run dev -- -H 0.0.0.0` (as handled automatically by `start-edge.ps1`) so the phone's browser can directly load the dispatch UI over LAN.

### 4.3 Phone Access
1. On your smartphone's browser (Chrome or Safari), open:
   ```
   http://192.168.137.1:3000
   ```
2. Tap **Site Demo Electrical Co.**.
3. Tap **Talk to agent** (`/companies/site-demo/call`).
4. Tap **Join Call** and allow microphone access.
5. Speak naturally into your phone. The speech is transcribed by local CPU `faster-whisper`, reasoned by local `Ollama`, and spoken back via local `Piper ONNX TTS`!

---

## 5. Scripted Demo Scenarios for Judges

Use these exact vocal prompts to demonstrate FieldLine's technical depth:

### Beat 1: Verbatim Safety Manual Retrieval & Citation
- **Technician says:** *"What is the lockout tagout procedure for Main Distribution Panel B?"*
- **FieldLine replies:** *"According to Section 4.2 of the Electrical Safety Manual: Disconnect main breaker CB-101, apply padlock and danger tag at Lockout Station 2, verify zero voltage using an approved multimeter, and discharge residual capacitors before touching busbars."*
- **Highlight for judges:** Notice the exact section and manual citation. FieldLine never paraphrases safety-critical compliance instructions.

### Beat 2: Tunable Confidence Floor & Hallucination Guardrail
- **Technician says:** *"What is the safety procedure for the nuclear reactor core cooling valve?"*
- **FieldLine replies:** *"I cannot locate a verified safety procedure with sufficient confidence (retrieval score below 0.35 threshold). For your safety, please halt work and contact your supervisor immediately."*
- **Highlight for judges:** FieldLine has a mathematical confidence floor (`SAFETY_CONFIDENCE_FLOOR=0.35`). When retrieval confidence is low, it refuses to hallucinate and defers to safety leadership.

### Beat 3: Parts & Inventory Warehouse Lookup
- **Technician says:** *"Do we have any 40-amp dual-pole breakers in stock?"*
- **FieldLine replies:** *"Yes, we have 8 units of the Siemens 40-Amp Dual-Pole Circuit Breaker in stock. They are located in Aisle 3, Shelf B, Bin 12."*
- **Highlight for judges:** Hands-free parts lookup saves 15-20 minutes per work order.

### Beat 4: Voice-Dictated Job Note & Append-Only Audit Trail
- **Technician says:** *"Log a note on job 101: Replaced the faulty contactor, cleaned copper contacts, and tested under full load for 20 minutes."*
- **FieldLine replies:** *"Logged job note for Job 101: Replaced contactor, cleaned contacts, tested 20 min under full load. Recorded in the company audit log."*
- **Highlight for judges:** Switch to the dashboard's **Audit log** tab. Show the newly minted audit event with timestamp, user role, and complete tool payload.

### Beat 5: The Edge & Resilience Kill-Switch (Flagship Demo)
1. In Mode 1 or Mode 2, sever external WAN internet (disconnect Wi-Fi from the internet).
2. Ask: *"What is the fault history for elevator motor unit 4?"*
3. The agent responds instantly from its local `SessionIndex`.
4. Dictate a job note: *"Job 102 completed."*
5. The agent announces: *"Stored locally in offline sync queue."*
6. Restore internet connectivity. Watch `agent/src/sync_queue.py` automatically flush the SQLite records upstream to Moss and the database with zero data loss!

---

## 6. Comprehensive Troubleshooting Matrix

| Symptom | Root Cause | Exact Resolution |
| :--- | :--- | :--- |
| **`ConnectError: All connection attempts failed` on `livekit.plugins.openai.tts.TTS`** | PowerShell session still has `FIELDLINE_EDGE_MODE=1` set, but Piper server is closed | Run: `Remove-Item env:FIELDLINE_EDGE_MODE, env:LIVEKIT_URL`<br>Restart agent: `uv run python src/agent.py dev`<br>*(Or use `.\start-cloud.ps1 -Component agent`)* |
| **Phone shows "Companies Loading..." indefinitely** | Windows Firewall blocking port 8000 on LAN | Bypassed automatically via Next.js `/api/backend` proxy. Ensure phone visits `http://192.168.137.1:3000` (port 3000, not 8000). |
| **Docker `Bind for 0.0.0.0:7880 failed: port is already allocated`** | Existing `livekit-edge` container running | Run: `docker rm -f livekit-edge`<br>Then re-run: `.\start-edge.ps1 -Component livekit` |
| **Microphone fails to activate on Phone** | Browser blocks insecure WebRTC on non-localhost IP | In mobile Chrome, navigate to `chrome://flags/#unsafely-treat-insecure-origin-as-secure`, add `http://192.168.137.1:3000`, and relaunch Chrome. |
| **`Ollama connection refused`** | Ollama daemon not running | Run: `ollama serve` in a background terminal. Verify model: `ollama list`. |
| **LiveKit agent says `no audio frames were pushed`** | Piper TTS returned empty stream or wrong model string | In `local_pipeline.py`, ensure `model="tts-1"` is used for Piper so binary PCM audio stream is decoded. |
