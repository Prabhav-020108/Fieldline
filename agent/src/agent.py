import asyncio
import logging
import os
import textwrap
import time

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

# Phase 8d addition -- one shared, durable, retrying outbound queue for
# audit-log entries and queued Moss writes.
import audit_log  # noqa: F401
import sync_queue

# Phase 5 addition -- multi-tenant company identity, resolved once per call
# from the room name.
from company_context import (
    company_id_from_room_name,
    set_current_company,
    set_current_role,
    set_current_room_name,
)

# Phase 4 additions -- offline-first pipeline and data layer.
from connectivity import connectivity
from local_pipeline import (
    build_hybrid_llm,
    build_hybrid_stt,
    build_hybrid_tts,
    build_local_llm,
    build_local_stt,
    build_local_tts,
    warm_up_local_stt,
)
from moss_client import get_index

# Phase 8c addition -- offline-capable role verification.
from role_cache import verify_role_token
from settings import settings
from tools.dispatch_status import dispatch_status
from tools.fault_history import fault_history
from tools.inventory_lookup import inventory_lookup
from tools.log_job_note import log_job_note
from tools.safety_procedure import safety_procedure

# Phase 7 addition -- LLM observability.
from tracing import record_stage_span

logger = logging.getLogger("fieldline-agent")

