"""
Tests for Phase 6 / Phase 8d audit logging: posting immediately when the
backend is reachable, and queuing via sync_queue.py for retry when it
isn't. The queue's own persistence/backoff mechanics are tested in
test_sync_queue.py -- these tests only check that audit_log.py calls into
that queue correctly.

    uv run pytest tests/test_audit_log.py -v
"""

import pytest

import audit_log
import sync_queue


@pytest.fixture(autouse=True)
def _isolated_environment(tmp_path, monkeypatch):
    """Every test gets its own throwaway queue file and starts from a
    known "online" connectivity state, regardless of what earlier tests
    left behind."""
    monkeypatch.setattr(sync_queue, "DB_PATH", str(tmp_path / "test_queue.sqlite3"))
    audit_log.connectivity.is_online = True
    yield
    audit_log.connectivity.is_online = True


def _queued_row_count() -> int:
    conn = sync_queue._get_connection()
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM sync_queue WHERE op_type = 'audit_log_entry'"
        ).fetchone()[0]
    finally:
        conn.close()


async def test_queues_locally_when_backend_unreachable(monkeypatch):
    async def _always_fail(company_id, entry):
        return False

    monkeypatch.setattr(audit_log, "_post_entry", _always_fail)

    await audit_log.log_tool_call(
        "site-demo",
        "safety_procedure",
        "panel B lockout",
        "Section 4.2 ... Source: Site Electrical Safety Manual, Section 4.2.",
        source_citation="Site Electrical Safety Manual, Section 4.2",
        confidence_score=0.82,
        below_confidence_floor=False,
    )

    assert _queued_row_count() == 1


async def test_does_not_queue_when_backend_reachable(monkeypatch):
    calls = []

    async def _always_succeed(company_id, entry):
        calls.append((company_id, entry))
        return True

    monkeypatch.setattr(audit_log, "_post_entry", _always_succeed)

    await audit_log.log_tool_call("site-demo", "fault_history", "unit-12", "Job history for unit-12: ...")

    assert len(calls) == 1
    assert calls[0][0] == "site-demo"
    assert _queued_row_count() == 0


async def test_offline_skips_the_network_attempt_and_queues_directly(monkeypatch):
    calls = []

    async def _should_never_be_called(company_id, entry):
        calls.append((company_id, entry))
        return True

    monkeypatch.setattr(audit_log, "_post_entry", _should_never_be_called)
    audit_log.connectivity.is_online = False

    await audit_log.log_tool_call("site-demo", "inventory_lookup", "LC1D18", "Schneider contactor ...")

    assert calls == []  # never attempted the network call while offline
    assert _queued_row_count() == 1


async def test_queued_entry_is_replayed_once_the_backend_is_reachable(monkeypatch):
    async def _always_fail(company_id, entry):
        return False

    monkeypatch.setattr(audit_log, "_post_entry", _always_fail)

    await audit_log.log_tool_call(
        "site-demo", "dispatch_status", "current job queue and dispatch status", "1 open job ..."
    )
    assert _queued_row_count() == 1

    sent = []

    async def _always_succeed(company_id, entry):
        sent.append((company_id, entry))
        return True

    monkeypatch.setattr(audit_log, "_post_entry", _always_succeed)

    await sync_queue.process_due_ops()

    assert len(sent) == 1
    assert sent[0][0] == "site-demo"
    assert _queued_row_count() == 0
