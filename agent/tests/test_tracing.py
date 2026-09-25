from unittest.mock import MagicMock

import tracing


def test_prompt_hash():
    h1 = tracing.prompt_hash("What is the lockout procedure for panel B?")
    h2 = tracing.prompt_hash("What is the lockout procedure for panel B?")
    h3 = tracing.prompt_hash("Different query")

    assert isinstance(h1, str)
    assert len(h1) == 12
    assert h1 == h2
    assert h1 != h3

    # Empty text handling
    empty_hash = tracing.prompt_hash("")
    assert len(empty_hash) == 12


def test_check_latency_budget_within_budget():
    mock_span = MagicMock()
    # Online budget is 1000ms. 500ms is well within.
    tracing._check_latency_budget(mock_span, "retrieval", "online", 500.0)
    mock_span.add_event.assert_not_called()


def test_check_latency_budget_exceeded():
    mock_span = MagicMock()
    # Online budget is 1000ms. 1500ms exceeds.
    tracing._check_latency_budget(mock_span, "retrieval", "online", 1500.0)
    mock_span.add_event.assert_called_once_with(
        "latency_threshold_exceeded",
        {"budget_ms": 1000.0, "actual_ms": 1500.0},
    )


def test_check_latency_budget_offline_path():
    mock_span = MagicMock()
    # Offline budget is 2500ms. 2000ms passes, 3000ms exceeds.
    tracing._check_latency_budget(mock_span, "llm", "offline", 2000.0)
    mock_span.add_event.assert_not_called()

    tracing._check_latency_budget(mock_span, "llm", "offline", 3000.0)
    mock_span.add_event.assert_called_once_with(
        "latency_threshold_exceeded",
        {"budget_ms": 2500.0, "actual_ms": 3000.0},
    )


def test_traced_stage_context_manager():
    with tracing.traced_stage("retrieval", "room-123", "online", tool="fault_history") as span:
        assert span is not None


def test_record_stage_span():
    # Calling with valid latency
    tracing.record_stage_span("stt", "room-123", "online", 450.0, prompt_tokens=10)

    # Calling with None latency should not raise
    tracing.record_stage_span("stt", "room-123", "online", None)


def test_noop_tracer_and_span():
    noop = tracing._NoOpTracer()
    with noop.start_as_current_span("test") as span:
        span.set_attribute("key", "val")
        span.add_event("event", {"data": 1})
