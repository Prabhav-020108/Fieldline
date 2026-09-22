"""
Phase 7: LLM observability for FieldLine's voice agent, via OpenTelemetry
exported to a locally self-hosted Arize Phoenix instance.

Design goals (build plan Phase 7a and 7e):

  - Every pipeline stage (STT, LLM, TTS, and Moss retrieval) gets its own
    span, tagged with a correlation_id and a `path` attribute ("online" or
    "offline"), so a supervisor can filter Phoenix's trace view down to
    e.g. "show me every offline-path LLM call" or "show me this one call,
    start to finish."
  - LLM/STT/TTS spans are recorded from LiveKit AgentSession's own
    `metrics_collected` event (see agent.py) rather than by wrapping the
    SDK calls ourselves -- LiveKit already measures these accurately
    end-to-end, including whichever FallbackAdapter branch actually served
    the call, so re-measuring them would be redundant and more fragile.
  - Moss retrieval spans (the stage FieldLine owns end-to-end) are
    recorded with traced_stage() at the call site in each tools/*.py file.
  - Any span whose latency busts LATENCY_BUDGET_MS for its path gets an
    explicit `latency_threshold_exceeded` event attached (Phase 7e) --
    visible and filterable in Phoenix, not just a log line.
  - Observability must never be able to take down a voice call. Every
    public function here is defensive: if Phoenix isn't running, if
    `arize-phoenix` isn't installed, or if a metrics object's fields don't
    match what this file expects (LiveKit's metrics schema is
    verify-before-trusting territory -- see
    .agents/skills/livekit-agents/references/freshness-rules.md), this
    module falls back to a no-op tracer rather than raising.

Run Phoenix locally before starting the agent:

    uv run python -m phoenix.server.main serve

Then open http://localhost:6006 to watch traces arrive as calls come in.
If traces don't show up and Phoenix is running on a non-default host/port,
set PHOENIX_COLLECTOR_ENDPOINT in .env.local (see .env.example).

CORRELATION GRANULARITY: correlation_id is set once per call (the LiveKit
room name, via company_context.set_current_room_name()), not once per
conversational turn. That's coarser than "one full turn end-to-end" but
still lets you pull up every span from one call in Phoenix, which is
enough to diagnose an offline-path issue after a demo or a real shift.
Narrowing this to per-turn would mean hooking LiveKit's turn-taking events
directly -- a reasonable future refinement, out of scope for this phase.
"""

import hashlib
import logging
import os
import time
from contextlib import contextmanager

logger = logging.getLogger("fieldline.tracing")

# Matches the latency budget stated in the PRD's NFR-02 / NFR-03.
LATENCY_BUDGET_MS = {"online": 1000.0, "offline": 2500.0}

PHOENIX_PROJECT_NAME = os.environ.get("PHOENIX_PROJECT_NAME", "fieldline-agent")


class _NoOpSpan:
    """Stand-in for an OpenTelemetry span when Phoenix isn't available, so
    every call site can call span.set_attribute(...)/span.add_event(...)
    unconditionally without an `if tracer_enabled:` check everywhere."""

    def set_attribute(self, *args, **kwargs) -> None:
        pass

    def add_event(self, *args, **kwargs) -> None:
        pass


class _NoOpTracer:
    @contextmanager
    def start_as_current_span(self, *args, **kwargs):
        yield _NoOpSpan()


_TRACING_DISABLED = os.environ.get("OTEL_SDK_DISABLED", "").lower() == "true"


