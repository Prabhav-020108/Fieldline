import logging

from livekit.agents import RunContext, function_tool
from moss import QueryOptions

from moss_client import get_index

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
    results = await client.query(
        index_name,
        f"inventory location for {part_number}",
        QueryOptions(
            top_k=3,
            alpha=0.4,
            filter={"field": "type", "condition": {"$eq": "inventory"}},
        ),
    )

    if not results.docs:
        return (
            f"I couldn't find {part_number} in the inventory index. "
            "It may not be stocked at this site, or the part number might be off."
        )

    lines = [doc.text for doc in results.docs]
    return " ".join(lines)