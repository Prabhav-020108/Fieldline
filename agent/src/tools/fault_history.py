import logging

from livekit.agents import RunContext, function_tool
from moss import QueryOptions

from audit_log import log_tool_call_background
from company_context import get_current_room_name
from connectivity import connectivity
from moss_client import get_index
from tracing import prompt_hash, traced_stage

logger = logging.getLogger("fieldline.fault_history")


@function_tool()
async def fault_history(context: RunContext, equipment_id: str) -> str:
    """Look up job and fault history for a piece of equipment.

    Use this whenever the technician asks what happened with a unit before,
    whether an issue is recurring, or what the last resolution was.

    Args:
        equipment_id: The equipment identifier the technician mentioned,
            e.g. "unit-12" or "unit 12".
    """
    logger.info("fault_history lookup for %s", equipment_id)

    client, index_name = await get_index()
    path = "online" if connectivity.is_online else "offline"

    with traced_stage(
        "retrieval",
        get_current_room_name(),
        path,
        tool="fault_history",
        query_hash=prompt_hash(equipment_id),
    ) as span:
        results = await client.query(
            index_name,
            f"job and fault history for {equipment_id}",
            QueryOptions(
                top_k=5,
                alpha=0.5,
                filter={"field": "type", "condition": {"$eq": "job_history"}},
            ),
        )
        span.set_attribute("fieldline.result_count", len(results.docs))

    if not results.docs:
        answer = (
            f"I couldn't find any job history for {equipment_id} in the index. "
            "Double-check the equipment ID -- this may be a new unit with no logged history yet."
        )
    else:
        lines = [doc.text for doc in results.docs]
        answer = f"Job history for {equipment_id}: " + " ".join(lines)

    log_tool_call_background("fault_history", equipment_id, answer)

    return answer