import asyncio
import logging
import textwrap

from dotenv import load_dotenv
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    JobContext,
    TurnHandlingOptions,
    cli,
    inference,
)
from livekit.plugins import groq

from tools.dispatch_status import dispatch_status
from tools.fault_history import fault_history
from tools.inventory_lookup import inventory_lookup
from tools.log_job_note import log_job_note
from tools.safety_procedure import safety_procedure

# Phase 4 additions -- offline-first pipeline and data layer.
from connectivity import connectivity
from local_pipeline import build_hybrid_llm, build_hybrid_stt, build_hybrid_tts, warm_up_local_stt
from moss_client import get_index

# Phase 5 addition -- multi-tenant company identity, resolved once per call
# from the room name. See company_context.py for the full explanation of
# why this uses a ContextVar instead of a function argument threaded
# through every tool.
from company_context import company_id_from_room_name, set_current_company, set_current_room_name

# Phase 6 addition -- every tool call now writes an entry to the
# company's audit log (see audit_log.py and each tools/*.py file).
# flush_all_buffers() catches up on anything logged while the backend was
# unreachable; start_periodic_flush() keeps retrying that catch-up in the
# background for as long as the session runs.
from audit_log import flush_all_buffers, start_periodic_flush

# Phase 7 addition -- LLM observability. Importing tracing here (before it's
# used below) is what triggers Phoenix registration at process startup; see
# tracing.py's module docstring for the graceful no-op fallback if Phoenix
# isn't running.
from tracing import record_stage_span

logger = logging.getLogger("fieldline-agent")

load_dotenv(".env.local")

FIELDLINE_INSTRUCTIONS = textwrap.dedent(
    """\
    # Capacity and Role
    You are FieldLine, an expert hands-free voice dispatch assistant
    embedded in a field technician's headset -- electrical maintenance,
    HVAC, elevator AMC, or telecom tower work -- with access to five tools
    backed by a live semantic index of job history, safety manuals, and
    inventory records.

    # Insight
    The technician's hands and eyes are occupied with physical work,
    possibly in a noisy room, possibly with no network at all. Every
    answer may inform a real safety decision. A wrong or invented answer
    costs more than no answer.

    # Statement
    Answer only from tool results. Never state a fact about equipment
    history, a part number, or a safety step that did not come back from a
    tool call in this conversation. If a tool returns nothing, say so
    plainly and suggest what to check next -- never guess.

    # Personality
    Respond in plain spoken text only. Never use markdown, lists, code,
    tables, or emojis. Keep replies short: one to three sentences for
    ordinary answers. Spell out numbers and unit IDs clearly (say "unit
    twelve", not "12"). Calm and direct, the way a competent radio
    dispatcher sounds.

    # Experiment (handling ambiguity)
    When a request doesn't give a tool what it needs (no equipment ID for
    fault_history, no clear topic for safety_procedure, no part name for
    inventory_lookup), do not ask an open-ended "what do you need help
    with." Ask for exactly the one missing detail, e.g. "Which unit or
    equipment ID are you working on?" or "What's the part number or part
    name?" Keep it to one short question, then proceed with the tool call.

    # Tools
    - fault_history: job and fault history for a piece of equipment.
    - safety_procedure: lockout / safety procedures. SAFETY-CRITICAL -- read
      the returned text back close to verbatim, in order, and always state
      the source manual and section. Never paraphrase or skip a step. If the
      tool says it isn't confident, tell the technician to confirm with a
      supervisor instead of guessing.
    - inventory_lookup: where a spare part is stored and how many are in stock.
    - dispatch_status: current job queue and any reroutes from dispatch.
    - log_job_note: logs a voice-dictated note against a job. Confirm back
      what you logged in one short sentence.

    # Negative constraints (safety-critical, non-negotiable)
    - Never paraphrase, summarize, or reorder text returned by
      safety_procedure -- read it back close to verbatim.
    - Never answer a lockout/safety question from memory -- always call
      the tool first, even if you believe you already know the answer.
    - Never invent a section number, manual name, part number, or job ID
      not present in a tool result.
    - On a low-confidence safety_procedure result, say so and refer the
      technician to a supervisor instead of guessing.

    See PROMPT_ENGINEERING.md for the full worked examples this structure
    is built from.
    """
)


class FieldLineAssistant(Agent):
    def __init__(self, *, llm) -> None:
        super().__init__(
            instructions=FIELDLINE_INSTRUCTIONS,
            llm=llm,
            tools=[
                fault_history,
                safety_procedure,
                inventory_lookup,
                dispatch_status,
                log_job_note,
            ],
        )


server = AgentServer()