def _build_tracer():
    """Try to stand up a real Phoenix/OpenTelemetry tracer. Falls back to
    a no-op tracer on ANY failure -- a missing `arize-phoenix` install, no
    Phoenix server listening, or a version mismatch should degrade
    observability, never block the voice pipeline from starting."""
    if _TRACING_DISABLED:
        logger.info("OTEL_SDK_DISABLED=true -- skipping the arize-phoenix import entirely")
        return _NoOpTracer()

    try:
        from phoenix.otel import register

        tracer_provider = register(
            project_name=PHOENIX_PROJECT_NAME,
            auto_instrument=True,  # picks up any installed openinference-instrumentation-* package
            batch=True,
        )
        logger.info(
            "Phoenix tracing enabled (project=%r). If you don't see traces "
            "at http://localhost:6006, make sure `uv run python -m "
            "phoenix.server.main serve` is running in its own window.",
            PHOENIX_PROJECT_NAME,
        )
        return tracer_provider.get_tracer("fieldline")
    except Exception:
        logger.warning(
            "Phoenix tracing unavailable (arize-phoenix not installed, or "
            "no Phoenix server reachable) -- continuing WITHOUT "
            "observability. Voice calls are unaffected. Run `uv sync` and "
            "`uv run python -m phoenix.server.main serve` to enable it.",
            exc_info=True,
        )
        return _NoOpTracer()


tracer = _build_tracer()


def prompt_hash(text: str) -> str:
    """Short, stable hash of a prompt/query so you can spot drift across
    runs in Phoenix without logging full prompt text on every span."""
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:12]


def _check_latency_budget(span, stage: str, path: str, latency_ms: float) -> None:
    budget = LATENCY_BUDGET_MS.get(path)
    if budget is not None and latency_ms > budget:
        span.add_event(
            "latency_threshold_exceeded",
            {"budget_ms": budget, "actual_ms": latency_ms},
        )
        logger.warning(
            "%s stage on %s path took %.0fms (budget %dms)",
            stage,
            path,
            latency_ms,
            budget,
        )


@contextmanager
def traced_stage(stage: str, correlation_id: str, path: str, **attrs):
    """Wrap a pipeline stage FieldLine calls directly (currently: Moss
    retrieval, inside tools/*.py). Times itself and flags any span that
    exceeds this path's latency budget -- see LATENCY_BUDGET_MS above.

    Usage:
        with traced_stage("retrieval", correlation_id, path,
                           tool="fault_history", query_hash=prompt_hash(topic)) as span:
            results = await client.query(...)
            span.set_attribute("fieldline.result_count", len(results.docs))
    """
    start = time.perf_counter()
    with tracer.start_as_current_span(stage) as span:
        span.set_attribute("fieldline.correlation_id", correlation_id)
        span.set_attribute("fieldline.path", path)
        for key, value in attrs.items():
            span.set_attribute(f"fieldline.{key}", value)
        try:
            yield span
        finally:
            latency_ms = (time.perf_counter() - start) * 1000
            span.set_attribute("fieldline.latency_ms", latency_ms)
            _check_latency_budget(span, stage, path, latency_ms)


def record_stage_span(
    stage: str, correlation_id: str, path: str, latency_ms: "float | None", **attrs
) -> None:
    """Record a pipeline stage whose latency LiveKit already measured for
    us (STT / LLM / TTS, via AgentSession's `metrics_collected` event --
    see agent.py). Unlike traced_stage(), this doesn't time anything
    itself; it opens a span, stamps it with the already-known latency, and
    closes it immediately.

    latency_ms may be None if the underlying metrics object didn't expose
    a duration field FieldLine recognized -- the span is still recorded
    (with correlation id, path, and whatever attrs were passed), just
    without a latency figure or a budget check.
    """
    try:
        with tracer.start_as_current_span(stage) as span:
            span.set_attribute("fieldline.correlation_id", correlation_id)
            span.set_attribute("fieldline.path", path)
            for key, value in attrs.items():
                if value is not None:
                    span.set_attribute(f"fieldline.{key}", value)
            if latency_ms is not None:
                span.set_attribute("fieldline.latency_ms", latency_ms)
                _check_latency_budget(span, stage, path, latency_ms)
    except Exception:
        # Observability must never break a voice call -- see module docstring.
        logger.exception("failed to record %s span (call was unaffected)", stage)