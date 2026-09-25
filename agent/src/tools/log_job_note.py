import logging
import uuid
from datetime import datetime, timezone

from livekit.agents import RunContext, function_tool
from moss import DocumentInfo, MutationOptions

from audit_log import log_tool_call_background
from company_context import get_current_role, get_current_room_name
from connectivity import connectivity
from moss_client import get_index
from tracing import prompt_hash, traced_stage

logger = logging.getLogger("fieldline.log_job_note")

# Phase 8c: only these roles may close out a job via voice. A technician
# can still log a note against a job -- they just can't be the one who
# marks it resolved. This check runs entirely off the locally-verified
# role in company_context (see role_cache.py) -- no network call, so it
# enforces identically online or fully offline.
ROLES_THAT_CAN_RESOLVE = {"supervisor", "dispatcher"}


@function_tool()
async def log_job_note(
    context: RunContext, equipment_id: str, note: str, mark_resolved: bool = False
) -> str:
    """Log a voice-dictated note against a job, writing it back into the
    index so it shows up in future fault-history lookups.

    Args:
        equipment_id: The equipment the note is about, e.g. "unit-12".
        note: The note content, in the technician's own words.
        mark_resolved: True if the technician says this note closes out
            the job (e.g. "mark it resolved", "that's done"). Closing a
            job out loud requires a supervisor or dispatcher role -- a
            technician's note is still logged either way, just left open.
    """
    logger.info("log_job_note for %s: %r (mark_resolved=%s)", equipment_id, note, mark_resolved)

    role = get_current_role()
    can_resolve = role in ROLES_THAT_CAN_RESOLVE
    effective_status = "closed" if (mark_resolved and can_resolve) else "open"

    client, index_name = await get_index()
    doc_id = f"note-{equipment_id}-{uuid.uuid4().hex[:8]}"
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    doc = DocumentInfo(
        id=doc_id,
        text=f"{equipment_id} - field note logged {timestamp}: {note}",
        metadata={"type": "job_history", "equipment": equipment_id, "status": effective_status},
    )

    path = "online" if connectivity.is_online else "offline"
    with traced_stage(
        "index_write",
        get_current_room_name(),
        path,
        tool="log_job_note",
        note_hash=prompt_hash(note),
    ):
        await client.add_docs(index_name, [doc], MutationOptions(upsert=True))

    if mark_resolved and not can_resolve:
        answer = (
            f"Got it, I've logged that note against {equipment_id}. Closing out a "
            "job needs a supervisor or dispatcher, so I've logged this as still open."
        )
    elif mark_resolved:
        answer = f"Got it, I've logged that note and marked {equipment_id} resolved."
    else:
        answer = f"Got it, I've logged that note against {equipment_id}."

    log_tool_call_background("log_job_note", f"{equipment_id}: {note}", answer)

    return answer
