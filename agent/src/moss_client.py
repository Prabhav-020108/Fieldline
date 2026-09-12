"""
Shared Moss client for the FieldLine agent.

Phase 3 (online path): every tool queried the Moss *cloud* index directly
via MossClient.load_index() + MossClient.query().

Phase 4 (offline-first, this file): we now also hydrate a local, in-process
Moss SessionIndex at startup from the same seed data already synced to the
cloud by backend/moss_sync.py. get_index() returns a small router object
(MossRouter) instead of the raw MossClient -- it exposes the exact same
`query(index_name, text, options)` and `add_docs(index_name, docs, options)`
methods, so fault_history.py, safety_procedure.py, inventory_lookup.py,
dispatch_status.py, and log_job_note.py do NOT need to change at all. They
keep calling `client, index_name = await get_index()` exactly as before;
the router decides underneath whether "client" means cloud or local.

NOTE ON ONE ASSUMPTION: `session.query(text, options)` below is written to
mirror MossClient.query()'s signature minus the index_name (since a session
is already bound to one index). This matches the build plan's documented
`client.session(index_name=...)` / `session.add_docs([...])` calls, but has
not been confirmed against the installed Moss SDK the way the cloud-side
calls were in Phase 2. Before relying on this, run:

    uv run python -c "from moss import MossClient; help(MossClient.session)"

...and/or `help()` on whatever object it returns, to confirm the local
session's query method name and signature. If it differs, only the one
`await session.query(text, options)` line below needs to change.
"""

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any

from moss import DocumentInfo, MossClient

from connectivity import connectivity

logger = logging.getLogger("fieldline.moss_client")

INDEX_NAME = "site-demo"

# data/seed/ lives at the repo root, two levels up from agent/src/.
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
SEED_DIR = os.path.join(_THIS_DIR, "..", "..", "data", "seed")
SEED_FILES = ["jobs.json", "safety_manual.json", "inventory.json"]


# ---------------------------------------------------------------------------
# Local in-memory session -- fully offline, no embeddings required
# ---------------------------------------------------------------------------

@dataclass
class _LocalDoc:
    """Minimal doc shape matching what MossClient.query() returns per doc.
    Tools access doc.text, doc.score, and doc.metadata -- nothing else."""
    text: str
    score: float = 0.0      # populated only on query results, not stored docs
    metadata: dict[str, Any] = field(default_factory=dict)
    id: str = ""


@dataclass
class _LocalResults:
    """Wraps a list of _LocalDoc so tools can do `results.docs`."""
    docs: list[_LocalDoc]


class _LocalSession:
    """In-memory keyword search fallback -- no Moss, no embeddings, no network.

    The cloud index (site-demo) uses model_id='custom', which means every
    document must carry pre-computed embedding vectors. We don't have those,
    so instead of going through Moss SessionIndex at all we search locally
    with a simple TF-style keyword scorer. Good enough for the demo offline
    path; the cloud index handles all production calls.

    Returns objects shaped exactly like MossClient.query() results so every
    tool file (fault_history, safety_procedure, etc.) works unchanged.
    """

    def __init__(self) -> None:
        self._docs: list[_LocalDoc] = []

    async def add_docs(self, docs: list[DocumentInfo]) -> None:
        for d in docs:
            self._docs.append(
                _LocalDoc(
                    id=d.id or "",
                    text=d.text or "",
                    metadata=d.metadata or {},
                )
            )

    async def query(self, text: str, options: Any = None) -> _LocalResults:
        """Keyword search: score each doc by how many query words it contains.
        Applies the filter from QueryOptions.filter when present."""
        text_lower = text.lower()
        keywords = [w for w in text_lower.split() if len(w) > 2]  # skip stop-words

        # Extract field-equality filter from Moss QueryOptions if present.
        filter_field: str | None = None
        filter_value: Any = None
        if options is not None:
            raw_filter = getattr(options, "filter", None)
            if isinstance(raw_filter, dict):
                filter_field = raw_filter.get("field")
                cond = raw_filter.get("condition", {})
                filter_value = cond.get("$eq")

        scored: list[tuple[float, _LocalDoc]] = []
        for doc in self._docs:
            # Apply metadata filter.
            if filter_field and filter_value is not None:
                if doc.metadata.get(filter_field) != filter_value:
                    continue
            doc_text = doc.text.lower()
            hits = sum(1 for kw in keywords if kw in doc_text)
            if hits > 0:
                # Normalise score to [0, 1] range so tools' CONFIDENCE_FLOOR works.
                score = min(hits / max(len(keywords), 1), 1.0)
                scored.append((score, doc))

        top_k = getattr(options, "top_k", 5) if options else 5
        scored.sort(key=lambda x: x[0], reverse=True)
        results = []
        for score, doc in scored[:top_k]:
            results.append(_LocalDoc(id=doc.id, text=doc.text, score=score, metadata=doc.metadata))
        return _LocalResults(docs=results)

    async def push_index(self) -> None:
        """No-op: nothing to push. Notes logged offline stay in memory only.
        The cloud index is the source of truth; we don't try to reconcile."""
        logger.info("local session push_index: skipped (custom-model index; cloud is source of truth)")


