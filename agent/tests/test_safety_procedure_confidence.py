"""
Tests for the Phase 6 tunable confidence floor on safety_procedure, plus
confirming audit entries are logged with the right confidence/citation
fields for both the "confident" and "below floor" paths.

These mock out get_index() and log_tool_call_background() directly, so no
real Moss connection or backend is needed to run them.

    uv run pytest tests/test_safety_procedure_confidence.py -v
"""

from dataclasses import dataclass, field
from typing import Any

import pytest

import tools.safety_procedure as safety_procedure_module
from tools.safety_procedure import safety_procedure


@dataclass
class _FakeDoc:
    text: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class _FakeResults:
    docs: list[_FakeDoc]


class _FakeClient:
    def __init__(self, docs: list[_FakeDoc]) -> None:
        self._docs = docs

    async def query(self, index_name, text, options):
        return _FakeResults(docs=self._docs)


@pytest.fixture
def captured_audit_calls(monkeypatch):
    """Replaces log_tool_call_background with a spy that records every
    call instead of actually scheduling a background asyncio task, so
    tests can assert on exactly what would have been sent to the audit
    log without needing a running event loop task or a real backend."""
    calls: list[dict] = []

    def _fake_log(tool_name, query_text, response_text, **kwargs):
        calls.append(
            {
                "tool_name": tool_name,
                "query_text": query_text,
                "response_text": response_text,
                **kwargs,
            }
        )

    monkeypatch.setattr(safety_procedure_module, "log_tool_call_background", _fake_log)
    return calls


def _patch_index(monkeypatch, docs: list[_FakeDoc]):
    async def _fake_get_index():
        return _FakeClient(docs), "fake-index"

    monkeypatch.setattr(safety_procedure_module, "get_index", _fake_get_index)


async def test_confident_answer_is_read_back_with_citation(monkeypatch, captured_audit_calls):
    monkeypatch.setattr(safety_procedure_module, "CONFIDENCE_FLOOR", 0.35)
    _patch_index(
        monkeypatch,
        [
            _FakeDoc(
                text="Section 4.2 - Panel B Lockout: (1) Notify affected personnel...",
                score=0.82,
                metadata={"source_manual": "Site Electrical Safety Manual", "section": "4.2"},
            )
        ],
    )

    result = await safety_procedure(context=None, topic="panel B lockout")

    assert "Section 4.2" in result
    assert "Site Electrical Safety Manual, Section 4.2" in result

    assert len(captured_audit_calls) == 1
    call = captured_audit_calls[0]
    assert call["tool_name"] == "safety_procedure"
    assert call["confidence_score"] == pytest.approx(0.82)
    assert call["below_confidence_floor"] is False
    assert call["source_citation"] == "Site Electrical Safety Manual, Section 4.2"


async def test_low_confidence_defers_to_supervisor_and_logs_floor_trip(
    monkeypatch, captured_audit_calls
):
    monkeypatch.setattr(safety_procedure_module, "CONFIDENCE_FLOOR", 0.35)
    _patch_index(
        monkeypatch,
        [_FakeDoc(text="some tangentially related passage", score=0.10, metadata={})],
    )

    result = await safety_procedure(context=None, topic="obscure equipment nobody has")

    assert "confirm the exact steps with your supervisor" in result
    assert "Section" not in result  # never reads back low-confidence content

    assert len(captured_audit_calls) == 1
    call = captured_audit_calls[0]
    assert call["below_confidence_floor"] is True
    assert call["confidence_score"] == pytest.approx(0.10)


async def test_raising_the_confidence_floor_makes_the_agent_more_cautious(
    monkeypatch, captured_audit_calls
):
    """A score that would have passed the Phase 2-5 default (0.35) should
    now fail once SAFETY_CONFIDENCE_FLOOR is tuned higher, proving the
    threshold is a live variable read at call time -- not a value baked
    into the module at import time that .env.local can no longer affect."""
    monkeypatch.setattr(safety_procedure_module, "CONFIDENCE_FLOOR", 0.6)
    _patch_index(
        monkeypatch,
        [
            _FakeDoc(
                text="Section 4.1 - Panel A Lockout: follows the same six-step sequence...",
                score=0.42,  # would have passed the old 0.35 floor
                metadata={"source_manual": "Site Electrical Safety Manual", "section": "4.1"},
            )
        ],
    )

    result = await safety_procedure(context=None, topic="panel A lockout")

    assert "confirm the exact steps with your supervisor" in result
    assert captured_audit_calls[0]["below_confidence_floor"] is True


async def test_no_matching_document_logs_a_null_confidence_score(
    monkeypatch, captured_audit_calls
):
    _patch_index(monkeypatch, [])

    result = await safety_procedure(context=None, topic="something not indexed at all")

    assert "Don't proceed from memory" in result
    assert captured_audit_calls[0]["confidence_score"] is None
    assert captured_audit_calls[0]["below_confidence_floor"] is True
