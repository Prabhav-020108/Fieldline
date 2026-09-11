import logging

from livekit.agents import RunContext, function_tool
from moss import QueryOptions

from moss_client import get_index

logger = logging.getLogger("fieldline.dispatch_status")


@function_tool()
async def dispatch_status(context: RunContext) -> str:
    """Report the current job queue and any dispatch reroutes for the site.

    Use this when the technician asks what's next, whether anything has
    changed with their schedule, or whether a job has been rerouted.
    """
    logger.info("dispatch_status lookup")

    client, index_name = await get_index()
    results = await client.query(
        index_name,
        "current job queue dispatch status and reroutes",
        QueryOptions(
            top_k=5,
            alpha=0.5,
            filter={"field": "type", "condition": {"$eq": "dispatch_status"}},
        ),
    )

    if not results.docs:
        return "I don't see any dispatch updates right now -- your queue looks unchanged."

    lines = [doc.text for doc in results.docs]
    return " ".join(lines)