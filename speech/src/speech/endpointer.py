"""Energy-based speech endpointing for a single microphone stream.

Feed 16 kHz mono float32 audio in any chunk size. The endpointer tracks an adaptive noise floor, starts an
utterance after a short run of loud frames (keeping a little pre-roll so the first syllable is not clipped), and
ends it after a quiet gap. Pure Python + numpy, so it is unit-tested without a model or a browser.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

SR = 16000
FRAME = 320  # 20 ms


@dataclass
class EndpointConfig:
    start_frames: int = 3          # 60 ms of speech to open an utterance
    end_silence_ms: int = 550      # quiet gap that closes it
    preroll_ms: int = 300          # audio kept from before the start
    max_utterance_s: float = 15.0  # force a cut on very long input
    min_utterance_ms: int = 250    # ignore clicks and coughs shorter than this
    start_ratio: float = 3.0       # speech when frame energy > floor * ratio ...
    min_level: float = 0.006       # ... and above this absolute RMS


@dataclass
class Event:
    kind: str                      # "start" | "end"
    audio: np.ndarray | None = None


@dataclass
class Endpointer:
    cfg: EndpointConfig = field(default_factory=EndpointConfig)
    floor: float = 0.003
    _pending: np.ndarray = field(default_factory=lambda: np.zeros(0, np.float32))
    _preroll: list = field(default_factory=list)
    _utt: list = field(default_factory=list)
    _in_speech: bool = False
    _loud_run: int = 0
    _quiet_ms: int = 0
    _speech_frames: int = 0  # frames since the start, excluding pre-roll

    @property
    def in_speech(self) -> bool:
        return self._in_speech

    def current_audio(self) -> np.ndarray:
        return np.concatenate(self._utt) if self._utt else np.zeros(0, np.float32)

    def reset(self) -> None:
        """Drop any utterance in progress (the client cancelled it)."""
        self._utt, self._in_speech, self._loud_run, self._quiet_ms = [], False, 0, 0

    def feed(self, audio: np.ndarray) -> list[Event]:
        events: list[Event] = []
        buf = np.concatenate([self._pending, audio.astype(np.float32)])
        n = len(buf) // FRAME
        self._pending = buf[n * FRAME:]
        c = self.cfg
        for i in range(n):
            frame = buf[i * FRAME:(i + 1) * FRAME]
            rms = float(np.sqrt(np.mean(frame * frame)) + 1e-9)
            loud = rms > max(self.floor * c.start_ratio, c.min_level)
            if not self._in_speech:
                self._preroll.append(frame)
                if len(self._preroll) > c.preroll_ms // 20:
                    self._preroll.pop(0)
                self.floor = 0.95 * self.floor + 0.05 * rms if not loud else self.floor
                self._loud_run = self._loud_run + 1 if loud else 0
                if self._loud_run >= c.start_frames:
                    self._in_speech, self._quiet_ms, self._speech_frames = True, 0, self._loud_run
                    self._utt = list(self._preroll)
                    self._preroll = []
                    events.append(Event("start"))
                continue
            self._utt.append(frame)
            self._speech_frames += 1
            self._quiet_ms = 0 if loud else self._quiet_ms + 20
            too_long = len(self._utt) * 20 >= c.max_utterance_s * 1000
            if self._quiet_ms >= c.end_silence_ms or too_long:
                audio_out = self.current_audio()
                spoken_ms = self._speech_frames * 20 - self._quiet_ms
                self.reset()
                if spoken_ms >= c.min_utterance_ms:
                    events.append(Event("end", audio_out))
                else:
                    events.append(Event("end", None))  # too short: a click, not speech
        return events
