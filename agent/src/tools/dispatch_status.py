import logging

from livekit.agents import RunContext, function_tool
from moss import QueryOptions

from audit_log import log_tool_call_background
from company_context import get_current_room_name
from connectivity import connectivity
from moss_client import get_index
from tracing import traced_stage

logger = logging.getLogger("fieldline.dispatch_status")


@function_tool()
async def dispatch_status(context: RunContext) -> str:
    """Report the current job queue and any dispatch reroutes for the site.

    Use this when the technician asks what's next, whether anything has
    changed with their schedule, or whether a job has been rerouted.
    """
    logger.info("dispatch_status lookup")

    client, index_name = await get_index()
    path = "online" if connectivity.is_online else "offline"

    with traced_stage(
        "retrieval", get_current_room_name(), path, tool="dispatch_status"
    ) as span:
        results = await client.query(
            index_name,
            "current job queue dispatch status and reroutes",
            QueryOptions(
                top_k=5,
                alpha=0.5,
                filter={"field": "type", "condition": {"$eq": "dispatch_status"}},
            ),
        )
        span.set_attribute("fieldline.result_count", len(results.docs))

    if not results.docs:
        answer = "I don't see any dispatch updates right now -- your queue looks unchanged."
    else:
        lines = [doc.text for doc in results.docs]
        answer = " ".join(lines)

    # dispatch_status takes no argument from the technician, so the audit
    # log's "query" column just records that a status check happened.
    log_tool_call_background(
        "dispatch_status", "current job queue and dispatch status", answer
    )

    return answer