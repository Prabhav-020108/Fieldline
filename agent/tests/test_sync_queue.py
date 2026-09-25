"""
Tests for the Phase 8d sync queue: enqueue/dedupe, successful processing
removing a row, failed processing backing off with a growing delay, and
start()'s idempotency.

    uv run pytest tests/test_sync_queue.py -v
"""

import asyncio
import contextlib
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
    with contextlib.suppress(asyncio.CancelledError):
        await task_first


async def test_row_dropped_after_max_attempts():
    async def _always_fail(company_id, payload):
        return False

    sync_queue.register_handler("test_fail_op", _always_fail)
    await sync_queue.enqueue(
        op_type="test_fail_op", company_id="site-demo", payload={}, idempotency_key="key-max"
    )
    assert _row_count() == 1

    # Simulate 9 failed attempts already recorded
    conn = sync_queue._get_connection()
    conn.execute("UPDATE sync_queue SET attempts = 9, next_attempt_at = ?", (time.time() - 1,))
    conn.commit()
    conn.close()

    # The 10th attempt reaches MAX_ATTEMPTS (10) and drops the row
    await sync_queue.process_due_ops()
    assert _row_count() == 0


def test_next_delay_bounds():
    # Attempt 0: delay should be between 30 and 35 seconds
    delay_0 = sync_queue._next_delay(0)
    assert 30.0 <= delay_0 <= 35.0

    # High attempt: delay should cap at MAX_DELAY_S (300) + jitter (up to 5s)
    delay_high = sync_queue._next_delay(15)
    assert 300.0 <= delay_high <= 305.0


async def test_handler_exception_treated_as_failure():
    async def _crashes(company_id, payload):
        raise RuntimeError("Network cable chewed by squirrel")

    sync_queue.register_handler("test_crash_op", _crashes)
    await sync_queue.enqueue(
        op_type="test_crash_op", company_id="site-demo", payload={}, idempotency_key="key-crash"
    )

    # process_due_ops should catch the exception and back off instead of crashing
    await sync_queue.process_due_ops()
    attempts, _ = _fetch_row()
    assert attempts == 1