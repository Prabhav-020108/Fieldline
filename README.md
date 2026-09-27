# FieldLine

> **Hands-Free Autonomous Voice Dispatch Copilot for Field Service Technicians**  
> *Built for the YC Fall 2026 × Moss Zero Latency Builder Sprint Hackathon (HiDevs, Bengaluru)*

[![Agent CI](https://github.com/Prabhav-020108/Fieldline/actions/workflows/agent-ci.yml/badge.svg)](https://github.com/Prabhav-020108/Fieldline/actions/workflows/agent-ci.yml)
[![Backend CI](https://github.com/Prabhav-020108/Fieldline/actions/workflows/backend-ci.yml/badge.svg)](https://github.com/Prabhav-020108/Fieldline/actions/workflows/backend-ci.yml)
[![Dashboard CI](https://github.com/Prabhav-020108/Fieldline/actions/workflows/dashboard-ci.yml/badge.svg)](https://github.com/Prabhav-020108/Fieldline/actions/workflows/dashboard-ci.yml)
[![Docker Build](https://github.com/Prabhav-020108/Fieldline/actions/workflows/docker-build.yml/badge.svg)](https://github.com/Prabhav-020108/Fieldline/actions/workflows/docker-build.yml)

---

## 1. Executive Summary

Field service technicians working on electrical switchgear, commercial HVAC systems, elevator machinery rooms, and remote telecom towers face a universal failure mode: **they cannot type on keyboards or touch screens with heavy protective gloves, and cellular connectivity drops dead the moment they step into a basement, elevator shaft, or remote facility.**

FieldLine solves this with an **offline-first, hands-free voice copilot**:
- **Dual-Operational Architecture:** Runs as an ultra-low latency, high-fidelity cloud agent (Open-weight 120B model via Groq: `openai/gpt-oss-120b` + Cartesia Sonic-3 on LiveKit Cloud) and seamlessly hot-swaps to a **100% autonomous on-device edge stack** (faster-whisper CPU + Ollama Llama 3.2 3B + Piper Neural TTS) when connectivity is lost.
- **Moss Offline-First `SessionIndex`:** In-process semantic memory hydrated at shift start keeps answering compliance, safety, and inventory queries with **zero network connection**.
- **Verbatim Safety Retrieval:** Never hallucinates safety procedures. Cites exact sections and manuals word-for-word, governed by a strict mathematical confidence floor (`SAFETY_CONFIDENCE_FLOOR=0.35`).
- **Durable Offline Sync Queue:** Audio notes, job completions, and audit logs are persisted to a transactional SQLite queue with exponential backoff, jitter, and idempotency keys, draining upstream automatically upon reconnect.
- **Zero-Config Mobile Hotspot Access:** Next.js built-in LAN proxy (`/api/backend`) and dynamic WebRTC IP rewriting allow technicians to connect smartphones over a local Wi-Fi hotspot without firewall or CORS roadblocks.

---

## 2. System Architecture

```
                                      FIELDLINE ARCHITECTURAL MATRIX
                                      
  ┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
  │                                    MODE 1: PRIMARY CLOUD DEMO                                   │
  │                                                                                                 │
  │   Technician (Browser)                                                                          │
  │          │ WebRTC (WSS)                                                                         │
  │          ▼                                                                                      │
  │   LiveKit Cloud ─────────▶  Groq Whisper v3 Turbo  ───▶  Groq 120B (gpt-oss)  ───▶  Cartesia   │
  │   (Global Edge Mesh)        (Streaming STT)              (120B High-Reasoning)      Sonic-3 TTS │
  │          │                                                        │                      │      │
  │          ▼                                                        ▼                      │      │
  │   Next.js 16 Dashboard ──▶ FastAPI Backend (:8000) ───────▶ Moss Cloud Session ◀────────┘      │
  │   (Turbopack on :3000)     (Postgres / Supabase)            (Multi-Tenant Semantic Index)       │
  └─────────────────────────────────────────────────────────────────────────────────────────────────┘
  
  ┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
  │                                    MODE 2: ZERO-INTERNET EDGE SHOWCASE                          │
  │                                                                                                 │
  │   Technician (Phone over Wi-Fi Hotspot - NO INTERNET)                                           │
  │          │ WebRTC (WS LAN)                                                                      │
  │          ▼                                                                                      │
  │   LiveKit Server (Docker) ──▶ faster-whisper CPU  ────▶  Ollama Llama 3.2 3B  ───▶  Piper ONNX  │
  │   (Port 7880 on 0.0.0.0)      (Local CPU STT)            (Local 3B Model :11434)    TTS (:8880) │
  │          │                                                        │                      │      │
  │          ▼                                                        ▼                      │      │
  │   Next.js LAN Proxy ─────▶ FastAPI Backend (:8000) ───────▶ Local SessionIndex ◀────────┘      │
  │   (:3000 /api/backend)     (SQLite Local Storage)           (Durable SQLite Sync Queue)         │
  └─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. What FieldLine Does: 5 Core Tools

A technician communicates entirely hands-free via voice headset. The agent dynamically routes commands through 5 specialized tools:

| Tool | Capability | Compliance & Operational Guarantee |
| :--- | :--- | :--- |
| **`fault_history`** | Equipment maintenance & historical breakdown logs | Returns past failure patterns, replaced components, and recurring anomalies. |
| **`safety_procedure`** | Verbatim safety & Lockout/Tagout (LOTO) protocols | **Never paraphrases safety-critical compliance instructions.** Cites source manual and section. Defers to supervisor if confidence < `0.35`. |
| **`inventory_lookup`** | Warehouse part availability & bin coordinates | Locates spare components, quantities on hand, aisle/bin numbers across trucks and warehouses. |
| **`dispatch_status`** | Real-time work order queue & reroute notifications | Alerts technician of job escalations, schedule shifts, or SLA deadlines. |
| **`log_job_note`** | Voice-dictated job completion notes | Dictated notes are indexed into Moss memory and queued to the audit log. |

Every single tool interaction is recorded in a tamper-evident, append-only **Audit Log** reviewable in real time on the dispatch dashboard.

---

## 4. Repository Structure

```
Fieldline/
├── agent/                         # LiveKit Agents (Python) voice assistant
│   ├── src/
│   │   ├── agent.py               # Worker entrypoint, dynamic mode banner & diagnostics
│   │   ├── company_context.py     # Multi-tenant isolation via ContextVar
│   │   ├── moss_client.py         # Per-company Moss router + local SessionIndex
│   │   ├── connectivity.py        # Real-time network probe & debounced state alerts
│   │   ├── sync_queue.py          # Durable SQLite sync queue with backoff & idempotency
│   │   ├── role_cache.py          # Local HMAC role verification (no network needed)
│   │   ├── tracing.py             # OpenTelemetry + Arize Phoenix observability
│   │   ├── settings.py            # Strict Pydantic fail-fast configuration
│   │   ├── local_pipeline.py      # faster-whisper + Ollama + Piper neural TTS pipeline
│   │   ├── audit_log.py           # Machine-to-machine audit logging
│   │   ├── local_tts_server.py    # Local Piper ONNX server (OpenAI-compatible)
│   │   └── tools/                 # 5 specialized dispatch tools
│   ├── tests/                     # 88 automated unit tests
│   ├── Dockerfile                 # Production agent container
│   └── pyproject.toml             # Python 3.12 dependencies (uv)
├── backend/                       # FastAPI enterprise dispatch backend
│   ├── main.py                    # RESTful endpoints, CORS regex, slowapi rate limiting
│   ├── auth.py                    # JWT authentication & role-based access control (RBAC)
│   ├── models.py                  # SQLAlchemy models with dual-support (Postgres & SQLite)
│   ├── settings.py                # Environment configuration
│   ├── seed_db.py                 # Multi-tenant seed data (Site Demo & Acme Elevator)
│   ├── moss_sync.py               # Bi-directional sync engine to Moss cloud indices
│   ├── migrations/                # Alembic schema migrations
│   ├── tests/                     # 97 automated unit tests
│   └── Dockerfile                 # Production backend container
├── dashboard/                     # Next.js 16 (Turbopack) dispatch console
│   ├── app/                       # App router with multi-tenant company views
│   │   ├── api/backend/[...path]/ # Built-in LAN proxy bypassing mobile firewall blocks
│   │   ├── api/livekit-token/     # Dynamic LAN WebRTC IP rewriting & JWT minting
│   │   └── companies/[companyId]/ # Dispatch views: Overview, Jobs, Safety, Inventory, Call
│   ├── lib/api.ts                 # Resilient HTTP client with LAN detection & timeouts
│   └── next.config.ts             # Cross-origin allowedDevOrigins configuration
├── docs/                          # In-depth technical documentation
│   ├── RUNBOOK.md                 # Step-by-step Dual-Mode Demonstration & Troubleshooting
│   ├── CONNECTIVITY_MODEL.md      # Detailed 3-Tier connectivity specification
│   ├── EDGE_HARDWARE_REQUIREMENTS.md # Edge compute & RAM specifications
│   └── REQUIREMENTS_TRACEABILITY.md  # Functional & Non-Functional requirement matrix
├── render.yaml                    # Automated 1-Click Render Cloud Deployment Blueprint
├── start-cloud.ps1                # 1-Click orchestrator for Primary Laptop Cloud Demo
├── start-edge.ps1                 # 1-Click orchestrator for Zero-Internet Edge Showcase
└── docker-compose.edge.yml        # Docker Compose definition for full edge stack
```

---

## 5. Quickstart: Dual-Mode Demonstration

FieldLine includes dedicated PowerShell launchers that isolate environment variables so neither demo can ever break or contaminate the other.

### 5.1 Mode 1: Primary Laptop Cloud Demo (Main Pitch)

Run from PowerShell in the project root:
```powershell
.\start-cloud.ps1 -Component all
```
*This command stops any conflicting local Docker containers, purges edge session variables, and spawns the Backend, Dashboard, and Cloud Agent across three terminal windows.*

1. Open `http://localhost:3000` in Google Chrome.
2. Select **Site Demo Electrical Co.** (`site-demo`).
3. Navigate to **Talk to agent** (`/companies/site-demo/call`).
4. Select the **Dispatcher** role and click **Join Call**.
5. Speak: *"What is the lockout tagout procedure for Main Distribution Panel B?"*

---

### 5.2 Mode 2: Zero-Internet Edge Showcase (Phone Demo)

Run from PowerShell in the project root:
```powershell
.\start-edge.ps1 -Component all
```
*This starts the local Docker LiveKit server, local Piper ONNX TTS, FastAPI on `0.0.0.0:8000`, the Edge Voice Agent, and the Dashboard on `0.0.0.0:3000`.*

1. Enable **Windows Mobile Hotspot** (Settings → Network & Internet → Mobile Hotspot).
2. Connect your smartphone to your laptop's Wi-Fi hotspot.
3. On your phone's browser, open:
   ```
   http://192.168.137.1:3000
   ```
4. Tap **Site Demo Electrical Co.** → **Talk to agent** → **Join Call**.
5. Speak into your phone: *"Do we have any 40-amp dual-pole breakers in stock?"*
6. Speech is processed 100% on your laptop's CPU with zero external internet!

> [!NOTE]
> `docker-compose.edge.yml` defines the core headless edge infrastructure (`livekit`, `backend`, and `agent`). When demonstrating to a smartphone over Wi-Fi hotspot, the Next.js dashboard is launched with host networking via `npm run dev -- -H 0.0.0.0` (as handled automatically by `start-edge.ps1`) so the phone's browser can directly load the dispatch UI over LAN.

For complete scripted pitch beats and diagnostic procedures, refer to [docs/RUNBOOK.md](file:///c:/Users/Prabhav/Downloads/Fieldline/docs/RUNBOOK.md).

---

## 6. Cloud Deployment (Render & Vercel)

FieldLine is cloud-ready and features a verified [render.yaml](file:///c:/Users/Prabhav/Downloads/Fieldline/render.yaml) blueprint.

### 6.1 Deploying Backend to Render
1. Connect your GitHub repository to [Render](https://render.com).
2. Click **New +** → **Blueprint** and select this repository.
3. Render automatically provisions the `fieldline-backend` Web Service using `backend/Dockerfile` and sets up health checking at `/health`.
4. Configure the following environment variables in Render:
   - `DATABASE_URL`: Your Supabase Postgres session-pooler connection string.
   - `MOSS_PROJECT_ID`: Your Moss Project ID.
   - `MOSS_PROJECT_KEY`: Your Moss Project Key.
   - `CORS_ALLOWED_ORIGINS`: Your deployed dashboard URL.

### 6.2 Deploying Dashboard to Vercel or Render
- **On Vercel:** Import `dashboard/` root, set `NEXT_PUBLIC_API_URL` to your Render backend URL, and supply `LIVEKIT_URL`, `LIVEKIT_API_KEY`, and `LIVEKIT_API_SECRET`.
- **On Render:** Deployed automatically via `render.yaml` with zero configuration.

---

## 7. Security, Offline RBAC & Data Integrity

- **Managed Postgres System of Record:** Database records are stored in managed Postgres (Supabase) encrypted at rest with AES-256. Dual-mode support enables seamless fallback to local SQLite in edge deployments.
- **Offline-First RBAC Tokens:** Role tokens are signed using HMAC-SHA256 and verified locally by the voice agent without network calls (`agent/src/role_cache.py`).
- **Append-Only Auditing:** Every agent decision and tool invocation is recorded with structured telemetry, available via the dashboard audit viewer.
- **Durable Sync Queue:** Outbound notes and mutations buffer durably in `_sync_queue.sqlite3` with exponential backoff, jitter, and idempotency protection against duplicate writes.

---

## 8. Verification & Test Suite

FieldLine maintains comprehensive test coverage across all components:

```powershell
# 1. Voice Agent Suite (88 tests)
cd agent
uv run ruff check src/ tests/
uv run pytest -v

# 2. Backend Suite (97 tests)
cd ..\backend
uv run ruff check .
uv run pytest -v

# 3. Dispatch Dashboard (Lint & Production Build)
cd ..\dashboard
npm run lint
npm run build
```

Every commit and pull request is automatically validated across 4 continuous integration pipelines in GitHub Actions (`agent-ci.yml`, `backend-ci.yml`, `dashboard-ci.yml`, `docker-build.yml`).

---

## 9. Comprehensive Documentation Index

- [docs/RUNBOOK.md](file:///c:/Users/Prabhav/Downloads/Fieldline/docs/RUNBOOK.md) — Complete operational runbook, scripted pitch beats, and troubleshooting matrix.
- [docs/CONNECTIVITY_MODEL.md](file:///c:/Users/Prabhav/Downloads/Fieldline/docs/CONNECTIVITY_MODEL.md) — 3-Tier connectivity specification and failover mechanics.
- [docs/EDGE_HARDWARE_REQUIREMENTS.md](file:///c:/Users/Prabhav/Downloads/Fieldline/docs/EDGE_HARDWARE_REQUIREMENTS.md) — Hardware, RAM, and model quantization specifications.
- [docs/REQUIREMENTS_TRACEABILITY.md](file:///c:/Users/Prabhav/Downloads/Fieldline/docs/REQUIREMENTS_TRACEABILITY.md) — Full requirements verification matrix.
- [agent/PROMPT_ENGINEERING.md](file:///c:/Users/Prabhav/Downloads/Fieldline/agent/PROMPT_ENGINEERING.md) — System prompt architecture and few-shot examples.