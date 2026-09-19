"""
Tests for the Phase 8d sync queue: enqueue/dedupe, successful processing
removing a row, failed processing backing off with a growing delay, and
start()'s idempotency.

    uv run pytest tests/test_sync_queue.py -v
"""

import asyncio
import time

import pytest

import sync_queue


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    """Every test gets its own throwaway SQLite file so tests never touch
    the real agent/_sync_queue.sqlite3."""
    monkeypatch.setattr(sync_queue, "DB_PATH", str(tmp_path / "test_queue.sqlite3"))
    sync_queue._handlers.clear()
    yield
    sync_queue._handlers.clear()


def _row_count() -> int:
    conn = sync_queue._get_connection()
    try:
        return conn.execute("SELECT COUNT(*) FROM sync_queue").fetchone()[0]
    finally:
        conn.close()


def _fetch_row():
    conn = sync_queue._get_connection()
    try:
        return conn.execute("SELECT attempts, next_attempt_at FROM sync_queue LIMIT 1").fetchone()
    finally:
        conn.close()


async def test_enqueue_then_successful_process_removes_the_row():
    async def _succeed(company_id, payload):
        return True

    sync_queue.register_handler("test_op", _succeed)

    await sync_queue.enqueue(op_type="test_op", company_id="site-demo", payload={"n": 1}, idempotency_key="key-1")
    assert _row_count() == 1

    await sync_queue.process_due_ops()
    assert _row_count() == 0


async def test_enqueue_then_failed_process_backs_off_with_growing_delay():
    async def _fail(company_id, payload):
        return False

    sync_queue.register_handler("test_op", _fail)

    await sync_queue.enqueue(op_type="test_op", company_id="site-demo", payload={"n": 1}, idempotency_key="key-2")

    before = time.time()
    await sync_queue.process_due_ops()
    attempts_1, next_attempt_1 = _fetch_row()
    assert attempts_1 == 1
    first_delay = next_attempt_1 - before

    conn = sync_queue._get_connection()
    conn.execute("UPDATE sync_queue SET next_attempt_at = ?", (time.time(),))
    conn.commit()
    conn.close()

    before_2 = time.time()
    await sync_queue.process_due_ops()
    attempts_2, next_attempt_2 = _fetch_row()
    assert attempts_2 == 2
    second_delay = next_attempt_2 - before_2

    assert second_delay > first_delay


async def test_duplicate_idempotency_key_is_only_stored_once():
    await sync_queue.enqueue(op_type="test_op", company_id="site-demo", payload={"n": 1}, idempotency_key="same-key")
    await sync_queue.enqueue(op_type="test_op", company_id="site-demo", payload={"n": 2}, idempotency_key="same-key")
    assert _row_count() == 1


async def test_unregistered_op_type_stays_queued():
    await sync_queue.enqueue(op_type="mystery_op", company_id="site-demo", payload={}, idempotency_key="key-3")
    await sync_queue.process_due_ops()
    assert _row_count() == 1


async def test_start_is_idempotent(monkeypatch):
    monkeypatch.setattr(sync_queue, "_periodic_task", None)
    monkeypatch.setattr(sync_queue, "_reconnect_hook_registered", False)

    sync_queue.start(periodic_interval_seconds=1000)
    task_first = sync_queue._periodic_task
    assert task_first is not None

    sync_queue.start(periodic_interval_seconds=1000)
    assert sync_queue._periodic_task is task_first

    task_first.cancel()
    try:
        await task_first
    except asyncio.CancelledError:
        pass