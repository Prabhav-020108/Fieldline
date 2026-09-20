"""
Tests for the inventory_lookup tool (FR-04, and FR-07 for the offline case).

    uv run pytest tests/test_inventory_lookup.py -v
"""

import pytest
from tool_test_helpers import FakeDoc, install_fakes

import tools.inventory_lookup as inventory_lookup_module
from tools.inventory_lookup import inventory_lookup

CONTACTOR = "Schneider contactor (part LC1D18) - stored at bin 14C, site store room, qty 3."


async def test_returns_the_location_and_quantity_and_logs_it(monkeypatch):
    client, audit_calls = install_fakes(
        monkeypatch, inventory_lookup_module, [FakeDoc(text=CONTACTOR)]
    )

    answer = await inventory_lookup(context=None, part_number="LC1D18")

    assert answer == CONTACTOR
    assert "bin 14C" in answer and "qty 3" in answer

    assert client.queries[0][1] == "inventory location for LC1D18"
    assert audit_calls == [
        {"tool_name": "inventory_lookup", "query_text": "LC1D18", "response_text": answer}
    ]


async def test_several_matches_are_read_out_together(monkeypatch):
    second = "Schneider contactor (part LC1D25) - stored at bin 15A, site store room, qty 1."
    install_fakes(
        monkeypatch,
        inventory_lookup_module,
        [FakeDoc(text=CONTACTOR), FakeDoc(text=second)],
    )

    answer = await inventory_lookup(context=None, part_number="Schneider contactor")

    assert answer == f"{CONTACTOR} {second}"


async def test_unknown_part_says_so_instead_of_guessing(monkeypatch):
    _, audit_calls = install_fakes(monkeypatch, inventory_lookup_module, [])

    answer = await inventory_lookup(context=None, part_number="ZZZ-999")

    assert "couldn't find ZZZ-999 in the inventory index" in answer
    assert "bin" not in answer  # no invented location
    assert len(audit_calls) == 1


@pytest.mark.parametrize("is_online", [True, False])
async def test_answers_the_same_online_and_offline(monkeypatch, is_online):
    monkeypatch.setattr(inventory_lookup_module.connectivity, "is_online", is_online)
    install_fakes(monkeypatch, inventory_lookup_module, [FakeDoc(text=CONTACTOR)])

    assert await inventory_lookup(context=None, part_number="LC1D18") == CONTACTOR
