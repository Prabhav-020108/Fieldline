# Edge Hardware Requirements

FieldLine's offline path runs three local models on the technician's own
device: faster-whisper (STT), Ollama running llama3.2:3b (LLM), and Piper
(TTS). This table states what each one needs to run, so "runs offline" is
a verifiable claim rather than an assumption.

| Component | Model as shipped | Min RAM | Recommended | Quantization | Acceleration |
|---|---|---|---|---|---|
| Offline STT | faster-whisper, `small` (`WHISPER_MODEL_SIZE`), CPU, int8 | 4 GB free | 8 GB free | int8 (`compute_type="int8"` in `local_pipeline.py`) | none required; CPU-only by design |
| Offline LLM | Ollama, `llama3.2:3b` | 8 GB unified/system | 16 GB unified (Apple Silicon) or a dedicated GPU/NPU | Q4_K_M (Ollama's default for tagged `3b` models -- confirm on your machine with `ollama show llama3.2:3b --modelfile` before quoting this in a submission) | Metal on Apple Silicon (automatic); CPU fallback elsewhere -- this is why the offline latency budget (2500ms) is 2.5x the online one |
| Offline TTS | Piper, `en_US-lessac-medium` | 1 GB free | 2 GB free | none (Piper ships fp32 ONNX at this voice size) | none required |
| **Demo device** | -- | -- | -- | -- | The rehearsed demo runs on a CPU-only laptop, not an NPU device -- stated explicitly rather than implying hardware not actually tested |

## Production target (stated, not yet exercised)

A rugged field tablet running this stack in production should target
**16 GB of unified memory on Apple Silicon**, or a **Snapdragon-X-Elite-class
Windows device** with 16 GB RAM. Ollama's NPU backend for Snapdragon
devices is a stated future upgrade -- it has not been exercised in this
build, which runs CPU-only in every rehearsal and in the recorded demo.

## Why these specific numbers

- `WHISPER_MODEL_SIZE=small` (not `tiny` or `medium`) is the balance point
  between accuracy on Hindi/Hinglish speech and CPU inference time on a
  typical laptop -- see `local_pipeline.py`'s comment on why the `.en`
  variants are excluded entirely (they can't transcribe non-English audio
  at all).
- `llama3.2:3b` is the smallest Llama 3 tier that stays coherent on
  FieldLine's five-tool, safety-critical instructions -- see
  `agent/PROMPT_ENGINEERING.md` for the prompt these hardware numbers need
  to run.
- The 2500ms offline latency budget in `agent/src/tracing.py`'s
  `LATENCY_BUDGET_MS` is set against CPU-only Ollama inference on the
  hardware above, not GPU-accelerated inference -- raising that budget
  without also raising this hardware floor would just hide real latency
  regressions from Phoenix's `latency_threshold_exceeded` alerting.