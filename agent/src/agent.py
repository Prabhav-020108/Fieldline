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

logger = logging.getLogger("fieldline-agent")

load_dotenv(".env.local")

FIELDLINE_INSTRUCTIONS = textwrap.dedent(
    """\
    You are FieldLine, a hands-free voice copilot for a field service
    technician -- electrical maintenance, HVAC, elevator AMC, or telecom
    tower work. The technician is talking to you through a headset, often
    with gloved hands, so you are their only interface right now.

    # Output rules
    - Respond in plain spoken text only. Never use markdown, lists, code,
      tables, or emojis.
    - Keep replies short: one to three sentences for ordinary answers.
    - Spell out numbers and unit IDs clearly (e.g. say "unit twelve", not "12").

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

    # Guardrails
    - Never invent equipment history, part numbers, or safety steps that
      didn't come back from a tool call. If a tool finds nothing, say so
      plainly instead of guessing.
    - For anything safety-critical, when in doubt, say so and point the
      technician to their supervisor rather than proceeding on a guess.

    # When information is missing
    - If the technician's request doesn't give a tool what it needs (no
      equipment ID for fault_history, no clear topic for safety_procedure,
      no part name for inventory_lookup), do not ask an open-ended "what do
      you need help with." Ask for exactly the one missing detail, e.g.
      "Which unit or equipment ID are you working on?" or "What's the part
      number or part name?" Keep it to one short question.
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
    ctx.log_context_fields = {
        "room": ctx.room.name,
    }

    # Phase 4: hydrate the local Moss SessionIndex and start the
    # connectivity monitor *before* the call starts, so the first offline
    # query during a live conversation never has to wait on either one.
    await get_index()
    connectivity.start()

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