"""Swappable speech engines. The WebSocket protocol and endpointer stay the same whichever engine runs.

Recognition (ASR_ENGINE):
  parakeet-mlx    Parakeet TDT 0.6B v3 on Apple Silicon (MLX), in-process. Default on arm64 macOS.
  faster-whisper  Whisper via CTranslate2 on an NVIDIA GPU (or CPU), in-process. `uv sync --extra cuda`.
  openai          any OpenAI-compatible /v1/audio/transcriptions endpoint: OpenAI, Groq, or a self-hosted
                  server such as Speaches on our GPU box. ASR_URL, ASR_API_KEY, STT_MODEL.

Synthesis (TTS_ENGINE, optional; the browser's own voice is used when it is off):
  openai          any OpenAI-compatible /v1/audio/speech endpoint: Kokoro-FastAPI on our GPU box, OpenAI.
                  TTS_URL, TTS_API_KEY, TTS_MODEL, TTS_VOICE.
  none            no server voice (default)

To add an engine: write a class with model_id, partials and transcribe(audio) -> (text, decode_ms) (or
synthesize(text, voice) -> (bytes, media_type)) and register it below.
"""

from __future__ import annotations

import io
import os
import platform
import time
import wave
from concurrent.futures import ThreadPoolExecutor

import httpx
import numpy as np

SR = 16000


def _wav(audio: np.ndarray) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes())
    return buf.getvalue()


class FasterWhisper:
    partials = True

    def __init__(self, model_id: str | None = None):
        from faster_whisper import WhisperModel

        self.model_id = model_id or "large-v3-turbo"
        device = os.environ.get("ASR_DEVICE", "auto")
        self.model = WhisperModel(self.model_id, device=device,
                                  compute_type=os.environ.get("ASR_COMPUTE_TYPE", "default"))
        self._worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="whisper")
        self.transcribe(np.zeros(SR, np.float32))

    def transcribe(self, audio: np.ndarray) -> tuple[str, float]:
        if len(audio) < 1600:
            return "", 0.0
        return self._worker.submit(self._decode, audio).result()

    def _decode(self, audio: np.ndarray) -> tuple[str, float]:
        started = time.perf_counter()
        segments, _ = self.model.transcribe(audio.astype(np.float32), language=os.environ.get("ASR_LANGUAGE", "en"),
                                            beam_size=1, vad_filter=False, condition_on_previous_text=False)
        text = " ".join(s.text.strip() for s in segments).strip()
        return text, (time.perf_counter() - started) * 1000


class OpenAITranscription:
    """One HTTP request per utterance. Partials are off: re-sending the growing utterance every 400 ms over the
    network costs more than the live preview is worth."""

    partials = False

    def __init__(self, model_id: str | None = None):
        self.url = os.environ.get("ASR_URL", "https://api.openai.com").rstrip("/")
        self.model_id = model_id or "whisper-1"
        key = os.environ.get("ASR_API_KEY", "")
        self._client = httpx.Client(timeout=httpx.Timeout(15.0, connect=3.0),
                                    headers={"Authorization": f"Bearer {key}"} if key else {})

    def transcribe(self, audio: np.ndarray) -> tuple[str, float]:
        if len(audio) < 1600:
            return "", 0.0
        started = time.perf_counter()
        r = self._client.post(f"{self.url}/v1/audio/transcriptions",
                              files={"file": ("utterance.wav", _wav(audio), "audio/wav")},
                              data={"model": self.model_id, "language": os.environ.get("ASR_LANGUAGE", "en"),
                                    "response_format": "json"})
        r.raise_for_status()
        return r.json().get("text", "").strip(), (time.perf_counter() - started) * 1000


class Parakeet:
    partials = True

    def __new__(cls, model_id: str | None = None):
        from speech.asr import DEFAULT_MODEL, Recognizer

        return Recognizer(model_id or DEFAULT_MODEL)


class OpenAISpeech:
    def __init__(self):
        self.url = os.environ.get("TTS_URL", "https://api.openai.com").rstrip("/")
        self.model_id = os.environ.get("TTS_MODEL", "kokoro")
        self.voice = os.environ.get("TTS_VOICE", "af_heart")
        key = os.environ.get("TTS_API_KEY", "")
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=3.0),
                                         headers={"Authorization": f"Bearer {key}"} if key else {})

    async def synthesize(self, text: str, voice: str | None = None) -> tuple[bytes, str]:
        r = await self._client.post(f"{self.url}/v1/audio/speech", json={
            "model": self.model_id, "input": text, "voice": voice or self.voice, "response_format": "mp3"})
        r.raise_for_status()
        return r.content, "audio/mpeg"


ASR_ENGINES = {"parakeet-mlx": Parakeet, "faster-whisper": FasterWhisper, "openai": OpenAITranscription}
TTS_ENGINES = {"openai": OpenAISpeech}


def default_asr_engine() -> str:
    on_apple = platform.system() == "Darwin" and platform.machine() == "arm64"
    return "parakeet-mlx" if on_apple else "faster-whisper"


def make_recognizer():
    name = os.environ.get("ASR_ENGINE") or default_asr_engine()
    if name not in ASR_ENGINES:
        raise RuntimeError(f"ASR_ENGINE must be one of {list(ASR_ENGINES)}")
    rec = ASR_ENGINES[name](os.environ.get("STT_MODEL") or None)
    rec.engine = name
    return rec


def make_synthesizer():
    name = os.environ.get("TTS_ENGINE", "none")
    if name == "none":
        return None
    if name not in TTS_ENGINES:
        raise RuntimeError(f"TTS_ENGINE must be one of {list(TTS_ENGINES) + ['none']}")
    tts = TTS_ENGINES[name]()
    tts.engine = name
    return tts
