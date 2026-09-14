"""
Tests for the Phase 6 audit-log module: buffering an entry when the
backend is unreachable, and flushing that buffer back once it's reachable
again.

These are plain async unit tests against audit_log.py's functions
directly -- no LiveKit session needed, the same "turn-level checks that
don't need a live session" pattern described in this file's sibling,
test_agent.py. Run them with:

    uv run pytest tests/test_audit_log.py -v
"""

import asyncio
import json

import pytest

import audit_log


@pytest.fixture(autouse=True)
def _isolated_environment(tmp_path, monkeypatch):
    """Every test gets its own throwaway buffer directory (never touches
    the real agent/_audit_buffer/) and starts from a known "online"
    connectivity state, regardless of what earlier tests left behind."""
    monkeypatch.setattr(audit_log, "BUFFER_DIR", str(tmp_path))
    audit_log.connectivity.is_online = True
    yield tmp_path
    audit_log.connectivity.is_online = True


async def test_buffers_locally_when_backend_unreachable(tmp_path, monkeypatch):
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

    buffer_file = tmp_path / "site-demo.jsonl"
    assert buffer_file.exists()

    lines = buffer_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1

    entry = json.loads(lines[0])
    assert entry["tool_name"] == "safety_procedure"
    assert entry["query_text"] == "panel B lockout"
    assert entry["confidence_score"] == pytest.approx(0.82)
    assert entry["below_confidence_floor"] is False
    assert "created_at_local" in entry


async def test_does_not_buffer_when_backend_reachable(tmp_path, monkeypatch):
    calls = []

    async def _always_succeed(company_id, entry):
        calls.append((company_id, entry))
        return True

    monkeypatch.setattr(audit_log, "_post_entry", _always_succeed)

    await audit_log.log_tool_call(
        "site-demo", "fault_history", "unit-12", "Job history for unit-12: ..."
    )

    assert len(calls) == 1
    assert calls[0][0] == "site-demo"
    assert not list(tmp_path.glob("*.jsonl"))


async def test_flush_all_buffers_sends_and_clears_buffered_entries(tmp_path, monkeypatch):
    async def _always_fail(company_id, entry):
        return False

    monkeypatch.setattr(audit_log, "_post_entry", _always_fail)

    await audit_log.log_tool_call(
        "site-demo", "inventory_lookup", "LC1D18", "Schneider contactor ..."
    )
    await audit_log.log_tool_call(
        "acme-elevator", "fault_history", "lift-3", "Job history for lift-3: ..."
    )

    assert (tmp_path / "site-demo.jsonl").exists()
    assert (tmp_path / "acme-elevator.jsonl").exists()

    sent = []

    async def _always_succeed(company_id, entry):
        sent.append((company_id, entry))
        return True

    monkeypatch.setattr(audit_log, "_post_entry", _always_succeed)

    await audit_log.flush_all_buffers()

    assert {company_id for company_id, _ in sent} == {"site-demo", "acme-elevator"}
    assert not (tmp_path / "site-demo.jsonl").exists()
    assert not (tmp_path / "acme-elevator.jsonl").exists()

    for _, entry in sent:
        assert "created_at_local" not in entry
        assert "created_at" in entry


async def test_flush_all_buffers_keeps_entries_that_still_fail(tmp_path, monkeypatch):
    async def _always_fail(company_id, entry):
        return False

    monkeypatch.setattr(audit_log, "_post_entry", _always_fail)

    await audit_log.log_tool_call(
        "site-demo",
        "dispatch_status",
        "current job queue and dispatch status",
        "1 open job ...",
    )

    # Still offline at flush time -- the entry must stay buffered, not be lost.
    await audit_log.flush_all_buffers()

    buffer_file = tmp_path / "site-demo.jsonl"
    assert buffer_file.exists()
    lines = buffer_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1


async def test_start_periodic_flush_is_idempotent(monkeypatch):
    monkeypatch.setattr(audit_log, "_periodic_flush_task", None)

    audit_log.start_periodic_flush(interval_seconds=1000)
    task_first = audit_log._periodic_flush_task
    # Narrows task_first from `asyncio.Task | None` to `asyncio.Task` for
    # the type checker -- start_periodic_flush() always sets it when it
    # was None, so this can never actually fail.
    assert task_first is not None

    audit_log.start_periodic_flush(interval_seconds=1000)
    assert audit_log._periodic_flush_task is task_first

    task_first.cancel()
    try:
        await task_first
    except asyncio.CancelledError:
        pass