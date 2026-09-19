"""
Phase 8d: one shared, durable, SQLite-backed outbound queue for FieldLine's
agent process -- replacing the two separate, ad hoc mechanisms that used
to live in audit_log.py (a per-company JSONL file) and moss_client.py
(silently dropping a failed cloud push once the local session had already
been updated).

Everything that needs to reach a remote service eventually -- an
audit-log entry for the FastAPI backend, or a document that needs to land
in a company's cloud Moss index -- goes through the same three steps:

    1. enqueue(op_type, company_id, payload, idempotency_key) -- called
       the moment an attempt fails, or is skipped because we're already
       offline. Returns immediately; never raises.
    2. A registered handler for that op_type actually performs the network
       call, later, when this module decides the op is due for a retry.
    3. process_due_ops() -- runs every currently-due row through its
       handler, and marks it done or backs it off based on the result.

Retry timing is exponential backoff with jitter, so a struggling backend
or a shaky connection doesn't get hammered by every retry landing on the
same clock tick. idempotency_key makes a retried op safe to apply twice --
both handlers this project registers are naturally idempotent anyway (the
backend's own row-id assignment for audit entries; Moss's own
MutationOptions(upsert=True) for document writes), but the UNIQUE
constraint on idempotency_key is a second, storage-level guarantee that
the same logical write is never queued twice.

Call sync_queue.start() once, at agent startup (agent.py, right next to
connectivity.start()) -- it registers the connectivity on_reconnect hook,
starts the periodic retry loop, and immediately tries to catch up on
anything queued from a previous run. Call
sync_queue.register_handler(op_type, handler) once per op type, at import
time, from whichever module owns that kind of write.
"""

import asyncio
import json
import logging
import os
import random
import sqlite3
import time
from collections.abc import Awaitable, Callable

from connectivity import connectivity

logger = logging.getLogger("fieldline.sync_queue")

# Lives next to agent/src/, not inside it -- per-machine runtime state,
# not application source. Same reasoning as moss_client.py's SEED_DIR.
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(_THIS_DIR, "..", "_sync_queue.sqlite3")

BASE_DELAY_S = 30.0
MAX_DELAY_S = 300.0
JITTER_S = 5.0
MAX_ATTEMPTS = 10  # beyond this, stop retrying and log loudly rather than retry forever

_handlers: dict[str, Callable[[str, dict], Awaitable[bool]]] = {}
_db_lock = asyncio.Lock()
_periodic_task: asyncio.Task | None = None
_reconnect_hook_registered = False


def _next_delay(attempts: int) -> float:
    """Exponential backoff with jitter. attempts=0 -> ~30-35s, attempts=1
    -> ~60-65s, ... capped at MAX_DELAY_S so a long outage still retries
    every 5 minutes rather than backing off indefinitely."""
    return min(BASE_DELAY_S * (2**attempts), MAX_DELAY_S) + random.uniform(0, JITTER_S)


