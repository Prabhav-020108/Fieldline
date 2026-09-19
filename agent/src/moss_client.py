"""
Shared Moss client for the FieldLine agent -- Phase 5, multi-tenant.
Phase 8d update: a failed or offline cloud write is now queued via
sync_queue.py for retry, instead of being silently dropped.

Phase 3 (online path): every tool queried a single hardcoded Moss cloud
index ("site-demo") directly.

Phase 4 (offline-first): added a local, in-process fallback session
(_LocalSession, keyword search) hydrated from static seed JSON files, plus
a MossRouter that switches between the cloud client and the local session
based on connectivity.is_online.

Phase 5 (multi-tenant): every call belongs to a specific company, and
each company gets its own Moss index and its own local session.

get_index() keeps the EXACT same public signature it always had --
`await get_index()`, no arguments -- so fault_history.py, safety_procedure.py,
inventory_lookup.py, dispatch_status.py, and log_job_note.py do not change
at all. The company a call belongs to is read from
company_context.get_current_company().

Company metadata (which Moss index a company uses) comes from the FastAPI
backend, not a hardcoded constant. The local session's documents come
from that same backend's export endpoint instead of the fixed
data/seed/*.json files used in Phase 4.

Backward-compatible fallback: if the backend is unreachable AND the
company is the original "site-demo" demo company, this falls back to the
Phase 4 behaviour (hardcoded index name "site-demo", local seed JSON
files). Any OTHER company without a reachable backend gets an empty local
session and a clear log warning instead of a crash.
"""

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any

import httpx
from moss import DocumentInfo, MossClient, MutationOptions

from company_context import DEFAULT_COMPANY_ID, get_current_company
from connectivity import connectivity
from settings import settings
import sync_queue

logger = logging.getLogger("fieldline.moss_client")

BACKEND_URL = settings.fieldline_backend_url

# data/seed/ lives at the repo root, two levels up from agent/src/. Only
# used as a fallback for the default "site-demo" company if the backend is
# unreachable -- see hydrate_session().
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
    score: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    id: str = ""


@dataclass
class _LocalResults:
    """Wraps a list of _LocalDoc so tools can do `results.docs`."""
    docs: list[_LocalDoc]


class _LocalSession:
    """In-memory keyword search fallback -- no Moss, no embeddings, no
    network. One instance per company; see MossRouter / _get_session
    below."""

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
        """Keyword search: score each doc by how many query words it
        contains. Applies the filter from QueryOptions.filter when
        present."""
        text_lower = text.lower()
        keywords = [w for w in text_lower.split() if len(w) > 2]

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
            if filter_field and filter_value is not None:
                if doc.metadata.get(filter_field) != filter_value:
                    continue
            doc_text = doc.text.lower()
            hits = sum(1 for kw in keywords if kw in doc_text)
            if hits > 0:
                score = min(hits / max(len(keywords), 1), 1.0)
                scored.append((score, doc))

        top_k = getattr(options, "top_k", 5) if options else 5
        scored.sort(key=lambda x: x[0], reverse=True)
        results = []
        for score, doc in scored[:top_k]:
            results.append(_LocalDoc(id=doc.id, text=doc.text, score=score, metadata=doc.metadata))
        return _LocalResults(docs=results)

    async def push_index(self) -> None:
        logger.info("local session push_index: skipped (custom-model index; cloud is source of truth)")


# ---------------------------------------------------------------------------
# MossRouter -- transparent cloud/local switch, one per company
# ---------------------------------------------------------------------------

class MossRouter:
    """Drop-in stand-in for MossClient, from every tool's point of view --
    scoped to exactly one company.

    Tools do:
        client, index_name = await get_index()
        results = await client.query(index_name, text, options)

    Queries always go to this company's local keyword-search session (see
    the module docstring for why the cloud query path is skipped for this
    custom-embeddings index). add_docs() always writes to the local
    session immediately (so an offline read sees the note right away),
    then either pushes to the cloud index right now (if online) or queues
    that push via sync_queue for retry -- see the module-level
    _sync_queue_moss_handler below.
    """

    def __init__(self, company_id: str, index_name: str, cloud_client: MossClient) -> None:
        self.company_id = company_id
        self.index_name = index_name
        self._cloud_client = cloud_client
        self._session: _LocalSession | None = None
        self._session_lock = asyncio.Lock()

    async def query(self, index_name: str, text: str, options):
        session = await self._get_session()
        return await session.query(text, options)

    async def add_docs(self, index_name: str, docs, mutation_options=None):
        session = await self._get_session()
        # Always write to the local session immediately -- offline reads
        # must see this note/document right away, regardless of whether
        # the cloud push below succeeds this instant or gets queued.
        await session.add_docs(docs)

        if connectivity.is_online:
            try:
                return await self._cloud_client.add_docs(index_name, docs, mutation_options)
            except Exception:
                logger.exception(
                    "cloud add_docs failed for company %s -- queuing for retry "
                    "via sync_queue instead of losing the write",
                    self.company_id,
                )
                connectivity.mark_offline()

        # Offline (either already, or just detected above): queue the
        # cloud push for retry instead of losing it -- see sync_queue.py.
        await sync_queue.enqueue(
            op_type="moss_add_docs",
            company_id=self.company_id,
            payload={
                "index_name": index_name,
                "docs": [{"id": d.id, "text": d.text, "metadata": d.metadata} for d in docs],
            },
            idempotency_key=f"moss-add-docs-{self.company_id}-{'-'.join(d.id for d in docs)}",
        )
        return None

    async def _get_session(self) -> _LocalSession:
        async with self._session_lock:
            if self._session is None:
                self._session = await hydrate_session(self.company_id, self.index_name)
        return self._session

    async def sync_after_reconnect(self) -> None:
        logger.info(
            "reconnect sync complete for company %s (local session is keyword-only; no push needed)",
            self.company_id,
        )


