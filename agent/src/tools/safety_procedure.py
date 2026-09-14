import logging
import os

from livekit.agents import RunContext, function_tool
from moss import QueryOptions

from audit_log import log_tool_call_background
from moss_client import get_index

logger = logging.getLogger("fieldline.safety_procedure")

# Below this score, do not hand the technician a guess -- send them to a
# supervisor instead.
#
# Phase 6: this is now tunable via SAFETY_CONFIDENCE_FLOOR in .env.local
# instead of a hardcoded constant (default stays 0.35, matching Phases
# 2-5), and every safety_procedure call logs its score -- and whether it
# tripped this floor -- to the audit log below, so a supervisor can review
# exactly when the agent did and didn't trust its own answer. See
# audit_log.py and the dashboard's "Audit log" tab.
CONFIDENCE_FLOOR = float(os.environ.get("SAFETY_CONFIDENCE_FLOOR", "0.35"))


@function_tool()
async def safety_procedure(context: RunContext, topic: str) -> str:
    """Look up a safety or lockout procedure and read it back with its citation.

    This is a safety-critical tool: never paraphrase, summarize, or reorder
    the steps returned by this tool. Read the returned text back to the
    technician close to verbatim, in order, and always state the source
    manual and section at the end.

    Args:
        topic: What the technician wants the safety procedure for, in their
            own words, e.g. "panel B lockout" or "lockout procedure for panel A".
    """
    logger.info("safety_procedure lookup for %r", topic)

    client, index_name = await get_index()
    results = await client.query(
        index_name,
        topic,
        QueryOptions(
            top_k=1,
            alpha=0.25,  # keyword-weighted: exact wording matters for safety text
            filter={"field": "type", "condition": {"$eq": "safety_manual"}},
        ),
    )

    if not results.docs:
        answer = (
            "I don't have an indexed procedure that matches that. Don't proceed "
            "from memory -- confirm the lockout steps with your supervisor or the "
            "printed manual before touching the panel."
        )
        log_tool_call_background(
            "safety_procedure",
            topic,
            answer,
            confidence_score=None,
            below_confidence_floor=True,
        )
        return answer

    doc = results.docs[0]
    if doc.score < CONFIDENCE_FLOOR:
        answer = (
            "I'm not confident enough in what I found to read it back as the "
            "correct procedure. Please confirm the exact steps with your "
            "supervisor before proceeding."
        )
        log_tool_call_background(
            "safety_procedure",
            topic,
            answer,
            confidence_score=doc.score,
            below_confidence_floor=True,
        )
        return answer

    metadata = doc.metadata or {}
    manual = metadata.get("source_manual", "the site safety manual")
    section = metadata.get("section")
    citation = f"{manual}, Section {section}" if section else manual

    answer = f"{doc.text}\n\nSource: {citation}. Read this back exactly as written."

    log_tool_call_background(
        "safety_procedure",
        topic,
        answer,
        source_citation=citation,
        confidence_score=doc.score,
        below_confidence_floor=False,
    )

    return answer