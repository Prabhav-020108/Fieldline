import asyncio
import logging
import os
import textwrap

from dotenv import load_dotenv

# Load .env.local FIRST, before any local module below is imported --
# several of them (settings.py, and anything that imports it) now read
# required env vars at import time, and need this to have already run.
load_dotenv(".env.local")

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
# from the room name.
from company_context import (
    company_id_from_room_name,
    set_current_company,
    set_current_role,
    set_current_room_name,
)

# Phase 8d addition -- one shared, durable, retrying outbound queue for
# audit-log entries and queued Moss writes. Importing audit_log and
# moss_client above already registers their sync_queue handlers; this
# import is just for sync_queue.start() below.
import sync_queue

# Phase 8c addition -- offline-capable role verification.
from role_cache import verify_role_token
from settings import settings

# Phase 7 addition -- LLM observability.
from tracing import record_stage_span

logger = logging.getLogger("fieldline-agent")

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

    # State Awareness
    When your connection to the dispatch server changes -- online to
    offline, or back -- say so once, briefly, before continuing with the
    technician's actual question. Voice itself is unaffected, so don't
    imply you've gone fully offline. Never mention it again mid-conversation
    unless it changes again.

    # Tools
    - fault_history: job and fault history for a piece of equipment.
    - safety_procedure: lockout / safety procedures. SAFETY-CRITICAL -- read
      the returned text back close to verbatim, in order, and always state
      the source manual and section. Never paraphrase or skip a step. If the
      tool says it isn't confident, tell the technician to confirm with a
      supervisor instead of guessing.
    - inventory_lookup: where a spare part is stored and how many are in stock.
    - dispatch_status: current job queue and any reroutes from dispatch.
    - log_job_note: logs a voice-dictated note against a job. If the
      technician says the job is done or resolved, pass that along -- the
      tool itself decides whether their role is allowed to close it.
      Confirm back what you logged in one short sentence.

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


server = AgentServer(initialize_process_timeout=90.0)


@server.rtc_session(agent_name="fieldline-agent")
async def entrypoint(ctx: JobContext) -> None:
    company_id = company_id_from_room_name(ctx.room.name)
    set_current_company(company_id)
    set_current_room_name(ctx.room.name)

    ctx.log_context_fields = {
        "room": ctx.room.name,
        "company_id": company_id,
    }

    # Phase 4: hydrate the local Moss SessionIndex and start the
    # connectivity monitor *before* the call starts.
    await get_index()
    connectivity.start()

    # Phase 8d: catch up on anything queued from a previous run, keep
    # retrying every 30s for the life of this session, and hot-swap back
    # the instant real connectivity returns -- see sync_queue.py.
    sync_queue.start()

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

    # Phase 10: the LiveKit Cloud container has no offline path to warm up
    # (no Ollama, no Piper server), so the deployed agent skips both
    # warm-ups. Locally this variable is unset and nothing changes.
    if os.environ.get("FIELDLINE_CLOUD_DEPLOY") != "1":
        asyncio.create_task(_warm_up_stt())

    async def _warm_up_llm() -> None:
        try:
            import httpx as _httpx
            async with _httpx.AsyncClient(timeout=5) as c:
                await c.get("http://localhost:11434/api/tags")
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
                        break
            logger.info("Ollama warm-up complete -- local LLM ready for offline use")
        except Exception:
            logger.warning(
                "Ollama warm-up failed -- local LLM will have a slow first response "
                "if you go offline before it loads. Make sure Ollama is running: "
                "ollama serve"
            )

    if os.environ.get("FIELDLINE_CLOUD_DEPLOY") != "1":
        asyncio.create_task(_warm_up_llm())

    cloud_stt = groq.STT(model="whisper-large-v3-turbo", language="en")
    cloud_llm = groq.LLM(model="openai/gpt-oss-120b", reasoning_effort="low")
    cloud_tts = inference.TTS(
        model="fishaudio/s2.1-pro", voice="fa4c9eb3dccc4806b382b40d61c6b10a"
    )

    session = AgentSession(
        stt=build_hybrid_stt(cloud_stt),
        tts=build_hybrid_tts(cloud_tts),
        turn_handling=TurnHandlingOptions(
            turn_detection=inference.TurnDetector(),
            interruption={"mode": "adaptive"},
            preemptive_generation={"enabled": True},
        ),
    )

    # Phase 8f: tell the technician, once, briefly, whenever the
    # connectivity path actually changes -- never silently. Both handlers
    # only fire on a genuine transition (connectivity.py's
    # mark_offline()/mark_online() already de-duplicate this).
    async def _announce_offline() -> None:
        try:
            await session.generate_reply(
                instructions=(
                    "Briefly tell the technician you've lost the connection to the "
                    "dispatch server and are now running on locally cached job "
                    "data -- one short sentence, e.g. 'Heads up, I've lost the "
                    "link to dispatch -- job history and inventory might be a few "
                    "minutes stale until I reconnect.' Voice itself is unaffected, "
                    "so don't imply you've gone fully offline. Then continue normally."
                )
            )
        except Exception:
            logger.exception("failed to announce offline transition (call was unaffected)")

    async def _announce_reconnect() -> None:
        try:
            await session.generate_reply(
                instructions=(
                    "Briefly tell the technician you're reconnected to the "
                    "dispatch server -- one short sentence, e.g. 'Good news, I'm "
                    "reconnected to dispatch -- job history and inventory are "
                    "live again.' Voice itself is unaffected. Then continue normally."
                )
            )
        except Exception:
            logger.exception("failed to announce reconnect (call was unaffected)")

    connectivity.on_disconnect(_announce_offline)
    connectivity.on_reconnect(_announce_reconnect)

    def _on_metrics_collected(ev) -> None:
        try:
            m = ev.metrics
            stage = type(m).__name__
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

    # Phase 8c: verify the calling participant's role token locally (no
    # network call -- see role_cache.py) and stash the verified role for
    # the rest of this call. Wrapped defensively: any failure here (no
    # participant, a bad token, taking too long) falls back to
    # "technician" -- least privilege -- rather than blocking the call.
    try:
        participant = await asyncio.wait_for(ctx.wait_for_participant(), timeout=10.0)
        role = verify_role_token(participant.metadata, settings.fieldline_jwt_secret, company_id)
    except Exception:
        logger.warning(
            "could not read a call-role token from the connecting participant "
            "-- continuing as 'technician' (least privilege)",
            exc_info=True,
        )
        role = "technician"
    set_current_role(role)
    logger.info("call role for this session: %s", role)

    # Short audible greeting so you can confirm the pipeline is live before
    # asking anything.
    await session.generate_reply(
        instructions=(
            "Greet the technician briefly, e.g. 'FieldLine here, go ahead.' "
            "Keep it to one short sentence."
        )
    )


if __name__ == "__main__":
    cli.run_app(server)