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
    """
)


class FieldLineAssistant(Agent):
    def __init__(self) -> None:
        super().__init__(
            instructions=FIELDLINE_INSTRUCTIONS,
            # Online path (Phase 3), deliberate choice: swap the LLM to Groq.
            # Groq's inference speed matters most right here, since
            # tool-calling latency (LLM decides to call a tool, waits on it,
            # then composes the spoken reply) is usually the slowest link in
            # a voice loop. STT is swapped to Groq below for the same reason.
            # TTS is left on the starter's default (LiveKit Inference /
            # fishaudio) since it's already fast and zero-config -- no need
            # to touch what isn't the bottleneck.
            llm=groq.LLM(model="openai/gpt-oss-120b", reasoning_effort="low"),
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

    session = AgentSession(
        # Swapped to Groq-hosted Whisper for the online path (see PRD).
        stt=groq.STT(model="whisper-large-v3-turbo", language="en"),
        # Left on the starter's default TTS -- not the latency bottleneck.
        tts=inference.TTS(
            model="fishaudio/s2.1-pro", voice="fa4c9eb3dccc4806b382b40d61c6b10a"
        ),
        turn_handling=TurnHandlingOptions(
            turn_detection=inference.TurnDetector(),
            interruption={"mode": "adaptive"},
            preemptive_generation={"enabled": True},
        ),
    )

    await session.start(
        agent=FieldLineAssistant(),
        room=ctx.room,
    )

    await ctx.connect()

    # Short audible greeting so you can confirm the pipeline is live before
    # asking anything -- easy sanity check for Phase 3.
    await session.generate_reply(
        instructions=(
            "Greet the technician briefly, e.g. 'FieldLine here, go ahead.' "
            "Keep it to one short sentence."
        )
    )


if __name__ == "__main__":
    cli.run_app(server)
