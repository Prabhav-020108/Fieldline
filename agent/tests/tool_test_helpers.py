"""
Small fakes shared by the agent tool tests (fault_history, inventory_lookup,
dispatch_status, log_job_note).

This file is NOT a test file (its name doesn't start with "test_"), so pytest
doesn't run it -- the test files import from it.

Every tool follows the same pattern:

    client, index_name = await get_index()        # gets the Moss client
    results = await client.query(...)             # searches it
    ...
    log_tool_call_background(...)                 # writes an audit entry

install_fakes() swaps the first and last of those for in-memory fakes, so a
test can (a) decide exactly which documents "Moss" returns and (b) inspect
exactly what the tool tried to log -- with no network and no backend.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FakeDoc:
    """What a Moss search hit looks like to the tools: .text .score .metadata"""

    text: str
    score: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class FakeResults:
    docs: list[FakeDoc]


class FakeMossClient:
    """Stands in for MossRouter. Records every query and every write."""

    def __init__(self, docs: list[FakeDoc]) -> None:
        self._docs = docs
        self.queries: list[tuple[str, str, Any]] = []  # (index_name, text, options)
        self.added: list[dict[str, Any]] = []  # one entry per add_docs() call

    async def query(self, index_name, text, options):
        self.queries.append((index_name, text, options))
        return FakeResults(docs=self._docs)

    async def add_docs(self, index_name, docs, mutation_options=None):
        self.added.append(
            {"index_name": index_name, "docs": list(docs), "mutation_options": mutation_options}
        )


def install_fakes(monkeypatch, tool_module, docs: list[FakeDoc]):
    """Patch `tool_module` (e.g. tools.fault_history) so that:

      - get_index() returns a FakeMossClient that answers with `docs`
      - log_tool_call_background(...) appends to a list instead of scheduling
        a real network call

    Returns (client, audit_calls).
    """
    client = FakeMossClient(docs)
    audit_calls: list[dict[str, Any]] = []

    async def _fake_get_index():
        return client, "fake-index"

    def _fake_log(tool_name, query_text, response_text, **kwargs):
        audit_calls.append(
            {
                "tool_name": tool_name,
                "query_text": query_text,
                "response_text": response_text,
                **kwargs,
            }
        )

    monkeypatch.setattr(tool_module, "get_index", _fake_get_index)
    monkeypatch.setattr(tool_module, "log_tool_call_background", _fake_log)
    return client, audit_calls