async def hydrate_session(company_id: str, index_name: str) -> _LocalSession:
    """Loads job history, safety procedures, inventory, and dispatch
    status for ONE company into a local in-memory session, so tool calls
    can answer with the network fully off.

    Reads from the FastAPI backend's per-company export endpoint. Falls
    back to the original Phase 4 seed-file behaviour ONLY for the default
    "site-demo" company, and only if the backend can't be reached."""
    session = _LocalSession()
    docs: list[DocumentInfo] = []

    try:
        async with httpx.AsyncClient(timeout=10) as http_client:
            resp = await http_client.get(f"{BACKEND_URL}/companies/{company_id}/export")
            resp.raise_for_status()
            payload = resp.json()
        for item in payload.get("documents", []):
            docs.append(
                DocumentInfo(id=item["id"], text=item["text"], metadata=item.get("metadata", {}))
            )
        logger.info(
            "hydrated local session for company %r with %d docs from backend (%s)",
            company_id,
            len(docs),
            BACKEND_URL,
        )
    except Exception:
        if company_id == DEFAULT_COMPANY_ID:
            logger.warning(
                "could not reach FastAPI backend at %s -- falling back to "
                "the original Phase 4 seed files for the default demo "
                "company. Start the backend to use live, dashboard-edited "
                "data instead.",
                BACKEND_URL,
            )
            for filename in SEED_FILES:
                path = os.path.join(SEED_DIR, filename)
                with open(path, encoding="utf-8") as f:
                    raw_docs = json.load(f)
                for item in raw_docs:
                    docs.append(
                        DocumentInfo(id=item["id"], text=item["text"], metadata=item["metadata"])
                    )
            logger.info("hydrated local session with %d docs from seed files (fallback)", len(docs))
        else:
            logger.exception(
                "could not reach FastAPI backend at %s to hydrate company "
                "%r -- this company will have no indexed data until the "
                "backend is reachable.",
                BACKEND_URL,
                company_id,
            )

    await session.add_docs(docs)
    return session


# ---------------------------------------------------------------------------
# Per-company router cache
# ---------------------------------------------------------------------------

_routers: dict[str, MossRouter] = {}
_routers_lock: asyncio.Lock | None = None


async def _fetch_company_config(company_id: str) -> dict:
    """Ask the FastAPI backend which Moss index this company uses. Falls
    back to the Phase 4 default for "site-demo" if the backend can't be
    reached, and to a predictable f"company-{company_id}" guess for any
    other company."""
    try:
        async with httpx.AsyncClient(timeout=10) as http_client:
            resp = await http_client.get(f"{BACKEND_URL}/companies/{company_id}")
            resp.raise_for_status()
            return resp.json()
    except Exception:
        fallback_index = "site-demo" if company_id == DEFAULT_COMPANY_ID else f"company-{company_id}"
        logger.warning(
            "could not fetch company config for %r from backend at %s -- assuming Moss index name %r",
            company_id,
            BACKEND_URL,
            fallback_index,
        )
        return {"id": company_id, "moss_index_name": fallback_index}


async def get_index() -> tuple[MossRouter, str]:
    """Return a router for the CURRENT company -- the one set by
    company_context.set_current_company() at the top of agent.py's
    entrypoint() for this call."""
    global _routers_lock

    company_id = get_current_company()

    if _routers_lock is None:
        _routers_lock = asyncio.Lock()

    async with _routers_lock:
        router = _routers.get(company_id)
        if router is None:
            config = await _fetch_company_config(company_id)
            index_name = config.get("moss_index_name") or f"company-{company_id}"

            cloud_client = MossClient(settings.moss_project_id, settings.moss_project_key)
            try:
                await cloud_client.load_index(index_name)
            except Exception:
                logger.warning(
                    "cloud_client.load_index(%r) failed for company %r -- "
                    "continuing with the local session only. Cloud writes "
                    "from log_job_note will still be attempted per-call.",
                    index_name,
                    company_id,
                )

            router = MossRouter(company_id, index_name, cloud_client)
            await router._get_session()
            connectivity.on_reconnect(router.sync_after_reconnect)
            _routers[company_id] = router

    return router, router.index_name


# ---------------------------------------------------------------------------
# Phase 8d: sync_queue handler for a queued cloud write
# ---------------------------------------------------------------------------

async def _sync_queue_moss_handler(company_id: str, payload: dict) -> bool:
    """Registered with sync_queue below -- replays one queued Moss cloud
    write. Reuses whatever router is already cached for this company, or
    resolves one fresh if the agent process restarted since the write was
    queued."""
    router = _routers.get(company_id)
    if router is None:
        config = await _fetch_company_config(company_id)
        index_name = config.get("moss_index_name") or f"company-{company_id}"
        cloud_client = MossClient(settings.moss_project_id, settings.moss_project_key)
        router = MossRouter(company_id, index_name, cloud_client)
        _routers[company_id] = router

    docs = [
        DocumentInfo(id=d["id"], text=d["text"], metadata=d.get("metadata", {}))
        for d in payload["docs"]
    ]
    try:
        await router._cloud_client.add_docs(payload["index_name"], docs, MutationOptions(upsert=True))
        return True
    except Exception:
        logger.exception("retry of queued Moss write failed for company %r", company_id)
        return False


sync_queue.register_handler("moss_add_docs", _sync_queue_moss_handler)