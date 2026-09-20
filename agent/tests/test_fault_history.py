"""
Tests for the fault_history tool (FR-01, and FR-07 for the offline case).

Each test replaces Moss with a fake (see tool_test_helpers.py), so nothing
here touches the network.

    uv run pytest tests/test_fault_history.py -v
"""

import pytest
from tool_test_helpers import FakeDoc, install_fakes

import tools.fault_history as fault_history_module
from tools.fault_history import fault_history

JOB_1 = "unit-12 - Tripped overload on the 8th, reset by Anil. Resolution: Breaker reset, monitored 48h."
JOB_2 = "unit-12 - Recurring low-refrigerant flag on the 15th. Resolution: open."


async def test_returns_the_matching_job_history_and_logs_it(monkeypatch):
    client, audit_calls = install_fakes(
        monkeypatch,
        fault_history_module,
        [FakeDoc(text=JOB_1), FakeDoc(text=JOB_2)],
    )

    answer = await fault_history(context=None, equipment_id="unit-12")

    assert answer == f"Job history for unit-12: {JOB_1} {JOB_2}"

    # The search text names the equipment, and goes to the company's index.
    assert client.queries[0][0] == "fake-index"
    assert client.queries[0][1] == "job and fault history for unit-12"

    # Exactly one audit entry, recording what was asked and what was said.
    assert audit_calls == [
        {"tool_name": "fault_history", "query_text": "unit-12", "response_text": answer}
    ]


async def test_unknown_equipment_says_so_instead_of_guessing(monkeypatch):
    _, audit_calls = install_fakes(monkeypatch, fault_history_module, [])

    answer = await fault_history(context=None, equipment_id="unit-99")

    assert "couldn't find any job history for unit-99" in answer
    assert "Job history for" not in answer  # nothing invented
    assert len(audit_calls) == 1
    assert audit_calls[0]["response_text"] == answer


@pytest.mark.parametrize("is_online", [True, False])
async def test_answers_the_same_online_and_offline(monkeypatch, is_online):
    """FR-07: the tool never needs the network -- only its Moss client differs."""
    monkeypatch.setattr(fault_history_module.connectivity, "is_online", is_online)
    install_fakes(monkeypatch, fault_history_module, [FakeDoc(text=JOB_2)])

    answer = await fault_history(context=None, equipment_id="unit-12")

    assert answer == f"Job history for unit-12: {JOB_2}"
