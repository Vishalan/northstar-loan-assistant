"""Endpointer unit tests and an end-to-end WebSocket test with the real Parakeet model."""

import json
import wave
from pathlib import Path

import numpy as np
import pytest

from speech.endpointer import SR, Endpointer

FIX = Path(__file__).parent / "fixtures"


def load(name: str) -> np.ndarray:
    with wave.open(str(FIX / name)) as w:
        assert w.getframerate() == SR and w.getnchannels() == 1
        return np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(np.float32) / 32768


def noise(seconds: float, level: float = 0.001) -> np.ndarray:
    return (np.random.default_rng(0).standard_normal(int(SR * seconds)) * level).astype(np.float32)


def test_endpointer_finds_one_utterance_with_preroll():
    clip = load("failed_payments.wav")
    stream = np.concatenate([noise(1.0), clip, noise(1.2)])
    ep, events = Endpointer(), []
    for i in range(0, len(stream), 1600):  # 100 ms chunks, like the browser
        events += ep.feed(stream[i:i + 1600])
    kinds = [e.kind for e in events]
    assert kinds == ["start", "end"]
    seconds = len(events[1].audio) / SR
    assert len(clip) / SR - 0.4 < seconds < len(clip) / SR + 1.0


def test_endpointer_ignores_silence_and_clicks():
    ep = Endpointer()
    events = ep.feed(noise(3.0))
    click = np.concatenate([noise(0.5), np.full(800, 0.3, np.float32), noise(1.5)])  # 50 ms click
    events += ep.feed(click)
    assert all(e.audio is None for e in events if e.kind == "end")


def test_reset_drops_the_utterance_in_progress():
    ep = Endpointer()
    clip = load("next_due_date.wav")
    ep.feed(np.concatenate([noise(0.5), clip[: len(clip) // 2]]))
    assert ep.in_speech
    ep.reset()
    assert not ep.in_speech and len(ep.current_audio()) == 0


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from speech.app import app
    with TestClient(app) as c:
        yield c


@pytest.mark.parametrize("name,expect", [("failed_payments.wav", "failed payments"),
                                         ("next_due_date.wav", "next due date"),
                                         ("next_due_date_8k.wav", "next due date")])
def test_websocket_transcribes_streamed_audio(client, name, expect):
    stream = np.concatenate([noise(0.6), load(name), noise(1.2)])
    pcm = (np.clip(stream, -1, 1) * 32767).astype("<i2").tobytes()
    with client.websocket_connect("/v1/stt") as ws:
        assert ws.receive_json()["type"] == "ready"
        for i in range(0, len(pcm), 3200):  # 100 ms frames
            ws.send_bytes(pcm[i:i + 3200])
        messages = []
        while True:
            m = ws.receive_json()
            messages.append(m)
            if m["type"] == "final":
                break
    final = messages[-1]
    assert expect in final["text"].lower(), final
    assert final["decode_ms"] < 1500
    assert messages[0]["type"] == "start"


def test_openai_compatible_recognizer_sends_one_wav_per_utterance(monkeypatch):
    import httpx

    from speech.engines import OpenAITranscription
    seen = {}

    def handler(request: httpx.Request):
        seen["url"] = str(request.url)
        seen["body"] = request.read()
        return httpx.Response(200, json={"text": " what is my next EMI "})

    monkeypatch.setenv("ASR_URL", "http://gpu-box:8000/")
    rec = OpenAITranscription("Systran/faster-whisper-large-v3")
    rec._client = httpx.Client(transport=httpx.MockTransport(handler))
    text, ms = rec.transcribe(np.zeros(8000, np.float32))
    assert text == "what is my next EMI" and ms >= 0
    assert seen["url"] == "http://gpu-box:8000/v1/audio/transcriptions"
    assert b"RIFF" in seen["body"] and b"Systran/faster-whisper-large-v3" in seen["body"]
    assert rec.partials is False  # no live partials over the network
    assert rec.transcribe(np.zeros(100, np.float32)) == ("", 0.0)


def test_tts_endpoint_uses_the_configured_engine(monkeypatch):
    from fastapi.testclient import TestClient

    import speech.app as app_module

    class FakeTTS:
        engine, model_id, voice = "fake", "kokoro", "af_heart"

        async def synthesize(self, text, voice=None):
            return b"ID3" + text.encode(), "audio/mpeg"

    monkeypatch.setattr(app_module, "_synthesizer", FakeTTS())
    monkeypatch.setattr(app_module, "load_model", lambda: None)
    client = TestClient(app_module.app)
    r = client.post("/v1/tts", json={"text": "Your EMI is due on 5 November."})
    assert r.status_code == 200 and r.headers["content-type"] == "audio/mpeg" and r.content.startswith(b"ID3")
    assert client.post("/v1/tts", json={"text": " "}).status_code == 400
    monkeypatch.setattr(app_module, "_synthesizer", False)
    assert client.post("/v1/tts", json={"text": "hi"}).status_code == 404
