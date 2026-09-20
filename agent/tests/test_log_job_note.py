"""
Tests for the log_job_note tool, including the role rule that only a
supervisor or dispatcher may close a job out loud.

Covers: FR-06 (voice-logged job notes) and NFR-14 (the role check needs no
network -- so it must behave identically online and offline).

    uv run pytest tests/test_log_job_note.py -v
"""

import pytest
from tool_test_helpers import install_fakes

import tools.log_job_note as log_job_note_module
from tools.log_job_note import log_job_note


def _set_role(monkeypatch, role: str) -> None:
    monkeypatch.setattr(log_job_note_module, "get_current_role", lambda: role)


async def test_a_plain_note_is_written_to_the_index_as_open(monkeypatch):
    _set_role(monkeypatch, "technician")
    client, audit_calls = install_fakes(monkeypatch, log_job_note_module, [])

    answer = await log_job_note(
        context=None, equipment_id="unit-12", note="Replaced the contactor"
    )

    assert answer == "Got it, I've logged that note against unit-12."

    # Exactly one write to the index...
    assert len(client.added) == 1
    write = client.added[0]
    assert write["index_name"] == "fake-index"
    doc = write["docs"][0]
    assert doc.id.startswith("note-unit-12-")
    assert "unit-12 - field note logged" in doc.text
    assert doc.text.endswith("Replaced the contactor")
    assert doc.metadata == {"type": "job_history", "equipment": "unit-12", "status": "open"}

    # ...and one audit entry.
    assert audit_calls == [
        {
            "tool_name": "log_job_note",
            "query_text": "unit-12: Replaced the contactor",
            "response_text": answer,
        }
    ]


async def test_a_technician_cannot_close_a_job_but_the_note_is_still_saved(monkeypatch):
    _set_role(monkeypatch, "technician")
    client, _ = install_fakes(monkeypatch, log_job_note_module, [])

    answer = await log_job_note(
        context=None, equipment_id="unit-12", note="All done", mark_resolved=True
    )

    assert "Closing out a job needs a supervisor or dispatcher" in answer
    assert "still open" in answer
    # The note was still written -- just left open.
    assert len(client.added) == 1
    assert client.added[0]["docs"][0].metadata["status"] == "open"


@pytest.mark.parametrize("role", ["supervisor", "dispatcher"])
async def test_supervisor_and_dispatcher_can_close_a_job(monkeypatch, role):
    _set_role(monkeypatch, role)
    client, _ = install_fakes(monkeypatch, log_job_note_module, [])

    answer = await log_job_note(
        context=None, equipment_id="unit-12", note="All done", mark_resolved=True
    )

    assert answer == "Got it, I've logged that note and marked unit-12 resolved."
    assert client.added[0]["docs"][0].metadata["status"] == "closed"


async def test_the_role_check_works_with_the_network_off(monkeypatch):
    """NFR-14: offline, a technician is still denied and a dispatcher still
    allowed -- the check never touches the network."""
    monkeypatch.setattr(log_job_note_module.connectivity, "is_online", False)

    _set_role(monkeypatch, "technician")
    client, _ = install_fakes(monkeypatch, log_job_note_module, [])
    await log_job_note(context=None, equipment_id="unit-12", note="x", mark_resolved=True)
    assert client.added[0]["docs"][0].metadata["status"] == "open"

    _set_role(monkeypatch, "dispatcher")
    client, _ = install_fakes(monkeypatch, log_job_note_module, [])
    await log_job_note(context=None, equipment_id="unit-12", note="x", mark_resolved=True)
    assert client.added[0]["docs"][0].metadata["status"] == "closed"


async def test_every_note_gets_its_own_unique_id(monkeypatch):
    _set_role(monkeypatch, "technician")
    client, _ = install_fakes(monkeypatch, log_job_note_module, [])

    await log_job_note(context=None, equipment_id="unit-12", note="first")
    await log_job_note(context=None, equipment_id="unit-12", note="second")

    ids = [write["docs"][0].id for write in client.added]
    assert len(set(ids)) == 2