def _get_connection() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sync_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            op_type TEXT NOT NULL,
            company_id TEXT NOT NULL,
            payload TEXT NOT NULL,
            idempotency_key TEXT NOT NULL UNIQUE,
            attempts INTEGER NOT NULL DEFAULT 0,
            next_attempt_at REAL NOT NULL,
            created_at REAL NOT NULL
        )
        """
    )
    return conn


def register_handler(op_type: str, handler: Callable[[str, dict], Awaitable[bool]]) -> None:
    """Register the function that performs one op of this type. The
    handler receives (company_id, payload) and must return True on
    success, False on failure -- a raised exception is treated the same
    as False, but a clean False return lets the handler log its own
    specific failure reason."""
    _handlers[op_type] = handler


async def enqueue(*, op_type: str, company_id: str, payload: dict, idempotency_key: str) -> None:
    """Queue an op for later retry. Safe to call more than once with the
    same idempotency_key -- later calls are silently ignored rather than
    creating a duplicate row."""

    def _write() -> None:
        conn = _get_connection()
        try:
            now = time.time()
            conn.execute(
                """
                INSERT INTO sync_queue
                    (op_type, company_id, payload, idempotency_key, attempts, next_attempt_at, created_at)
                VALUES (?, ?, ?, ?, 0, ?, ?)
                ON CONFLICT(idempotency_key) DO NOTHING
                """,
                (op_type, company_id, json.dumps(payload), idempotency_key, now, now),
            )
            conn.commit()
        finally:
            conn.close()

    async with _db_lock:
        await asyncio.get_event_loop().run_in_executor(None, _write)
    logger.info("queued %s for company %r (key=%r)", op_type, company_id, idempotency_key)


async def process_due_ops() -> None:
    """Run every currently-due row through its registered handler. Safe
    to call repeatedly (periodic loop) or on-demand (connectivity's
    on_reconnect hook)."""

    def _read_due() -> list[tuple]:
        conn = _get_connection()
        try:
            now = time.time()
            cursor = conn.execute(
                "SELECT id, op_type, company_id, payload, attempts FROM sync_queue "
                "WHERE next_attempt_at <= ? ORDER BY id",
                (now,),
            )
            return cursor.fetchall()
        finally:
            conn.close()

    async with _db_lock:
        rows = await asyncio.get_event_loop().run_in_executor(None, _read_due)

    for row_id, op_type, company_id, payload_json, attempts in rows:
        handler = _handlers.get(op_type)
        if handler is None:
            logger.error("no sync_queue handler registered for op_type %r -- leaving it queued", op_type)
            continue

        payload = json.loads(payload_json)
        try:
            success = await handler(company_id, payload)
        except Exception:
            logger.exception("sync_queue handler for %s raised -- treating as failed", op_type)
            success = False

        if success:
            await _mark_done(row_id)
        else:
            await _mark_failed(row_id, attempts)


async def _mark_done(row_id: int) -> None:
    def _write() -> None:
        conn = _get_connection()
        try:
            conn.execute("DELETE FROM sync_queue WHERE id = ?", (row_id,))
            conn.commit()
        finally:
            conn.close()

    async with _db_lock:
        await asyncio.get_event_loop().run_in_executor(None, _write)


async def _mark_failed(row_id: int, attempts: int) -> None:
    new_attempts = attempts + 1
    if new_attempts >= MAX_ATTEMPTS:
        logger.error(
            "sync_queue row %d has failed %d times -- giving up and dropping it "
            "(this should be rare; check backend/Moss reachability)",
            row_id,
            new_attempts,
        )
        await _mark_done(row_id)
        return

    next_attempt_at = time.time() + _next_delay(new_attempts)

    def _write() -> None:
        conn = _get_connection()
        try:
            conn.execute(
                "UPDATE sync_queue SET attempts = ?, next_attempt_at = ? WHERE id = ?",
                (new_attempts, next_attempt_at, row_id),
            )
            conn.commit()
        finally:
            conn.close()

    async with _db_lock:
        await asyncio.get_event_loop().run_in_executor(None, _write)


async def _periodic_loop(interval_seconds: float) -> None:
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            await process_due_ops()
        except Exception:
            logger.exception("periodic sync_queue flush failed")


def start(periodic_interval_seconds: float = 30.0) -> None:
    """Call once, at agent startup. Idempotent -- safe to call more than
    once."""
    global _reconnect_hook_registered, _periodic_task
    if not _reconnect_hook_registered:
        connectivity.on_reconnect(process_due_ops)
        _reconnect_hook_registered = True
    # Catch up immediately on anything queued from a previous run (e.g.
    # this process restarted while offline, so the normal
    # offline -> online transition that triggers on_reconnect never
    # fired) -- fire-and-forget, exactly like the periodic loop below.
    asyncio.create_task(process_due_ops())
    if _periodic_task is None:
        _periodic_task = asyncio.create_task(_periodic_loop(periodic_interval_seconds))