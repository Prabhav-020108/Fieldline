"""
Builds the offline/local half of FieldLine's voice pipeline:

  - STT:  faster-whisper, running on CPU, fully local
  - LLM:  Ollama, reached through LiveKit's OpenAI-compatible plugin
  - TTS:  Piper, reached through local_tts_server.py's OpenAI-compatible
          endpoint, using that same plugin

None of these three ever touch the network. They get combined with the
existing cloud providers (Groq STT/LLM, LiveKit Inference TTS) using
LiveKit's built-in FallbackAdapter for each modality -- see
build_hybrid_stt / build_hybrid_llm / build_hybrid_tts below, and agent.py
for how they're wired into AgentSession.

FallbackAdapter tries the first item in its list first (the cloud provider),
and only falls to the next item on a real failure or timeout. It also
periodically re-probes the failed provider in the background and switches
back automatically once it's healthy again -- this is what gives us the
"hot-swap back to cloud on reconnect" behaviour for the voice pipeline, with
zero extra code on our side.
"""

import asyncio
import logging
import os
import tempfile

import httpx
from livekit import rtc
from livekit.agents import APIConnectOptions, llm, stt, tts
from livekit.agents.types import NOT_GIVEN, NotGivenOr
from livekit.agents.utils import AudioBuffer
# Plugin imports MUST happen at module level (import time, main thread), not
# lazily inside a function called from within the job's async entrypoint --
# LiveKit's plugin registration raises "Plugins must be registered on the
# main thread" if you defer these. This matches how agent.py already
# imports `groq` at the top instead of inside entrypoint().
from livekit.plugins import openai, silero
import openai as _openai_sdk  # the raw openai SDK, for custom client config

logger = logging.getLogger("fieldline.local_pipeline")

# All overridable via .env.local if you want to change models/ports without
# editing code. Sensible defaults are baked in so this works out of the box.
WHISPER_MODEL_SIZE = os.environ.get("WHISPER_MODEL_SIZE", "small.en")
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2:3b")
PIPER_TTS_BASE_URL = os.environ.get("PIPER_TTS_BASE_URL", "http://localhost:8880/v1")


class FasterWhisperSTT(stt.STT):
    """Local, fully offline speech-to-text using faster-whisper on CPU.

    This is non-streaming by design -- faster-whisper transcribes a
    complete utterance at once rather than word-by-word. It is wrapped with
    stt.StreamAdapter (see build_local_stt) so it can still be used anywhere
    LiveKit expects a streaming STT, such as AgentSession or
    stt.FallbackAdapter.
    """

    def __init__(self, *, model_size: str = WHISPER_MODEL_SIZE, language: str = "en") -> None:
        super().__init__(
            capabilities=stt.STTCapabilities(streaming=False, interim_results=False)
        )
        self._language = language
        self._model_size = model_size
        self._model = None  # lazy-loaded on first use, see _ensure_model

    def _ensure_model(self):
        if self._model is None:
            from faster_whisper import WhisperModel

            local_path = _get_local_model_path(self._model_size)
            if local_path:
                logger.info(
                    "loading faster-whisper from local cache (no network needed): %s",
                    local_path,
                )
                model_arg = local_path
            else:
                logger.info(
                    "faster-whisper model %r not in local cache yet -- downloading (online required)...",
                    self._model_size,
                )
                model_arg = self._model_size
            self._model = WhisperModel(model_arg, device="cpu", compute_type="int8")
            logger.info("faster-whisper model ready")
        return self._model

    @property
    def model(self) -> str:
        return self._model_size

    @property
    def provider(self) -> str:
        return "faster-whisper-local"

    async def _recognize_impl(
        self,
        buffer: AudioBuffer,
        *,
        language: NotGivenOr[str] = NOT_GIVEN,
        conn_options: APIConnectOptions,
    ) -> stt.SpeechEvent:
        wav_bytes = rtc.combine_audio_frames(buffer).to_wav_bytes()
        effective_language = self._language if language is NOT_GIVEN else language

        def _transcribe() -> str:
            model = self._ensure_model()
            tmp_path = None
            try:
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                    tmp.write(wav_bytes)
                    tmp_path = tmp.name
                segments, _info = model.transcribe(
                    tmp_path,
                    language=effective_language,
                    vad_filter=False,  # AgentSession's own VAD already segmented this
                )
                return "".join(segment.text for segment in segments).strip()
            finally:
                if tmp_path and os.path.exists(tmp_path):
                    os.remove(tmp_path)

        text = await asyncio.get_event_loop().run_in_executor(None, _transcribe)
        logger.info("faster-whisper transcribed: %r", text)

        return stt.SpeechEvent(
            type=stt.SpeechEventType.FINAL_TRANSCRIPT,
            alternatives=[stt.SpeechData(text=text, language=effective_language)],
        )


def build_local_stt() -> stt.STT:
    """Local, fully offline STT via faster-whisper. Non-streaming, same as
    Groq's STT -- see build_hybrid_stt, which supplies a VAD so
    stt.FallbackAdapter wraps both with streaming support automatically."""
    return FasterWhisperSTT()


