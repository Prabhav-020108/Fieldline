# FieldLine

**FieldLine** is a hands-free voice dispatch copilot for field service
technicians — electrical maintenance, HVAC, elevator AMC, and telecom tower
crews — built for the YC Fall 2026 × Moss Zero Latency Builder Sprint
hackathon (HiDevs, Bengaluru).

The core bet: retrieval has to work identically whether the technician's
device is online or completely offline, because losing signal on a job site
is the norm, not the edge case. FieldLine's differentiator is **Moss's
offline-first `SessionIndex`** — a local, in-process semantic index that
keeps answering with no network, then hot-swaps back to the cloud the
instant reconnection happens. The flagship demo beat is toggling Wi-Fi off
mid-call and watching the agent keep answering instantly.

## What it does

A technician talks hands-free to a LiveKit voice agent through a headset.
The agent has five tools:

| Tool | What it does |
|---|---|
| `fault_history` | Job and fault history for a piece of equipment |
| `safety_procedure` | Retrieves and reads back the *exact* indexed safety/lockout passage, with a citation, never paraphrased. Below a tunable confidence floor, it defers to a supervisor instead of guessing |
| `inventory_lookup` | Where a spare part is stored and how many are in stock |
| `dispatch_status` | Current job queue and any dispatch reroutes |
| `log_job_note` | Logs a voice-dictated completion note, written back into the index |

Every one of those five tool calls is also recorded in a company-scoped
**audit log** (Phase 6), reviewable from the dashboard.

## Architecture at a glance

┌───────────────────────────┐

Technician ───▶ │ LiveKit Agent (agent/) │
(voice, headset) │ │
│ connectivity.py ──────────┼──▶ online: Groq STT/LLM +
│ │ │ LiveKit Inference TTS
│ └──── offline ────────┼──▶ faster-whisper + Ollama +
│ │ Piper (all local)
│ moss_client.py ───────────┼──▶ per-company Moss
│ (5 tools, audit_log.py) │ SessionIndex (cloud +
└────────────┬───────────────┘ local keyword fallback)
│ HTTP (jobs, safety procs,
│ inventory, audit log)
┌────────────▼───────────────┐
│ FastAPI backend │
│ (backend/) │ ┌──────────────┐
│ SQLite: companies, jobs, │◀────▶│ Next.js │
│ inventory, safety procs, │ │ dashboard │
│ audit log entries │ │ (dashboard/) │
└────────────┬───────────────┘ └──────────────┘
│ sync on every write
▼
Moss cloud index
(one per company)


Every company gets its **own** Moss index and its own local session, so two
companies' job history, safety procedures, and inventory can never mix —
even though the exact same agent code and the exact same five tools serve
all of them. See `agent/src/company_context.py` for how a call is routed to
the right company from its LiveKit room name.

## Repo structure

fieldline/
├── agent/ # LiveKit Agents (Python) voice agent
│ ├── src/
│ │ ├── agent.py # entrypoint, tool registration, greeting
│ │ ├── company_context.py # per-call company routing (ContextVar)
│ │ ├── moss_client.py # per-company Moss router + offline session
│ │ ├── connectivity.py # online/offline detection
│ │ ├── local_pipeline.py # faster-whisper + Ollama + Piper wiring
│ │ ├── audit_log.py # Phase 6: audit logging, offline-buffered
│ │ ├── local_tts_server.py # standalone Piper TTS server (run separately)
│ │ └── tools/
│ │ ├── fault_history.py
│ │ ├── safety_procedure.py
│ │ ├── inventory_lookup.py
│ │ ├── dispatch_status.py
│ │ └── log_job_note.py
│ ├── tests/
│ │ ├── test_agent.py
│ │ ├── test_audit_log.py # Phase 6
│ │ └── test_safety_procedure_confidence.py # Phase 6
│ ├── models/ # Piper voice model files
│ ├── .env.example
│ └── pyproject.toml
├── backend/ # FastAPI dispatch backend
│ ├── main.py # all REST endpoints, incl. audit log
│ ├── models.py # SQLAlchemy tables
│ ├── seed_db.py # seeds two demo companies
│ ├── moss_sync.py # DB rows -> Moss cloud index, per company
│ ├── document_builder.py # row -> Moss document shape (shared)
│ └── .env.example
├── dashboard/ # Next.js multi-tenant dispatch console
│ └── app/
│ ├── page.tsx # company list / create company
│ ├── api/livekit-token/ # mints LiveKit tokens w/ explicit dispatch
│ └── companies/[companyId]/
│ ├── page.tsx # Overview
│ ├── jobs/ # Job CRUD + reroute
│ ├── safety/ # Safety procedure CRUD
│ ├── audit/ # Phase 6: audit log viewer
│ ├── inventory/ # Inventory CRUD
│ └── call/ # Talk-to-agent voice UI
├── data/seed/ # Phase 2 fallback seed JSON (site-demo only)
└── README.md


