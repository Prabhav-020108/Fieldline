from unittest.mock import MagicMock, patch

from livekit.agents import llm, stt, tts

import local_pipeline


def test_build_hybrid_stt_cloud_deploy(monkeypatch):
    monkeypatch.setattr(local_pipeline, "CLOUD_DEPLOY", True)
    mock_cloud = MagicMock(spec=stt.STT)
    result = local_pipeline.build_hybrid_stt(mock_cloud)
    assert result is mock_cloud


def test_build_hybrid_stt_hybrid_fallback(monkeypatch):
    monkeypatch.setattr(local_pipeline, "CLOUD_DEPLOY", False)
    mock_cloud = MagicMock(spec=stt.STT)
    with (
        patch("local_pipeline.silero.VAD.load", return_value=MagicMock()),
        patch("local_pipeline.build_local_stt", return_value=MagicMock(spec=stt.STT)),
    ):
        result = local_pipeline.build_hybrid_stt(mock_cloud)
        assert isinstance(result, stt.FallbackAdapter)


def test_build_hybrid_llm_cloud_deploy(monkeypatch):
    monkeypatch.setattr(local_pipeline, "CLOUD_DEPLOY", True)
    mock_cloud = MagicMock(spec=llm.LLM)
    result = local_pipeline.build_hybrid_llm(mock_cloud)
    assert result is mock_cloud


def test_build_hybrid_llm_hybrid_fallback(monkeypatch):
    monkeypatch.setattr(local_pipeline, "CLOUD_DEPLOY", False)
    mock_cloud = MagicMock(spec=llm.LLM)
    with patch("local_pipeline.build_local_llm", return_value=MagicMock(spec=llm.LLM)):
        result = local_pipeline.build_hybrid_llm(mock_cloud)
        assert isinstance(result, llm.FallbackAdapter)


def test_build_hybrid_tts_cloud_deploy(monkeypatch):
    monkeypatch.setattr(local_pipeline, "CLOUD_DEPLOY", True)
    mock_cloud = MagicMock(spec=tts.TTS)
    result = local_pipeline.build_hybrid_tts(mock_cloud)
    assert result is mock_cloud


def test_build_hybrid_tts_hybrid_fallback(monkeypatch):
    monkeypatch.setattr(local_pipeline, "CLOUD_DEPLOY", False)
    mock_cloud = MagicMock(spec=tts.TTS)
    mock_cloud.num_channels = 1
    mock_cloud.sample_rate = 24000
    mock_local = MagicMock(spec=tts.TTS)
    mock_local.num_channels = 1
    mock_local.sample_rate = 24000
    with patch("local_pipeline.build_local_tts", return_value=mock_local):
        result = local_pipeline.build_hybrid_tts(mock_cloud)
        assert isinstance(result, tts.FallbackAdapter)


def test_faster_whisper_capabilities():
    stt_instance = local_pipeline.FasterWhisperSTT(model_size="small")
    assert stt_instance.capabilities.streaming is False
    assert stt_instance.capabilities.interim_results is False
