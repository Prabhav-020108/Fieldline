import logging

from livekit.agents import RunContext, function_tool
from moss import QueryOptions

from audit_log import log_tool_call_background
from company_context import get_current_room_name
from connectivity import connectivity
from moss_client import get_index
from tracing import prompt_hash, traced_stage

logger = logging.getLogger("fieldline.inventory_lookup")


@function_tool()
async def inventory_lookup(context: RunContext, part_number: str) -> str:
    """Look up where a spare part is stored and how many are in stock.

    Args:
        part_number: The part number or part name the technician asked
            about, e.g. "LC1D18" or "Schneider contactor".
    """
    logger.info("inventory_lookup for %r", part_number)

    client, index_name = await get_index()
    path = "online" if connectivity.is_online else "offline"

    with traced_stage(
        "retrieval",
        get_current_room_name(),
        path,
        tool="inventory_lookup",
        query_hash=prompt_hash(part_number),
    ) as span:
        results = await client.query(
            index_name,
            f"inventory location for {part_number}",
            QueryOptions(
                top_k=3,
                alpha=0.4,
                filter={"field": "type", "condition": {"$eq": "inventory"}},
            ),
        )
        span.set_attribute("fieldline.result_count", len(results.docs))

    if not results.docs:
        answer = (
            f"I couldn't find {part_number} in the inventory index. "
            "It may not be stocked at this site, or the part number might be off."
        )
    else:
        lines = [doc.text for doc in results.docs]
        answer = " ".join(lines)

    log_tool_call_background("inventory_lookup", part_number, answer)

    return answer