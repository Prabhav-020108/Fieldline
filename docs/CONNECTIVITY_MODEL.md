# FieldLine Connectivity Model

FieldLine's voice assistant is engineered specifically for real-world field operations where internet connectivity is frequently intermittent, degraded, or entirely absent. This document specifies the three connectivity tiers, how the architecture adapts, and what remains fully functional in each mode.

## The Three Tiers

| Tier | What's actually happening | What still works |
|---|---|---|
| **Tier 1: Full Connectivity (Cloud)** | Phone ↔ LiveKit Cloud ↔ Agent ↔ Backend/Moss Cloud all reachable | **Everything**: High-speed cloud STT/LLM/TTS models (Groq Whisper, GPT-OSS, Fish Audio), live bi-directional sync, real-time dashboard updates across all users. |
| **Tier 2: Degraded Connectivity (Hybrid)** | Phone ↔ LiveKit Cloud stays up; Agent ↔ Backend/Moss Cloud drops | **Voice remains 100% live**: Retrieval answers immediately from the in-memory Moss session hydrated at shift start; job notes and audit entries buffer durably via `sync_queue.py` (SQLite with exponential backoff + jitter) and drain automatically upon reconnect. Zero spoken interruptions, single debounced advisory announcement. |
| **Tier 3: Edge Deployment (Zero Internet)** | Phone ↔ Local Wi-Fi / Hotspot ↔ On-Site Edge Appliance (Self-Hosted LiveKit Server + Local Agent Stack + SQLite Backend) | **Complete local autonomy with zero external WAN**: Speech-to-text via CPU `faster-whisper`, local LLM reasoning via `Ollama` (`llama3.2:3b`), local TTS via `Piper`, local session search, and SQLite storage. WebRTC connects peer-to-peer over local LAN/Hotspot. When internet returns, the sync queue flushes all buffered records upstream. |

---

## Edge Deployment Architecture (Tier 3)

When operating in remote facilities, deep basements, mine sites, or during disaster recovery where cellular and WAN backhauls are dead:

```
  ┌─────────────────────────────────────────────────────────────┐
  │         ON-SITE EDGE APPLIANCE (Laptop / Rugged Box)        │
  │                                                             │
  │  ┌──────────────────┐          ┌─────────────────────────┐  │
  │  │  LiveKit Server  │          │  FastAPI Backend        │  │
  │  │  (Self-Hosted)   │          │  (SQLite Database)      │  │
  │  │  Port: 7880      │          │  Port: 8000             │  │
  │  └────────┬─────────┘          └────────────┬────────────┘  │
  │           │                                 │               │
  │  ┌────────┴─────────────────────────────────┴────────────┐  │
  │  │             FieldLine Autonomous Voice Agent           │  │
  │  │  ┌────────────────┐ ┌───────────────┐ ┌────────────┐  │  │
  │  │  │ faster-whisper │ │ Ollama (3B)   │ │ Piper TTS  │  │  │
  │  │  │ (Local CPU)    │ │ (Local LLM)   │ │ (Local ONNX│  │  │
  │  │  └────────────────┘ └───────────────┘ └────────────┘  │  │
  │  │  ┌──────────────────────────────────────────────────┐  │  │
  │  │  │ Local Session Index & SQLite Outbound Sync Queue │  │  │
  │  │  └──────────────────────────────────────────────────┘  │  │
  │  └───────────────────────────────────────────────────────┘  │
  │                                                             │
  │  📡 Local Wi-Fi Access Point / Mobile Hotspot               │
  └──────────────────────────────┬──────────────────────────────┘
                                 │ Local WebRTC (NO WAN Needed)
                                 │
                        ┌────────┴────────┐
                        │ Technician's    │
                        │ Smartphone / PWA│
                        └─────────────────┘
```

### Running the Edge Stack

**Option A: One-Command Docker Compose**
```bash
docker compose -f docker-compose.edge.yml up
```

**Option B: Native Process Execution**
1. **LiveKit Server**: `livekit-server --config livekit-edge.yaml --dev --bind 0.0.0.0`
2. **Local LLM**: `ollama run llama3.2:3b`
3. **Local TTS**: `cd agent && uv run python src/local_tts_server.py`
4. **Local Backend**: `cd backend && uv run uvicorn main:app --host 0.0.0.0 --port 8000`
5. **Edge Agent**: `cd agent && set FIELDLINE_EDGE_MODE=1 && uv run python src/agent.py dev`

---

## Technical Guarantees Across Tiers

1. **Zero Data Loss**: Every write action (audit logs, note creation) uses `sync_queue.py` backed by SQLite on the host filesystem. Even if power cuts or network drops, writes survive and replay with idempotency keys upon reconnection.
2. **Deterministic Safety Procedures**: Safety-critical lockout and procedure queries enforce a strict `SAFETY_CONFIDENCE_FLOOR` (0.35) and read verbatim manual citations. If a match is not confident, the agent explicitly defers rather than hallucinating.
3. **Seamless Transition & Debounce**: Connectivity transitions between online and offline trigger debounced advisory messages (`announce_cooldown_s = 15.0`) to avoid duplicate announcements during intermittent flapping.
