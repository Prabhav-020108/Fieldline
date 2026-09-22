# FieldLine Connectivity Model

FieldLine's voice assistant is designed for real-world field operations where internet connectivity is frequently intermittent or degraded. This document specifies the three connectivity tiers, what actually occurs in each tier, and what functionality remains operational.

## The Three Tiers

| Tier | What's actually happening | What still works |
|---|---|---|
| **Full connectivity** | Phone ↔ LiveKit Cloud ↔ agent ↔ backend/Moss Cloud all reachable | Everything: cloud STT/LLM/TTS models, live bi-directional sync, instant dashboard reflection. |
| **Degraded connectivity** | Phone ↔ LiveKit Cloud stays up; agent ↔ backend/Moss Cloud drops | Retrieval keeps answering from the local in-memory Moss session hydrated at shift start; job notes and audit entries queue durably via `sync_queue.py` and replay on reconnect. This is real today, verified by `test_moss_client.py` and `test_sync_queue.py`. Voice itself remains live. |
| **Total signal loss** | Phone has no connectivity at all | Voice cannot function — no cloud-hosted agent can be reached by a phone with zero signal, regardless of which models sit behind it. Stated as an explicit, scoped limitation, with a self-hosted edge deployment (the existing Ollama/Piper/faster-whisper stack, relocated to site hardware) as the stated future path. |

## Why This Distinction Matters

1. **Honest Architecture**: A smartphone operating in a zero-connectivity basement or Faraday cage cannot transmit audio packets over cellular/Wi-Fi to LiveKit Cloud. Claiming that a cloud-hosted voice agent works when the phone has airplane mode enabled is technically impossible.
2. **Degraded Connectivity is the Real Problem**: In practice, field connectivity often breaks between cloud microservices or between the field worker and enterprise servers while the worker maintains a basic WebRTC audio channel. FieldLine's client-side in-memory index, local keyword search fallback (`_LocalSession`), and SQLite-backed outbound queue (`sync_queue.py`) guarantee zero data loss and immediate local answers during dispatch server or Moss outages.
3. **Future Edge Deployment**: The local model stack (`faster-whisper`, `Ollama` with `llama3.2:3b`, and `Piper` TTS) implemented in `local_pipeline.py` is fully functional on local workstations or dedicated on-premise hardware (e.g. edge gateways in remote plants). When deployed on an on-premise edge appliance on a local LAN, the system can provide voice services even during an external ISP blackout.
