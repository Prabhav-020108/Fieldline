"""
Phase 6: audit logging for FieldLine's voice agent.

Every tool call (fault_history, safety_procedure, inventory_lookup,
dispatch_status, log_job_note) reports what the technician asked, what the
agent said back, and -- for safety_procedure -- the citation and
confidence score, to the FastAPI backend's audit log
(POST /companies/{id}/audit-log). A supervisor reviews this trail from the
dashboard's "Audit log" tab (see backend/main.py and
dashboard/app/companies/[companyId]/audit/page.tsx).

Three things shaped this file:

1. Never add latency to a voice response. Tools call
   log_tool_call_background(...) -- a plain, synchronous function that
   schedules the actual network call as a background asyncio task and
   returns immediately. Nothing in the tool files ever awaits this before
   returning an answer to the technician.

2. Never lose an entry just because the network is down. If the POST to
   the backend fails for any reason, the entry is appended to a small,
   durable JSON-lines buffer file on disk (one file per company, under
   agent/_audit_buffer/) instead of being dropped. When later flushed, the
   original local timestamp is replayed as the entry's created_at, so the
   audit trail reflects when the tool call actually happened -- not when
   it finally reached the backend.

3. Two independent ways to catch up once the backend is reachable again:
   - connectivity.py's on_reconnect hook -- the same mechanism
     moss_client.py already uses to hot-swap back to the cloud Moss index
     -- fires flush_all_buffers() the instant a real offline -> online
     transition is detected (e.g. the Wi-Fi-toggle demo).
   - A periodic background loop (start_periodic_flush(), started once
     from agent.py alongside connectivity.start()) retries
     flush_all_buffers() every 30 seconds regardless of the connectivity
     monitor's state. This covers the narrower case where only the
     FastAPI backend was briefly down or restarting (e.g. `uvicorn
     --reload` picking up a code change) while the technician's actual
     internet connection -- and therefore Moss and the cloud STT/LLM/TTS
     pipeline -- never dropped, so the on_reconnect hook never fires.

Deliberate design choice: a failed audit-log POST does NOT call
connectivity.mark_offline(). The audit log is supplementary telemetry, not
a core dependency like Moss or the STT/LLM/TTS pipeline -- if only the
FastAPI backend happens to be down while the technician's internet is
fine, we do not want that to push the whole voice pipeline into its
slower, local-model fallback path. Audit entries just buffer locally and
catch up later, through one of the two paths above.
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timezone

import httpx

from company_context import get_current_company
from connectivity import connectivity

logger = logging.getLogger("fieldline.audit_log")

BACKEND_URL = os.environ.get("FIELDLINE_BACKEND_URL", "http://localhost:8000")

# One buffer file per company (agent/_audit_buffer/<company_id>.jsonl), so
# a worker process serving two companies' calls concurrently never
# interleaves their entries in the same file. Lives next to agent/src/
# rather than inside it, mirroring how data/seed/ sits next to (not
# inside) agent/ -- see moss_client.py's SEED_DIR for the same pattern.
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
BUFFER_DIR = os.path.join(_THIS_DIR, "..", "_audit_buffer")

_flush_lock = asyncio.Lock()
_reconnect_hook_registered = False
_periodic_flush_task: asyncio.Task | None = None


def log_tool_call_background(
    tool_name: str,
    query_text: str,
    response_text: str,
    *,
    source_citation: str | None = None,
    confidence_score: float | None = None,
    below_confidence_floor: bool = False,
) -> None:
    """Call this as the last line of a tool, right before `return answer`:

        log_tool_call_background("fault_history", equipment_id, answer)
        return answer

    This is synchronous and returns immediately -- it schedules the actual
    logging as a background task rather than doing any I/O itself, so it
    never adds latency to the voice response.

    company_id is read here (synchronously, from company_context's
    ContextVar) rather than inside the background task, so the value
    reflects the company this call actually belonged to -- not whatever
    happens to be current by the time the background task gets scheduled.
    """
    company_id = get_current_company()
    asyncio.create_task(
        log_tool_call(
            company_id,
            tool_name,
            query_text,
            response_text,
            source_citation=source_citation,
            confidence_score=confidence_score,
            below_confidence_floor=below_confidence_floor,
        )
    )


async def log_tool_call(
    company_id: str,
    tool_name: str,
    query_text: str,
    response_text: str,
    *,
    source_citation: str | None = None,
    confidence_score: float | None = None,
    below_confidence_floor: bool = False,
) -> None:
    """Send one audit entry to the backend, or buffer it locally on
    failure. Safe to call directly (e.g. from tests); tools should
    normally go through log_tool_call_background() instead."""
    _ensure_reconnect_hook()

    entry = {
        "tool_name": tool_name,
        "query_text": query_text,
        "response_text": response_text,
        "source_citation": source_citation,
        "confidence_score": confidence_score,
        "below_confidence_floor": below_confidence_floor,
    }

    try:
        if connectivity.is_online:
            if await _post_entry(company_id, entry):
                return
            logger.warning(
                "audit-log backend unreachable for company %r -- buffering "
                "locally (this does not affect the voice pipeline's own "
                "online/offline state)",
                company_id,
            )

        entry["created_at_local"] = datetime.now(timezone.utc).isoformat()
        await asyncio.get_event_loop().run_in_executor(
            None, _append_to_buffer, company_id, entry
        )
    except Exception:
        # Audit logging must never take down a tool call. Worst case, one
        # entry is lost and we log why.
        logger.exception("audit log entry lost for company %r: %r", company_id, entry)


async def flush_all_buffers() -> None:
    """Push every company's buffered audit entries to the backend. See the
    module docstring for the two things that call this: connectivity's
    on_reconnect hook, and the periodic loop started by
    start_periodic_flush()."""
    async with _flush_lock:
        if not os.path.isdir(BUFFER_DIR):
            return
        for filename in os.listdir(BUFFER_DIR):
            if not filename.endswith(".jsonl"):
                continue
            company_id = filename[: -len(".jsonl")]
            await _flush_one_file(company_id, os.path.join(BUFFER_DIR, filename))


def start_periodic_flush(interval_seconds: float = 30.0) -> None:
    """Start a background loop that retries flush_all_buffers() every
    `interval_seconds`, independent of connectivity.py's online/offline
    state. Call this once, alongside connectivity.start(), in agent.py's
    entrypoint(). Safe to call more than once -- only starts one loop."""
    global _periodic_flush_task
    if _periodic_flush_task is None:
        _periodic_flush_task = asyncio.create_task(_periodic_flush_loop(interval_seconds))


async def _periodic_flush_loop(interval_seconds: float) -> None:
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            await flush_all_buffers()
        except Exception:
            logger.exception("periodic audit-log flush failed")


def _ensure_reconnect_hook() -> None:
    global _reconnect_hook_registered
    if not _reconnect_hook_registered:
        connectivity.on_reconnect(flush_all_buffers)
        _reconnect_hook_registered = True


async def _post_entry(company_id: str, entry: dict) -> bool:
    """Returns True on success, False on any failure -- never raises."""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.post(
                f"{BACKEND_URL}/companies/{company_id}/audit-log", json=entry
            )
            resp.raise_for_status()
        return True
    except Exception:
        return False


def _buffer_path(company_id: str) -> str:
    os.makedirs(BUFFER_DIR, exist_ok=True)
    return os.path.join(BUFFER_DIR, f"{company_id}.jsonl")


def _append_to_buffer(company_id: str, entry: dict) -> None:
    try:
        with open(_buffer_path(company_id), "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        logger.exception(
            "could not write audit entry to local buffer either -- entry is lost: %r",
            entry,
        )


async def _flush_one_file(company_id: str, path: str) -> None:
    try:
        with open(path, encoding="utf-8") as f:
            lines = [line for line in f.read().splitlines() if line.strip()]
    except OSError:
        logger.exception("could not read audit buffer %s", path)
        return

    if not lines:
        return

    remaining: list[str] = []
    sent = 0
    for line in lines:
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue  # drop an unparseable line rather than blocking the rest

        # Replay with the ORIGINAL local timestamp as created_at, so the
        # audit trail reflects when the tool call actually happened, not
        # whenever the backend finally became reachable again.
        local_ts = entry.pop("created_at_local", None)
        if local_ts:
            entry["created_at"] = local_ts

        if await _post_entry(company_id, entry):
            sent += 1
        else:
            remaining.append(line)

    try:
        if remaining:
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(remaining) + "\n")
        else:
            os.remove(path)
    except OSError:
        logger.exception("could not update audit buffer %s after flush", path)

    if sent:
        logger.info(
            "flushed %d buffered audit entries for company %r", sent, company_id
        )