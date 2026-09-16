"""STT rotation: remotes first, then local if few jobs, else OpenAI."""

from __future__ import annotations

from pathlib import Path

import app.stt as stt


def test_rotate_uses_first_remote_then_skips_local(monkeypatch, tmp_path):
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"RIFF")

    monkeypatch.setattr(stt.settings, "groq_api_key", "g")
    monkeypatch.setattr(stt.settings, "deepgram_api_key", "")
    monkeypatch.setattr(stt.settings, "assemblyai_api_key", "")
    monkeypatch.setattr(stt.settings, "speechmatics_api_key", "")
    monkeypatch.setattr(stt.settings, "gladia_api_key", "")
    monkeypatch.setattr(stt.settings, "elevenlabs_api_key", "")
    monkeypatch.setattr(stt.settings, "elevenlabs_api_key_2", "")
    monkeypatch.setattr(stt.settings, "soniox_api_key", "")
    monkeypatch.setattr(stt.settings, "openai_api_key", "o")
    monkeypatch.setattr(stt, "_groq", lambda *a, **k: "Ingredients flour water. Steps mix bake.")
    monkeypatch.setattr(stt, "active_counts", lambda: (1, 1))
    local_calls = []

    text, provider = stt.rotate_transcript(
        audio,
        local_fn=lambda p: local_calls.append(p) or "local",
    )
    assert provider == "groq"
    assert "flour" in text
    assert local_calls == []


def test_rotate_falls_to_local_when_remotes_fail_and_few_jobs(monkeypatch, tmp_path):
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"RIFF")

    monkeypatch.setattr(stt.settings, "groq_api_key", "g")
    for key in (
        "deepgram_api_key",
        "assemblyai_api_key",
        "speechmatics_api_key",
        "gladia_api_key",
        "elevenlabs_api_key",
        "elevenlabs_api_key_2",
        "soniox_api_key",
    ):
        monkeypatch.setattr(stt.settings, key, "")
    monkeypatch.setattr(stt.settings, "openai_api_key", "o")
    monkeypatch.setattr(stt.settings, "stt_local_max_active_jobs", 2)
    monkeypatch.setattr(stt, "_groq", lambda *a, **k: (_ for _ in ()).throw(stt.SttRateLimited("rl")))
    monkeypatch.setattr(stt, "active_counts", lambda: (1, 1))
    openai_calls = []
    monkeypatch.setattr(stt, "_openai", lambda *a, **k: openai_calls.append(1) or "openai")

    text, provider = stt.rotate_transcript(
        audio,
        local_fn=lambda p: "Local recipe speech with ingredients and steps.",
    )
    assert provider == "local"
    assert "Local" in text
    assert openai_calls == []


def test_rotate_falls_to_openai_when_busy(monkeypatch, tmp_path):
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"RIFF")

    monkeypatch.setattr(stt.settings, "groq_api_key", "g")
    for key in (
        "deepgram_api_key",
        "assemblyai_api_key",
        "speechmatics_api_key",
        "gladia_api_key",
        "elevenlabs_api_key",
        "elevenlabs_api_key_2",
        "soniox_api_key",
    ):
        monkeypatch.setattr(stt.settings, key, "")
    monkeypatch.setattr(stt.settings, "openai_api_key", "o")
    monkeypatch.setattr(stt.settings, "stt_local_max_active_jobs", 2)
    monkeypatch.setattr(stt, "_groq", lambda *a, **k: (_ for _ in ()).throw(stt.SttRateLimited("rl")))
    monkeypatch.setattr(stt, "active_counts", lambda: (2, 1))
    monkeypatch.setattr(stt, "_openai", lambda *a, **k: "OpenAI speech text here.")
    local_calls = []

    text, provider = stt.rotate_transcript(
        audio,
        local_fn=lambda p: local_calls.append(1) or "local",
    )
    assert provider == "openai"
    assert "OpenAI" in text
    assert local_calls == []


def test_round_robin_advances(monkeypatch, tmp_path):
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"RIFF")
    stt._rr_index = 0
    monkeypatch.setattr(stt.settings, "groq_api_key", "g")
    monkeypatch.setattr(stt.settings, "deepgram_api_key", "d")
    for key in (
        "assemblyai_api_key",
        "speechmatics_api_key",
        "gladia_api_key",
        "elevenlabs_api_key",
        "elevenlabs_api_key_2",
        "soniox_api_key",
    ):
        monkeypatch.setattr(stt.settings, key, "")
    calls = []

    def fake_groq(*a, **k):
        calls.append("groq")
        return "groq text long enough"

    def fake_dg(*a, **k):
        calls.append("deepgram")
        return "deepgram text long enough"

    monkeypatch.setattr(stt, "_groq", fake_groq)
    monkeypatch.setattr(stt, "_deepgram", fake_dg)

    _, p1 = stt.rotate_transcript(audio)
    _, p2 = stt.rotate_transcript(audio)
    assert {p1, p2} == {"groq", "deepgram"}
    assert calls == ["groq", "deepgram"] or calls == ["deepgram", "groq"]
