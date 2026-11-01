"""Parakeet TDT speech recognition on Apple Silicon (MLX), transcribing in-memory audio."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

import mlx.core as mx
import numpy as np
from parakeet_mlx import from_pretrained
from parakeet_mlx.audio import get_logmel

DEFAULT_MODEL = "mlx-community/parakeet-tdt-0.6b-v3"


class Recognizer:
    def __init__(self, model_id: str = DEFAULT_MODEL):
        self.model_id = model_id
        # MLX binds GPU streams to the thread that created them: load and run on one dedicated thread,
        # which also serialises decodes on the GPU.
        self._worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="parakeet")
        self.model = self._worker.submit(from_pretrained, model_id).result()
        self.transcribe(np.zeros(16000, np.float32))  # warm-up: compile kernels before the first caller

    def transcribe(self, audio: np.ndarray) -> tuple[str, float]:
        """Text and decode time in ms for 16 kHz mono float32 audio (blocks; call from a thread)."""
        if len(audio) < 1600:  # under 0.1 s: nothing to decode
            return "", 0.0
        return self._worker.submit(self._decode, audio).result()

    def _decode(self, audio: np.ndarray) -> tuple[str, float]:
        started = time.perf_counter()
        # float32: get_logmel views the complex STFT in the input dtype (the library itself loads float32)
        mel = get_logmel(mx.array(audio.astype(np.float32)), self.model.preprocessor_config)
        result = self.model.generate(mel)[0]
        return result.text.strip(), (time.perf_counter() - started) * 1000
