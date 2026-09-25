"""
Phase 6 (original): audit logging for FieldLine's voice agent -- what a
technician asked, what the agent said back, and (for safety_procedure)
the citation and confidence score, sent to the FastAPI backend's audit
log.

Phase 8d update: buffering now goes through sync_queue.py's shared,
durable retry queue instead of this file's own per-company JSONL files --
see sync_queue.py's module docstring for the full design. Every tool call
still calls log_tool_call_background(...) exactly as before; nothing in
tools/*.py changed for this update.

Never adds latency to a voice response -- log_tool_call_background()
schedules the real work as a background task and returns immediately.
Never fails a tool call -- every exception here is caught and logged, not
raised.
"""

import asyncio
import logging
from datetime import datetime, timezone

import httpx

import sync_queue
from company_context import get_current_company
from connectivity import connectivity
from settings import settings

logger = logging.getLogger("fieldline.audit_log")


def log_tool_call_background(
    tool_name: str,
    query_text: str,
    response_text: str,
    *,
    source_citation: str | None = None,
    confidence_score: float | None = None,
    below_confidence_floor: bool = False,
) -> None:
    """Call this as the last line of a tool, right before `return answer`.
    Synchronous and returns immediately. company_id is read here
    (synchronously) so the entry reflects the company this call actually
    belonged to -- not whatever happens to be current by the time the
    background task gets scheduled."""
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
    """Send one audit entry to the backend now if we can; otherwise queue
    it via sync_queue for retry. Safe to call directly (e.g. from
    tests)."""
    entry = {
        "tool_name": tool_name,
        "query_text": query_text,
        "response_text": response_text,
        "source_citation": source_citation,
        "confidence_score": confidence_score,
        "below_confidence_floor": below_confidence_floor,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    if connectivity.is_online:
        try:
            if await _post_entry(company_id, entry):
                connectivity.mark_online()
                return
            logger.warning(
                "audit-log backend unreachable for company %r -- queuing for "
                "retry and marking offline",
                company_id,
            )
            connectivity.mark_offline()
        except Exception:
            logger.exception("audit log POST raised unexpectedly for company %r", company_id)
            connectivity.mark_offline()

    await sync_queue.enqueue(
        op_type="audit_log_entry",
        company_id=company_id,
        payload=entry,
        idempotency_key=f"audit-{company_id}-{entry['created_at']}-{tool_name}",
    )


async def _post_entry(company_id: str, entry: dict) -> bool:
    """Returns True on success, False on any failure -- never raises."""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.post(
                f"{settings.fieldline_backend_url}/companies/{company_id}/audit-log", json=entry
            )
            resp.raise_for_status()
        return True
    except Exception:
        return False


async def _sync_queue_handler(company_id: str, payload: dict) -> bool:
    """Registered with sync_queue below -- replays one queued audit
    entry."""
    return await _post_entry(company_id, payload)


sync_queue.register_handler("audit_log_entry", _sync_queue_handler)
