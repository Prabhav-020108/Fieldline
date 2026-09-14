"""
Shared Moss client for the FieldLine agent -- Phase 5, multi-tenant.

Phase 3 (online path): every tool queried a single hardcoded Moss cloud
index ("site-demo") directly.

Phase 4 (offline-first): added a local, in-process fallback session
(_LocalSession, keyword search) hydrated from static seed JSON files, plus
a MossRouter that switches between the cloud client and the local session
based on connectivity.is_online -- see connectivity.py.

Phase 5 (this file, multi-tenant): "site-demo" is no longer the only
customer. Every call now belongs to a specific company, and each company
gets its OWN Moss index (see the Phase 5 build plan's "index-per-tenant"
section) and its own local session, so two companies can never see each
other's job history or safety procedures.

get_index() keeps the EXACT same public signature it always had --
`await get_index()`, no arguments -- so fault_history.py, safety_procedure.py,
inventory_lookup.py, dispatch_status.py, and log_job_note.py do not change
at all for Phase 5. The company a call belongs to is read from
company_context.get_current_company(), a contextvars.ContextVar that
agent.py sets once, at the very top of entrypoint(), from the room name --
see company_context.py for the full explanation.

Company metadata (which Moss index a company uses) comes from the FastAPI
backend built in Phase 5 (backend/main.py's GET /companies/{id}), not from
a hardcoded constant. The local session's documents come from that same
backend's GET /companies/{id}/export instead of the fixed data/seed/*.json
files used in Phase 4 -- see hydrate_session() below.

Backward-compatible fallback: if the backend is unreachable AND the
company is the original "site-demo" demo company, this falls back to the
exact Phase 4 behaviour (hardcoded index name "site-demo", local seed JSON
files), so your most-rehearsed demo path still works even with the FastAPI
backend not running. Any OTHER company without a reachable backend gets an
empty local session and a clear log warning instead of a crash.
"""

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any

import httpx
from moss import DocumentInfo, MossClient

from company_context import DEFAULT_COMPANY_ID, get_current_company
from connectivity import connectivity

logger = logging.getLogger("fieldline.moss_client")

BACKEND_URL = os.environ.get("FIELDLINE_BACKEND_URL", "http://localhost:8000")

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
    below. Unchanged from Phase 4 other than now living inside a
    per-company cache instead of a single global.
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
    now scoped to exactly one company.

    Tools do:
        client, index_name = await get_index()
        results = await client.query(index_name, text, options)

    Underneath, queries always go to this company's local keyword-search
    session (see the module docstring above for why the cloud query path
    is skipped for this custom-embeddings index); add_docs() writes to the
    cloud index when online and mirrors into the local session, or writes
    to the local session only when offline.
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
        if connectivity.is_online:
            try:
                result = await self._cloud_client.add_docs(index_name, docs, mutation_options)
                session = await self._get_session()
                await session.add_docs(docs)
                return result
            except Exception:
                logger.exception(
                    "cloud add_docs failed for company %s -- logging to local session only",
                    self.company_id,
                )
                connectivity.mark_offline()

        session = await self._get_session()
        return await session.add_docs(docs)

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

    Phase 5: reads from the FastAPI backend's per-company export endpoint
    instead of the fixed data/seed/*.json files used in Phase 4, since
    every company now has its own rows in backend/db.sqlite3. Falls back
    to the original Phase 4 seed-file behaviour ONLY for the default
    "site-demo" company, and only if the backend can't be reached -- so
    your original, most-rehearsed demo path never breaks even if you
    forget to start `uvicorn main:app`.
    """
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
                "company. Start the backend (`uv run uvicorn main:app "
                "--reload --port 8000` from backend/) to use live, "
                "dashboard-edited data instead.",
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
                "backend is reachable. Start it with `uv run uvicorn "
                "main:app --reload --port 8000` from backend/.",
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
    other company (so a brand-new company still resolves to *something*
    even if the backend happens to be down for a moment)."""
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
    entrypoint() for this call. Every tool calls this exactly as it did in
    Phase 3 and 4, with zero arguments; nothing in tools/*.py changes."""
    global _routers_lock

    company_id = get_current_company()

    if _routers_lock is None:
        _routers_lock = asyncio.Lock()

    async with _routers_lock:
        router = _routers.get(company_id)
        if router is None:
            config = await _fetch_company_config(company_id)
            index_name = config.get("moss_index_name") or f"company-{company_id}"

            project_id = os.environ["MOSS_PROJECT_ID"]
            project_key = os.environ["MOSS_PROJECT_KEY"]
            cloud_client = MossClient(project_id, project_key)
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