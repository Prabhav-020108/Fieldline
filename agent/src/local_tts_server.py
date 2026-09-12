"""
Minimal local, fully offline text-to-speech server for FieldLine's Phase 4
offline path.

Wraps Piper (a small, fast, fully local neural TTS engine) behind an
OpenAI-compatible /v1/audio/speech endpoint, so the agent can talk to it
using LiveKit's already-built, already-tested openai.TTS plugin instead of
a hand-rolled one -- see local_pipeline.py's build_local_tts().

Run this as its OWN process, in its own terminal window, separate from the
agent:

    cd agent
    uv run python src/local_tts_server.py

It must already be running before you start the agent -- the agent's TTS
fallback path (openai.TTS pointed at this server) will fail if nothing is
listening on PIPER_TTS_PORT yet.

Quick manual test once it's running:
    http://localhost:8880/health   (open in a browser, should show JSON)
"""

import io
import logging
import os
import wave

import uvicorn
from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel

logger = logging.getLogger("fieldline.local_tts_server")
logging.basicConfig(level=logging.INFO)

PIPER_MODEL_PATH = os.environ.get(
    "PIPER_MODEL_PATH", os.path.join("models", "en_US-lessac-medium.onnx")
)
PIPER_TTS_PORT = int(os.environ.get("PIPER_TTS_PORT", "8880"))

app = FastAPI(title="FieldLine local Piper TTS (OpenAI-compatible)")

_voice = None  # lazy-loaded PiperVoice instance, see _get_voice()


def _get_voice():
    global _voice
    if _voice is None:
        from piper import PiperVoice

        if not os.path.exists(PIPER_MODEL_PATH):
            raise FileNotFoundError(
                f"Piper voice model not found at '{PIPER_MODEL_PATH}'. "
                "From the agent/ folder, run:\n"
                "  uv run python -m piper.download_voices en_US-lessac-medium --data-dir models\n"
                "then check the exact filename with `dir models` and update "
                "PIPER_MODEL_PATH in .env.local if it doesn't match. "
                "See Phase 4 guide, Step 3."
            )
        logger.info("loading Piper voice from %s ...", PIPER_MODEL_PATH)
        _voice = PiperVoice.load(PIPER_MODEL_PATH)
        logger.info("Piper voice loaded")
    return _voice


class SpeechRequest(BaseModel):
    model: str = "piper"
    input: str
    voice: str = "default"
    response_format: str = "wav"


@app.post("/v1/audio/speech")
def create_speech(req: SpeechRequest) -> Response:
    if not req.input.strip():
        raise HTTPException(status_code=400, detail="`input` text is empty")

    try:
        voice = _get_voice()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        voice.synthesize_wav(req.input, wav_file)
    buffer.seek(0)
    return Response(content=buffer.read(), media_type="audio/wav")


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "model_path": PIPER_MODEL_PATH,
        "model_loaded": _voice is not None,
    }


if __name__ == "__main__":
    logger.info("starting local Piper TTS server on http://localhost:%d", PIPER_TTS_PORT)
    uvicorn.run(app, host="0.0.0.0", port=PIPER_TTS_PORT)