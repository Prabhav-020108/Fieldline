# FieldLine Requirements Traceability Matrix

Mentor feedback on the Sept 13 architecture/PRD submission flagged
requirements traceability as a gap. This matrix IDs every functional and
non-functional requirement, its acceptance criteria, the component that
implements it, and the phase it was verified in. Paste this into
Architecture Copilot's PRD chat as well, so the exported PRD reflects the
same rigor as the repo.

| ID | Requirement | Acceptance criteria | Component | Verified by |
|---|---|---|---|---|
| FR-01 | Fault/job history lookup | Given a known equipment ID, returns matching job_history docs with correct status | `fault_history` tool | Phase 3 |
| FR-02 | Safety procedure retrieval with citation | For confidence ≥ 0.35 (alpha 0.25), reads back the passage verbatim with manual + section | `safety_procedure` tool | Phase 2 / 6 |
| FR-03 | Low-confidence safety fallback | Below 0.35 confidence, states uncertainty and refers to supervisor | `safety_procedure` threshold | Phase 6 |
| FR-04 | Inventory/part lookup | Given a part number, returns location and quantity | `inventory_lookup` tool | Phase 3 |
| FR-05 | Dispatch reroute awareness | Dashboard reroute reflected on the agent's next `dispatch_status` call | Dashboard → backend → Moss sync | Phase 5 |
| FR-06 | Voice-logged job notes | Dictated note is indexed and retrievable on the next relevant query | `log_job_note` tool | Phase 3 |
| FR-07 | Offline operation | FR-01–FR-06 continue to function with the network disabled | Connectivity monitor + local model stack | Phase 4 |
| FR-08 | Zero-downtime resync | Offline-logged data appears centrally within one polling interval, no restart | Local session hydration + Moss sync | Phase 4 |
| NFR-01 | Retrieval latency | Moss query time stays low enough not to be the bottleneck in either path | Moss local session + cloud index | Phase 9 |
| NFR-02 | Voice-to-voice latency, online | ≤ ~1s for a short answer | Cloud STT/LLM/TTS | Phase 9 |
| NFR-03 | Voice-to-voice latency, offline | ≤ ~2.5s for a short answer | Local STT/LLM/TTS | Phase 9 |
| NFR-04 | Observability | Every stage traces latency, path, and (for LLM stages) token usage, correlated per call | `agent/src/tracing.py` + Phoenix | Phase 7 |
| NFR-05 | API authentication | Write endpoints require a valid JWT | `backend/auth.py` | Phase 7 |
| NFR-06 | Rate limiting | Excessive requests per IP are rejected within a rolling window | `slowapi` on login + write endpoints | Phase 7 |
| NFR-07 | Transit encryption | All traffic served over TLS | Vercel / Render edge (platform-level, not hand-built) | Phase 7 (documented) |
| NFR-08 | Offline-latency alerting | Any span exceeding its path's latency budget is flagged as an event, visible in Phoenix | `tracing.py`'s `_check_latency_budget()` | Phase 7 |
| NFR-09 | Retrieval/answer quality | Faithfulness and context-precision scores on a fixed golden set, checked offline, never inline with a live call | `agent/eval/run_ragas_eval.py` + Ragas | Phase 7 |
| NFR-10 | Role-based access control | Technicians can read/log notes; only supervisors/dispatchers can edit safety procedures or delete jobs/inventory; only dispatchers can reroute | `auth.require_role()` in `backend/main.py` | Phase 7 |
| NFR-11 | Encryption at rest | SQLite today; documented roadmap item to move to a managed Postgres provider with encryption at rest by default before any real deployment | *(scoped, not yet implemented)* | Roadmap |
| NFR-21 | Tenant isolation on writes | A valid token for one company cannot mutate another company's data | `auth.require_same_company()` | Phase 7 |

## Scoped, not implemented this phase (documented honestly rather than rushed)

- **NFR-07 (TLS):** handled automatically by Vercel/Render at the edge once deployed — nothing to hand-build, but was previously undocumented rather than unimplemented.
- **NFR-11 (encryption at rest):** SQLite has no built-in encryption at rest. The stated plan is to migrate to a managed Postgres provider (e.g. Supabase, which encrypts at rest by default) before any real-world pilot — a scoped roadmap item, not a rushed SQLCipher change days before the deadline.
- **Agent → backend audit-log authentication:** intentionally left open (see `backend/main.py`'s module docstring) since it's a machine-to-machine call from the trusted agent process, not a browser action. A static service credential is the natural next step.

## Phase 8 additions

| ID | Requirement | Acceptance criteria | Component | Verified by |
|---|---|---|---|---|
| NFR-11 | Encryption at rest | Postgres data encrypted at rest by the managed provider, AES-256, on by default | Supabase | Phase 8a |
| NFR-12 | Schema migrations | Every schema change ships as an Alembic revision; `alembic upgrade head` is idempotent | `backend/migrations/` | Phase 8a |
| NFR-13 | Secrets management | Startup fails immediately if a required secret is missing; no secret value is hardcoded or defaulted in production | `settings.py` (both services) | Phase 8b |
| NFR-14 | Offline RBAC | A role check for a gated action never requires a network call; an invalid/expired/tampered token is treated as least-privilege | `agent/src/role_cache.py` | Phase 8c |
| NFR-15 | Sync protocol | A failed sync attempt retries with exponential backoff and jitter; a repeated idempotency key is never applied twice | `agent/src/sync_queue.py` | Phase 8d |
| NFR-16 | Edge hardware requirements | Min/recommended RAM, quantization, and acceleration path stated per offline-path component | `docs/EDGE_HARDWARE_REQUIREMENTS.md` | Phase 8e |
| NFR-17 | Connectivity-state awareness | The agent states an online/offline transition exactly once, before answering the technician's next question | `connectivity.py`'s `on_disconnect`/`on_reconnect` + `agent.py` | Phase 8f |

## Phase 9 additions

| ID | Requirement | Acceptance criteria | Component | Verified by |
|---|---|---|---|---|
| NFR-18 | Backend API test coverage | Every endpoint group (auth, companies, jobs, inventory, safety procedures, audit log, export) has automated tests for success, validation errors, role denials and cross-company isolation; the suite runs on a throwaway SQLite database, never real data | `backend/tests/` (91 tests) | Phase 9a |
| NFR-19 | Agent behavior tests incl. offline path | All five tools, company routing, offline write queueing and local search are tested with Moss and the backend faked; each read tool is tested identically online and offline; the `log_job_note` role gate is tested with the network off | `agent/tests/` | Phase 9b |
| NFR-20 | Continuous integration | Lint and tests run automatically on every push and pull request to `main` for the agent, backend (including `alembic upgrade head` on Postgres 16) and dashboard (lint and build); a red check blocks merging | `.github/workflows/` | Phase 9c |