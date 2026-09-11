import logging

from livekit.agents import RunContext, function_tool
from moss import QueryOptions

from moss_client import get_index

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
    results = await client.query(
        index_name,
        f"job and fault history for {equipment_id}",
        QueryOptions(
            top_k=5,
            alpha=0.5,
            filter={"field": "type", "condition": {"$eq": "job_history"}},
        ),
    )

    if not results.docs:
        return (
            f"I couldn't find any job history for {equipment_id} in the index. "
            "Double-check the equipment ID -- this may be a new unit with no logged history yet."
        )

    lines = [doc.text for doc in results.docs]
    return f"Job history for {equipment_id}: " + " ".join(lines)
