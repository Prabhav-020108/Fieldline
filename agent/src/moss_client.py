"""
Shared Moss client for the FieldLine agent.

Phase 3 (online path): every tool queries the Moss *cloud* index directly via
MossClient.load_index() + MossClient.query(). There is no local SessionIndex
yet -- that is Phase 4's offline layer, which hydrates a SessionIndex at
shift start and keeps serving queries from it with the network fully off.
"""

import asyncio
import os

from moss import MossClient

INDEX_NAME = "site-demo"

_client: MossClient | None = None
_loaded = False
_lock: asyncio.Lock | None = None


async def get_index() -> tuple[MossClient, str]:
    """Return a MossClient with the site-demo index loaded.

    Creates the client and loads the index on first call; every call after
    that reuses the same client and skips the network round trip to
    load_index. Safe to call from every tool.
    """
    global _client, _loaded, _lock

    if _lock is None:
        _lock = asyncio.Lock()

    async with _lock:
        if _client is None:
            project_id = os.environ["MOSS_PROJECT_ID"]
            project_key = os.environ["MOSS_PROJECT_KEY"]
            _client = MossClient(project_id, project_key)

        if not _loaded:
            await _client.load_index(INDEX_NAME)
            _loaded = True

    return _client, INDEX_NAME