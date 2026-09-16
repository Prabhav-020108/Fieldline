import logging
import uuid
from datetime import datetime, timezone

from livekit.agents import RunContext, function_tool
from moss import DocumentInfo, MutationOptions

from audit_log import log_tool_call_background
from company_context import get_current_room_name
from connectivity import connectivity
from moss_client import get_index
from tracing import prompt_hash, traced_stage

logger = logging.getLogger("fieldline.log_job_note")


@function_tool()
async def log_job_note(context: RunContext, equipment_id: str, note: str) -> str:
    """Log a voice-dictated note against a job, writing it back into the
    index so it shows up in future fault-history lookups.

    Args:
        equipment_id: The equipment the note is about, e.g. "unit-12".
        note: The note content, in the technician's own words.
    """
    logger.info("log_job_note for %s: %r", equipment_id, note)

    client, index_name = await get_index()
    doc_id = f"note-{equipment_id}-{uuid.uuid4().hex[:8]}"
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    doc = DocumentInfo(
        id=doc_id,
        text=f"{equipment_id} - field note logged {timestamp}: {note}",
        metadata={"type": "job_history", "equipment": equipment_id, "status": "note"},
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

    answer = f"Got it, I've logged that note against {equipment_id}."

    log_tool_call_background("log_job_note", f"{equipment_id}: {note}", answer)

    return answer