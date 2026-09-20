"""
Tests for the dispatch_status tool (FR-05, and FR-07 for the offline case).

    uv run pytest tests/test_dispatch_status.py -v
"""

import pytest
from tool_test_helpers import FakeDoc, install_fakes

import tools.dispatch_status as dispatch_status_module
from tools.dispatch_status import dispatch_status

QUEUE = (
    "Current job queue for site-demo: 1 open job(s) -- "
    "unit-12 (Recurring low-refrigerant flag on the 15th)."
)
REROUTE = (
    "Dispatch reroute: job 2 (unit-12, Recurring low-refrigerant flag on the 15th) "
    "was rerouted to priority status. Treat it as the next job after any work "
    "currently in progress."
)


async def test_reads_out_the_queue_and_logs_a_status_check(monkeypatch):
    client, audit_calls = install_fakes(monkeypatch, dispatch_status_module, [FakeDoc(text=QUEUE)])

    answer = await dispatch_status(context=None)

    assert answer == QUEUE
    assert client.queries[0][1] == "current job queue dispatch status and reroutes"
    # This tool takes no argument, so the audit "query" is a fixed description.
    assert audit_calls == [
        {
            "tool_name": "dispatch_status",
            "query_text": "current job queue and dispatch status",
            "response_text": answer,
        }
    ]


async def test_a_dispatcher_reroute_is_included_in_the_answer(monkeypatch):
    """FR-05: a reroute made on the dashboard reaches the technician's next
    dispatch_status call."""
    install_fakes(
        monkeypatch, dispatch_status_module, [FakeDoc(text=QUEUE), FakeDoc(text=REROUTE)]
    )

    answer = await dispatch_status(context=None)

    assert QUEUE in answer
    assert "rerouted to priority status" in answer


async def test_no_documents_means_the_queue_looks_unchanged(monkeypatch):
    _, audit_calls = install_fakes(monkeypatch, dispatch_status_module, [])

    answer = await dispatch_status(context=None)

    assert answer == "I don't see any dispatch updates right now -- your queue looks unchanged."
    assert len(audit_calls) == 1


@pytest.mark.parametrize("is_online", [True, False])
async def test_answers_the_same_online_and_offline(monkeypatch, is_online):
    monkeypatch.setattr(dispatch_status_module.connectivity, "is_online", is_online)
    install_fakes(monkeypatch, dispatch_status_module, [FakeDoc(text=QUEUE)])

    assert await dispatch_status(context=None) == QUEUE
