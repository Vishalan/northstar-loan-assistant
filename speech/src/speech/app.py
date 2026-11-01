"""Local speech-recognition service.

WebSocket /v1/stt — the browser sends 16 kHz mono PCM16 (little-endian) as binary frames; the server replies with
JSON messages:
  {"type": "ready", "model": ...}
  {"type": "start", "id": n}                       speech began
  {"type": "partial", "id": n, "text": ...}        live transcript while speaking (about every 400 ms)
  {"type": "final", "id": n, "text": ..., "decode_ms": ..., "audio_ms": ...}
Client text messages: {"type": "reset"} drops the utterance in progress (barge-in, recogniser restart).

Run: uv run uvicorn speech.app:app --port 8200
"""

from __future__ import annotations

import asyncio
import json
import os
import time

import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from speech.endpointer import SR, Endpointer

PARTIAL_EVERY_S = 0.4
app = FastAPI(title="Northstar speech")
app.add_middleware(CORSMiddleware, allow_origins=os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(","),
                   allow_methods=["GET"], allow_headers=["*"])
_recognizer = None


def recognizer():
    global _recognizer
    if _recognizer is None:
        from speech.asr import DEFAULT_MODEL, Recognizer
        _recognizer = Recognizer(os.environ.get("STT_MODEL", DEFAULT_MODEL))
    return _recognizer


@app.on_event("startup")
async def load_model() -> None:
    await asyncio.to_thread(recognizer)


@app.get("/healthz")
async def healthz():
    return {"ok": True, "model": recognizer().model_id}


@app.websocket("/v1/stt")
async def stt(ws: WebSocket):
    await ws.accept()
    rec = recognizer()
    ep = Endpointer()
    utt_id = 0
    last_partial = 0.0
    partial_task: asyncio.Task | None = None
    await ws.send_json({"type": "ready", "model": rec.model_id})

    async def send_partial(uid: int, audio: np.ndarray):
        text, _ = await asyncio.to_thread(rec.transcribe, audio)
        if text and uid == utt_id and ep.in_speech:
            await ws.send_json({"type": "partial", "id": uid, "text": text})

    try:
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
            if msg.get("text"):
                if json.loads(msg["text"]).get("type") == "reset":
                    ep.reset()
                    utt_id += 1
                continue
            data = msg.get("bytes")
            if not data:
                continue
            audio = np.frombuffer(data, dtype="<i2").astype(np.float32) / 32768.0
            for ev in ep.feed(audio):
                if ev.kind == "start":
                    utt_id += 1
                    last_partial = time.monotonic()
                    await ws.send_json({"type": "start", "id": utt_id})
                elif ev.kind == "end":
                    if partial_task and not partial_task.done():
                        partial_task.cancel()
                    if ev.audio is None:
                        await ws.send_json({"type": "final", "id": utt_id, "text": "", "decode_ms": 0, "audio_ms": 0})
                        continue
                    text, decode_ms = await asyncio.to_thread(rec.transcribe, ev.audio)
                    await ws.send_json({"type": "final", "id": utt_id, "text": text, "decode_ms": round(decode_ms),
                                        "audio_ms": round(len(ev.audio) / SR * 1000)})
            if ep.in_speech and time.monotonic() - last_partial >= PARTIAL_EVERY_S and \
                    (partial_task is None or partial_task.done()):
                last_partial = time.monotonic()
                partial_task = asyncio.create_task(send_partial(utt_id, ep.current_audio()))
    except WebSocketDisconnect:
        pass
    finally:
        if partial_task and not partial_task.done():
            partial_task.cancel()