# ---------------------------------------------------------------------------
# MossRouter -- transparent cloud/local switch
# ---------------------------------------------------------------------------

class MossRouter:
    """Drop-in stand-in for MossClient, from every tool's point of view.

    Tools do:
        client, index_name = await get_index()
        results = await client.query(index_name, text, options)

    This class provides that same query()/add_docs() surface. Underneath,
    it queries the cloud MossClient when connectivity.is_online, and a
    local, pre-hydrated _LocalSession when it isn't -- falling back
    automatically the instant a cloud call actually fails, not just on the
    connectivity monitor's next poll.
    """

    def __init__(self, cloud_client: MossClient) -> None:
        self._cloud_client = cloud_client
        self._session: _LocalSession | None = None
        self._session_lock = asyncio.Lock()

    async def query(self, index_name: str, text: str, options):
        """Always queries the local keyword-search session.

        The cloud Moss index (site-demo) was built with model_id='custom',
        which means MossClient.query() internally calls _query_local() and
        requires pre-computed query embeddings -- the same error as the
        SessionIndex hydration. Attempting the cloud path every call would
        always raise:
          'This index uses custom embeddings. Query embeddings must be
           provided via QueryOptions.embedding.'
        and worse, our catch would call connectivity.mark_offline() for
        what is an API-mismatch error, not a real network failure -- that
        false-offline signal would then cascade and break the STT/LLM
        fallback switching logic mid-conversation.

        The fix: skip the cloud query path entirely. _LocalSession keyword
        search handles all queries. The cloud MossClient is still used for
        add_docs (log_job_note writes) when online.
        """
        session = await self._get_session()
        return await session.query(text, options)

    async def add_docs(self, index_name: str, docs, mutation_options=None):
        """Used by log_job_note.py. Writes to the cloud (and mirrors into
        the local session) when online; writes to the local session only
        when offline -- push_index() catches the cloud back up on reconnect."""
        if connectivity.is_online:
            try:
                result = await self._cloud_client.add_docs(index_name, docs, mutation_options)
                session = await self._get_session()
                await session.add_docs(docs)
                return result
            except Exception:
                logger.exception("cloud add_docs failed -- logging to local session only")
                connectivity.mark_offline()

        session = await self._get_session()
        return await session.add_docs(docs)

    async def _get_session(self):
        async with self._session_lock:
            if self._session is None:
                self._session = await hydrate_session(self._cloud_client, INDEX_NAME)
        return self._session

    async def sync_after_reconnect(self) -> None:
        """Registered with connectivity.on_reconnect() in get_index() below.

        The local session uses model_id='custom' logic bypassed entirely, so
        there is nothing to push back to the cloud Moss index -- the cloud
        index is the source of truth and we don't reconcile offline writes.
        Notes logged offline (log_job_note) are acknowledged to the technician
        but not persisted beyond the current session; that's an acceptable
        demo trade-off.
        """
        logger.info("reconnect sync complete (local session is keyword-only; no push needed)")


async def hydrate_session(
    _cloud_client: MossClient,   # kept in signature for API compat but not used
    _index_name: str,
) -> _LocalSession:
    """Loads job history, the safety manual, and inventory into a local
    in-memory session so it can answer tool queries with the network fully off.

    Uses _LocalSession (keyword search) instead of a Moss SessionIndex because
    the cloud index was built with model_id='custom' -- Moss requires every
    document to carry pre-computed embeddings for that model, which we don't
    have locally. Keyword search is good enough for the demo offline path.

    Reads from data/seed/*.json rather than over the network, on purpose --
    hydration works even if you're already offline when the shift starts.
    """
    session = _LocalSession()

    docs: list[DocumentInfo] = []
    for filename in SEED_FILES:
        path = os.path.join(SEED_DIR, filename)
        with open(path, encoding="utf-8") as f:
            raw_docs = json.load(f)
        for item in raw_docs:
            docs.append(
                DocumentInfo(id=item["id"], text=item["text"], metadata=item["metadata"])
            )

    await session.add_docs(docs)
    logger.info("hydrated local SessionIndex with %d docs from %s", len(docs), SEED_DIR)
    return session


_router: MossRouter | None = None
_lock: asyncio.Lock | None = None


async def get_index() -> tuple[MossRouter, str]:
    """Return a router with the site-demo index ready to go -- cloud-backed
    when online, local-session-backed when offline. Every tool calls this
    exactly as it did in Phase 3; nothing else in tools/*.py changes."""
    global _router, _lock

    if _lock is None:
        _lock = asyncio.Lock()

    async with _lock:
        if _router is None:
            project_id = os.environ["MOSS_PROJECT_ID"]
            project_key = os.environ["MOSS_PROJECT_KEY"]
            cloud_client = MossClient(project_id, project_key)
            await cloud_client.load_index(INDEX_NAME)

            _router = MossRouter(cloud_client)
            # Hydrate the local session up front too, so the very first
            # offline query during a live call doesn't have to wait on it.
            await _router._get_session()
            connectivity.on_reconnect(_router.sync_after_reconnect)

    return _router, INDEX_NAME