def build_local_llm() -> llm.LLM:
    """Ollama, through LiveKit's OpenAI-compatible LLM plugin.

    Uses openai.LLM with a custom AsyncOpenAI client instead of
    openai.LLM.with_ollama() so we can set a 120-second read timeout.
    CPU inference with llama3.2:3b takes 10-30 seconds for the first
    token (Ollama loads the model from disk on first request), which
    exceeds the default httpx timeout of 5 seconds and causes:
      'livekit.plugins.openai.llm.LLM failed: Request timed out'
    before Ollama finishes -- effectively making local LLM useless.
    """
    _ollama_client = _openai_sdk.AsyncOpenAI(
        api_key="ollama",           # Ollama ignores the key but needs non-empty
        base_url=OLLAMA_BASE_URL,
        timeout=httpx.Timeout(
            120.0,                  # 2 min read timeout -- plenty for CPU 3B
            connect=5.0,            # fail fast if Ollama process isn't running
        ),
    )
    return openai.LLM(model=OLLAMA_MODEL, client=_ollama_client)


def build_local_tts() -> tts.TTS:
    """Piper, through local_tts_server.py's OpenAI-compatible
    /v1/audio/speech endpoint (run that file as its own process first)."""
    return openai.TTS(
        model="piper",
        voice="default",
        api_key="not-needed",
        base_url=PIPER_TTS_BASE_URL,
        response_format="wav",
    )


def build_hybrid_stt(cloud_stt: stt.STT) -> stt.STT:
    """Cloud STT first, faster-whisper as the offline fallback.

    Neither Groq's STT nor faster-whisper streams natively (both transcribe
    a full utterance at once), so we hand FallbackAdapter a VAD and let it
    wrap both with stt.StreamAdapter automatically -- this is exactly what
    the ValueError it raises without a VAD tells you to do.
    """
    return stt.FallbackAdapter([cloud_stt, build_local_stt()], vad=silero.VAD.load())


def _get_local_model_path(model_size: str) -> str | None:
    """Return the on-disk snapshot directory for a cached faster-whisper
    model, or None if it hasn't been fully downloaded yet.

    By passing this path directly to WhisperModel instead of the model
    name string, we skip every HuggingFace Hub network call -- the library
    only hits the network when it receives a plain name/ID, not a path.
    This is the key fix that makes offline STT work without any internet.

    We also verify model.bin exists -- a partial download (config files
    only, no weights) would otherwise produce a confusing ctranslate2
    error rather than gracefully falling back to a download.
    """
    try:
        from huggingface_hub import scan_cache_dir
        import pathlib

        repo_id = f"Systran/faster-whisper-{model_size}"
        for repo in scan_cache_dir().repos:
            if repo.repo_id == repo_id:
                # Take the most recent revision that has a snapshot on disk
                # AND contains the actual model weights (not just metadata).
                for revision in sorted(
                    repo.revisions, key=lambda r: r.last_modified, reverse=True
                ):
                    snap = revision.snapshot_path
                    if snap and snap.exists() and (snap / "model.bin").exists():
                        return str(snap)
    except Exception as exc:
        logger.debug("scan_cache_dir failed: %s", exc)
    return None


def warm_up_local_stt() -> None:
    """Forces faster-whisper's model to download (or load from its local
    Hugging Face cache) right now, while you still have network access.

    faster-whisper downloads its model from Hugging Face the first time
    it's actually used -- if that first use happens to be the moment your
    internet just went down, the download fails and BOTH the cloud and
    local STT are briefly unavailable at once (this is exactly what caused
    the "all STTs are unavailable" error in the offline rehearsal).

    Call this once, in the background, at agent startup -- see agent.py.
    It's a blocking call (model loading isn't async), so always run it via
    run_in_executor / a background thread, never awaited directly on the
    event loop.
    """
    from faster_whisper import WhisperModel

    local_path = _get_local_model_path(WHISPER_MODEL_SIZE)
    if local_path:
        logger.info(
            "faster-whisper model %r already cached at %s -- warm-up skipped",
            WHISPER_MODEL_SIZE,
            local_path,
        )
        return

    logger.info(
        "downloading faster-whisper model %r to local cache (first run only)...",
        WHISPER_MODEL_SIZE,
    )
    WhisperModel(WHISPER_MODEL_SIZE, device="cpu", compute_type="int8")
    logger.info("faster-whisper model is cached locally and ready for offline use")


def build_hybrid_llm(cloud_llm: llm.LLM) -> llm.LLM:
    """Cloud LLM first, Ollama as the offline fallback.

    attempt_timeout is set to 120s (default is 5s) because Ollama on CPU
    needs 15-30 seconds to load llama3.2:3b from disk on the first call.
    After that it stays hot in memory and responds in 1-5s. The 5s default
    would kill every cold-start attempt before Ollama finishes loading.
    """
    return llm.FallbackAdapter(
        [cloud_llm, build_local_llm()],
        attempt_timeout=120.0,   # 2 min -- covers Ollama cold start on CPU
    )


def build_hybrid_tts(cloud_tts: tts.TTS) -> tts.TTS:
    """Cloud TTS first, Piper as the offline fallback."""
    return tts.FallbackAdapter([cloud_tts, build_local_tts()])