@server.rtc_session(agent_name="fieldline-agent")
async def entrypoint(ctx: JobContext) -> None:
    # Phase 5: work out which company this call belongs to from the room
    # name (rooms are named "fieldline-<company_id>" by the dashboard /
    # whatever creates the room -- see company_context.py). This MUST run
    # before session.start() below, so every tool call triggered by this
    # session sees the right company via moss_client.get_index().
    company_id = company_id_from_room_name(ctx.room.name)
    set_current_company(company_id)
    # Phase 7: same ContextVar pattern, for tracing correlation ids -- see
    # tracing.py and company_context.py.
    set_current_room_name(ctx.room.name)

    ctx.log_context_fields = {
        "room": ctx.room.name,
        "company_id": company_id,
    }

    # Phase 4: hydrate the local Moss SessionIndex and start the
    # connectivity monitor *before* the call starts, so the first offline
    # query during a live conversation never has to wait on either one.
    # Phase 5: get_index() now hydrates THIS company's session, using the
    # company_id set just above.
    await get_index()
    connectivity.start()

    # Phase 6: flush any audit-log entries buffered from a previous run
    # (e.g. this process was restarted while offline, so the normal
    # offline -> online transition that triggers connectivity's
    # on_reconnect hook never fired), then keep retrying that flush every
    # 30s for the life of this session -- see audit_log.py.
    asyncio.create_task(flush_all_buffers())
    start_periodic_flush()

    # Phase 4: warm faster-whisper's model into the local cache now, while
    # we still have network -- otherwise the first time it's actually
    # needed (i.e. the moment you go offline) it tries to download itself
    # and fails with no internet to do it. Runs in the background so it
    # doesn't delay the greeting; give it ~10-20s before testing Wi-Fi-off.
    async def _warm_up_stt() -> None:
        try:
            await asyncio.get_event_loop().run_in_executor(None, warm_up_local_stt)
        except Exception:
            logger.exception(
                "could not warm up local STT model -- it will try (and fail) "
                "to download on first offline use instead. Run this once "
                "while online: uv run python -c \"from local_pipeline import "
                "warm_up_local_stt; warm_up_local_stt()\""
            )

    asyncio.create_task(_warm_up_stt())

    # Phase 4: warm Ollama's model into RAM now so the first offline LLM call
    # doesn't pay the 15-30s cold-start penalty (loading 2GB from disk).
    # The ping is fire-and-forget; failures are logged but never fatal.
    async def _warm_up_llm() -> None:
        try:
            import httpx as _httpx
            async with _httpx.AsyncClient(timeout=5) as c:
                await c.get("http://localhost:11434/api/tags")  # just check it's up
            # Send a trivial generation to load the model weights into VRAM/RAM
            from local_pipeline import build_local_llm
            from livekit.agents.llm import ChatContext
            _warm_llm = build_local_llm()
            _ctx = ChatContext()
            _ctx.add_message(role="user", content="Say OK")
            full = ""
            async with _warm_llm.chat(chat_ctx=_ctx) as stream:
                async for chunk in stream:
                    if chunk.delta and chunk.delta.content:
                        full += chunk.delta.content
                        break   # just need the first token; model is now hot
            logger.info("Ollama warm-up complete -- local LLM ready for offline use")
        except Exception:
            logger.warning(
                "Ollama warm-up failed -- local LLM will have a slow first response "
                "if you go offline before it loads. Make sure Ollama is running: "
                "ollama serve"
            )

    asyncio.create_task(_warm_up_llm())

    # Cloud providers -- unchanged from Phase 3.
    cloud_stt = groq.STT(model="whisper-large-v3-turbo", language="en")
    cloud_llm = groq.LLM(model="openai/gpt-oss-120b", reasoning_effort="low")
    cloud_tts = inference.TTS(
        model="fishaudio/s2.1-pro", voice="fa4c9eb3dccc4806b382b40d61c6b10a"
    )

    session = AgentSession(
        # Phase 4: each of these tries the cloud provider first and falls
        # back automatically to the local one (faster-whisper / Ollama /
        # Piper) on a real failure -- see local_pipeline.py. They also
        # auto-recover back to cloud once it's healthy again.
        stt=build_hybrid_stt(cloud_stt),
        tts=build_hybrid_tts(cloud_tts),
        turn_handling=TurnHandlingOptions(
            turn_detection=inference.TurnDetector(),
            interruption={"mode": "adaptive"},
            preemptive_generation={"enabled": True},
        ),
    )

    # Phase 7: record STT / LLM / TTS / end-of-utterance latency into
    # Phoenix, using LiveKit's own metrics_collected event rather than
    # wrapping the SDK calls ourselves. Defensive by design -- see
    # tracing.py's record_stage_span() and the comment below: LiveKit's
    # exact metrics field names can drift between versions (same caution
    # this repo already applies to LiveKit APIs generally -- see
    # .agents/skills/livekit-agents/references/freshness-rules.md), so
    # every field is read with getattr() and this handler can never raise
    # into the voice pipeline.
    def _on_metrics_collected(ev) -> None:
        try:
            m = ev.metrics
            stage = type(m).__name__  # e.g. "STTMetrics", "LLMMetrics", "TTSMetrics", "EOUMetrics"
            path = "online" if connectivity.is_online else "offline"

            duration_s = getattr(m, "duration", None)
            latency_ms = duration_s * 1000 if isinstance(duration_s, (int, float)) else None

            attrs: dict = {}
            prompt_tokens = getattr(m, "prompt_tokens", None)
            completion_tokens = getattr(m, "completion_tokens", None)
            if prompt_tokens is not None:
                attrs["prompt_tokens"] = prompt_tokens
            if completion_tokens is not None:
                attrs["completion_tokens"] = completion_tokens

            # Different metric types call this "ttft" (LLM) or "ttfb" (TTS)
            # depending on the installed livekit-agents version.
            time_to_first = getattr(m, "ttft", None)
            if time_to_first is None:
                time_to_first = getattr(m, "ttfb", None)
            if isinstance(time_to_first, (int, float)):
                attrs["time_to_first_ms"] = time_to_first * 1000

            record_stage_span(stage, ctx.room.name, path, latency_ms, **attrs)
        except Exception:
            logger.exception("failed to process metrics_collected event (call was unaffected)")

    session.on("metrics_collected", _on_metrics_collected)

    await session.start(
        agent=FieldLineAssistant(llm=build_hybrid_llm(cloud_llm)),
        room=ctx.room,
    )

    await ctx.connect()

    # Short audible greeting so you can confirm the pipeline is live before
    # asking anything -- easy sanity check for both Phase 3 and Phase 4.
    await session.generate_reply(
        instructions=(
            "Greet the technician briefly, e.g. 'FieldLine here, go ahead.' "
            "Keep it to one short sentence."
        )
    )


if __name__ == "__main__":
    cli.run_app(server)