## Prerequisites

- **Windows + PowerShell** (this README assumes that; adjust shell syntax if
  you're on macOS/Linux)
- Python 3.10–3.14 with [`uv`](https://docs.astral.sh/uv/) installed
- Node.js 18+ with `npm`
- A [LiveKit Cloud](https://cloud.livekit.io/) project (free tier)
- A [Moss](https://moss.dev) project (Project ID + Project Key)
- A [Groq](https://console.groq.com/) API key (free tier)
- [Ollama](https://ollama.com/) installed locally, with `llama3.2:3b` pulled
  (`ollama pull llama3.2:3b`) — used for the fully offline LLM fallback
- A Piper voice model downloaded to `agent/models/` — used for the fully
  offline TTS fallback
- Arize Phoenix (installed via `uv sync`, no separate account needed) for
  LLM observability

## Setup

### 1. Backend (FastAPI)

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install fastapi uvicorn sqlalchemy httpx python-dotenv moss python-jose[cryptography] bcrypt slowapi python-multipart
copy .env.example .env
# Edit backend\.env and fill in MOSS_PROJECT_ID / MOSS_PROJECT_KEY
python seed_db.py
# Also generate a real JWT secret and add it to backend/.env as
# FIELDLINE_JWT_SECRET=<value> before anything beyond local testing:
python -c "import secrets; print(secrets.token_urlsafe(48))"
python -m uvicorn main:app --reload --port 8000
```

Leave this running in its own PowerShell window. Visit
`http://localhost:8000/docs` to confirm it's up.

### 2. Agent (LiveKit Agents)

In a **second** PowerShell window:

```powershell
cd agent
uv sync
copy .env.example .env.local
# Edit agent\.env.local and fill in:
#   LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET  (from LiveKit Cloud)
#   GROQ_API_KEY
#   MOSS_PROJECT_ID, MOSS_PROJECT_KEY                 (same as backend)
uv run python src/agent.py dev
```

Before your first fully-offline test, also run once **while online**, so the
local STT model is cached:

```powershell
uv run python -c "from local_pipeline import warm_up_local_stt; warm_up_local_stt()"
```

For the fully offline TTS path, run `agent/src/local_tts_server.py` as its
own process in a **third** window before testing offline mode:

```powershell
cd agent
uv run python src/local_tts_server.py
```

### 3. Dashboard (Next.js)

In a **fourth** PowerShell window:

```powershell
cd dashboard
npm install
copy .env.example .env.local   # if you don't have one yet, create it manually
# Edit dashboard\.env.local:
#   NEXT_PUBLIC_API_URL=http://localhost:8000
#   NEXT_PUBLIC_LIVEKIT_URL=<same as agent's LIVEKIT_URL>
#   LIVEKIT_API_KEY=<same as agent's>
#   LIVEKIT_API_SECRET=<same as agent's>
npm run dev
```

Open `http://localhost:3000`.

## Tunable settings

| Variable | Where | Default | What it does |
|---|---|---|---|
| `SAFETY_CONFIDENCE_FLOOR` | `agent/.env.local` | `0.35` | Below this Moss retrieval score, `safety_procedure` refuses to guess and tells the technician to confirm with a supervisor instead. Raise it to make the agent more conservative. |
| `WHISPER_MODEL_SIZE` | `agent/.env.local` | `small` | faster-whisper model size for the offline STT fallback. Use `tiny` on slower machines. |
| `FIELDLINE_BACKEND_URL` | `agent/.env.local` | `http://localhost:8000` | Where the agent reads company data and posts audit-log entries. |

## Testing

```powershell
cd agent
uv run pytest -v
```

Covers: agent greeting behavior, safety-procedure confidence-floor logic
(including the Phase 6 tunable threshold), and audit-log buffering/flush
behavior when the backend is briefly unreachable.

## Safety & audit trail (Phase 6)

- `safety_procedure`'s confidence floor is tunable via
  `SAFETY_CONFIDENCE_FLOOR` in `agent/.env.local` — no code change needed to
  make the agent more or less cautious.
- Every tool call (all five tools) writes an entry to a per-company audit
  log: what the technician asked, what the agent said, and — for
  `safety_procedure` — the Moss retrieval confidence score and whether it
  tripped the confidence floor.
- Audit logging never adds latency to a voice response (it's fire-and-forget
  in the background) and never fails a tool call — if the FastAPI backend is
  briefly unreachable, entries buffer to disk under `agent/_audit_buffer/`
  and are automatically replayed with their original timestamp once the
  backend is reachable again.
- View the trail per company at **Dashboard → \[Company\] → Audit log**.

## Offline-first demo

1. Start a call from the dashboard's **Talk to agent** tab.
2. Ask a question (e.g. "What's the history on unit twelve?").
3. Turn off Wi-Fi.
4. Ask another question — the agent keeps answering, now via the local
   Moss `SessionIndex` and the local STT/LLM/TTS pipeline.
5. Turn Wi-Fi back on — the agent hot-swaps back to the cloud pipeline and
   pushes anything logged offline (job notes, buffered audit entries) back
   to the cloud, with zero restart.

## Observability, security & evaluation (Phase 7)

**LLM observability.** Every pipeline stage (STT, LLM, TTS, Moss retrieval)
is traced via OpenTelemetry into a locally self-hosted [Arize
Phoenix](https://phoenix.arize.com/) instance -- correlation id, online/
offline path, latency, and (for LLM stages) token usage. Run it alongside
the agent:

```powershell
cd agent
uv run python -m phoenix.server.main serve
```

Open `http://localhost:6006` to watch traces arrive live. Any span that
busts its path's latency budget (1000ms online / 2500ms offline) gets an
explicit `latency_threshold_exceeded` event, filterable in Phoenix.

**Prompt engineering.** `agent/PROMPT_ENGINEERING.md` documents the CRISPE
structure, negative constraints, and few-shot examples behind
`agent/src/agent.py`'s system prompt.

**API security.** The backend now requires a login for every write
(create/update/delete). Demo accounts (see `backend/seed_db.py`, password
`FieldLine123!` for all):

| Company | Username | Role |
|---|---|---|
| site-demo | `tech.demo` | technician |
| site-demo | `supervisor.demo` | supervisor |
| site-demo | `dispatcher.demo` | dispatcher |
| acme-elevator | `tech.acme` | technician |
| acme-elevator | `supervisor.acme` | supervisor |
| acme-elevator | `dispatcher.acme` | dispatcher |

Roles: **technician** (read + log notes), **supervisor** (+ edit safety
procedures), **dispatcher** (+ reroute jobs, delete jobs/inventory).
Requests are also rate-limited (`slowapi`) and Pydantic request models
enforce explicit length/pattern constraints. Set a real
`FIELDLINE_JWT_SECRET` in `backend/.env` before deploying anywhere:

```powershell
cd backend
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

**Requirements traceability.** See `docs/REQUIREMENTS_TRACEABILITY.md` for
the full FR/NFR matrix mapping every requirement to its implementing
component and verifying phase.

**Offline evaluation.** `agent/eval/run_ragas_eval.py` runs Ragas
(faithfulness + context precision) against a fixed golden set, as a
standalone batch script -- never inline with a live call:

```powershell
cd agent
uv sync --group eval
uv run --group eval python eval/run_ragas_eval.py
```