# Observability: Sentry error tracking if configured
if settings.sentry_dsn:
    try:
        import sentry_sdk
        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            traces_sample_rate=1.0,
            environment=settings.environment,
        )
        logger.info("Sentry monitoring initialized (env=%s)", settings.environment)
    except Exception as e:
        logger.warning("Could not initialize Sentry: %s", e)

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
            from livekit.agents.llm import ChatContext

            from local_pipeline import build_local_llm
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

    is_edge_mode = os.environ.get("FIELDLINE_EDGE_MODE") == "1"
    configured_livekit_url = os.environ.get("LIVEKIT_URL", "wss://fieldline-y34tzh74.livekit.cloud")

    if is_edge_mode:
        logger.info("=" * 65)
        logger.info("  FIELDLINE AGENT: EDGE MODE ACTIVE (100% Offline / Local)")
        logger.info("  LiveKit URL: %s", configured_livekit_url)
        logger.info("  STT: faster-whisper (local CPU)")
        logger.info("  LLM: Ollama %s (%s)", os.environ.get("OLLAMA_MODEL", "llama3.2:3b"), os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1"))
        logger.info("  TTS: Piper Neural TTS (%s)", os.environ.get("PIPER_TTS_BASE_URL", "http://localhost:8880/v1"))
        logger.info("=" * 65)

        # Quick pre-flight check for local Piper TTS server
        try:
            import urllib.request
            urllib.request.urlopen("http://localhost:8880/health", timeout=1.0)
        except Exception:
            logger.warning(
                "\n"
                "********************************************************************************\n"
                "WARNING: Local Piper TTS server at http://localhost:8880 is NOT responding!\n"
                "  -> If you are presenting the ZERO-INTERNET EDGE DEMO (Phone/Offline):\n"
                "     Start Piper in another terminal: uv run python src/local_tts_server.py\n\n"
                "  -> If you intended to run the PRIMARY CLOUD DEMO (Laptop/Pitch):\n"
                "     Your PowerShell session still has FIELDLINE_EDGE_MODE=1 set from earlier!\n"
                "     Run: Remove-Item env:FIELDLINE_EDGE_MODE, env:LIVEKIT_URL\n"
                "     Then restart: uv run python src/agent.py dev\n"
                "     (Or simply run: .\\start-cloud.ps1 -Component agent)\n"
                "********************************************************************************\n"
            )

        session = AgentSession(
            stt=build_local_stt(),
            tts=build_local_tts(),
            turn_handling=TurnHandlingOptions(
                turn_detection=inference.TurnDetector(),
                interruption={"mode": "adaptive"},
                preemptive_generation={"enabled": True},
            ),
        )
        active_llm = build_local_llm()
    else:
        logger.info("=" * 65)
        logger.info("  FIELDLINE AGENT: PRIMARY CLOUD DEMO MODE ACTIVE")
        logger.info("  LiveKit Cloud: %s", configured_livekit_url)
        logger.info("  STT: Groq Whisper Large v3 Turbo")
        logger.info("  LLM: Groq 120B (openai/gpt-oss-120b)")
        logger.info("  TTS: Cartesia Sonic-3 (LiveKit Cloud Inference)")
        logger.info("=" * 65)

        if "localhost" in configured_livekit_url or "127.0.0.1" in configured_livekit_url:
            logger.warning(
                "\n"
                "********************************************************************************\n"
                "NOTICE: LIVEKIT_URL is currently set to '%s' (local server),\n"
                "        but you are running in Cloud Mode (expecting LiveKit Cloud)!\n"
                "  If you intended to connect to LiveKit Cloud for your primary demo, run:\n"
                "    Remove-Item env:LIVEKIT_URL\n"
                "  in your PowerShell terminal before running the agent.\n"
                "********************************************************************************\n",
                configured_livekit_url,
            )

        cloud_stt = groq.STT(model="whisper-large-v3-turbo", language="en")
        cloud_llm = groq.LLM(model="openai/gpt-oss-120b", reasoning_effort="low")
        cloud_tts = inference.TTS(
            model="cartesia/sonic-3",
            fallback=[
                {
                    "model": "fishaudio/s2.1-pro",
                    "voice": "fa4c9eb3dccc4806b382b40d61c6b10a",
                }
            ],
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
        active_llm = build_hybrid_llm(cloud_llm)

    # Phase 8f: tell the technician, once, briefly, whenever the
    # connectivity path actually changes -- never silently.
    #
    # Debounce: connectivity.py's mark_offline()/mark_online() already
    # guard against firing callbacks on a non-transition, but multiple
    # rapid failures (e.g. audit_log POST + sync_queue startup both
    # failing within ms of each other) can each cause their own
    # mark_offline() call before the first callback has even started.
    # The _ANNOUNCE_COOLDOWN_S window below is a second, cheap safety net
    # that prevents the technician from hearing the same announcement
    # multiple times in one go.
    announce_cooldown_s = 15.0
    _last_offline_announce: float = 0.0
    _last_online_announce: float = 0.0

    async def _announce_offline() -> None:
        nonlocal _last_offline_announce
        now = time.monotonic()
        if now - _last_offline_announce < announce_cooldown_s:
            logger.debug("offline announcement debounced (%.1fs since last)", now - _last_offline_announce)
            return
        _last_offline_announce = now
        try:
            handle = session.say(
                "Heads up, I've lost the link to dispatch -- running on locally cached data.",
                add_to_chat_ctx=False,
            )
            await handle.wait_if_not_interrupted()
        except Exception:
            logger.exception("failed to announce offline transition (call was unaffected)")

    async def _announce_reconnect() -> None:
        nonlocal _last_online_announce
        now = time.monotonic()
        if now - _last_online_announce < announce_cooldown_s:
            logger.debug("reconnect announcement debounced (%.1fs since last)", now - _last_online_announce)
            return
        _last_online_announce = now
        try:
            handle = session.say(
                "Good news, I'm reconnected to dispatch -- data is live again.",
                add_to_chat_ctx=False,
            )
            await handle.wait_if_not_interrupted()
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
        agent=FieldLineAssistant(llm=active_llm),
        room=ctx.room,
    )

    await ctx.connect()

    # Phase 8c: verify the calling participant's role token locally (no
    # network call -- see role_cache.py) and stash the verified role for
    # the rest of this call. Fast-path: check if participant is already present
    # in the room, else wait with a short 1.5s timeout so greeting starts immediately.
    role = "technician"
    remote = next(iter(ctx.room.remote_participants.values()), None)
    if remote and remote.metadata:
        try:
            role = verify_role_token(remote.metadata, settings.fieldline_jwt_secret, company_id)
        except Exception:
            role = "technician"
    else:
        try:
            participant = await asyncio.wait_for(ctx.wait_for_participant(), timeout=1.5)
            if participant and participant.metadata:
                role = verify_role_token(participant.metadata, settings.fieldline_jwt_secret, company_id)
        except Exception:
            pass

    def _on_participant_metadata_changed(p, _prev):
        if p.metadata:
            try:
                new_role = verify_role_token(p.metadata, settings.fieldline_jwt_secret, company_id)
                set_current_role(new_role)
                logger.info("call role dynamically updated for %s: %s", p.identity, new_role)
            except Exception:
                pass

    ctx.room.on("participant_metadata_changed", _on_participant_metadata_changed)
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
