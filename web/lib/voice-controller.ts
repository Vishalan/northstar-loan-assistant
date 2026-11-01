"use client";

// VoiceController: voice mode. Recognition is the local/remote speech service or the browser's Web Speech
// API; speech output is a swappable Speaker (browser voice, or a server voice: see ./speech-output.ts).
//
// State machine
//   idle ──start()──▶ listening ──interim──▶ user_speaking ──final + 250ms quiet──▶ thinking
//   thinking ──first sentence starts playing──▶ speaking ──queue drained & turn done──▶ listening
//   thinking|speaking ──barge-in (≥2 real words, not echo)──▶ interrupted ──▶ user_speaking
//   any ──stop()──▶ idle
//
// All browser and app dependencies are injected (VoiceDeps) so the controller can be driven
// with fakes; the pure text logic lives in ./voice-utils.ts and is unit-tested.

import { makeSpeaker, type Speaker } from "./speech-output";
import type { EngineContext, EngineEvent } from "./turn-engine";
import type { ActionProposal, ClientMetricName, ConfirmResponse } from "./types";
import {
  LONG_WAIT_FILLER,
  SentenceBuffer,
  fillerFromStatus,
  isAffirmative,
  isBackchannel,
  isClosing,
  isThanks,
  GOODBYE,
  YOU_ARE_WELCOME,
  isEcho,
  parseOtp,
  shouldBargeIn,
  stripEchoPrefix,
  stripMarkdown,
  toSpeakable,
} from "./voice-utils";
import { LocalRecognizer, STT_URL, localSttAvailable } from "./local-recognizer";

export type VoiceState = "idle" | "listening" | "user_speaking" | "thinking" | "speaking" | "interrupted";

export type VoiceSnapshot = {
  state: VoiceState;
  active: boolean;
  interim: string;
  error: string | null;
  notice: string | null;
  supported: boolean;
  stream: MediaStream | null;
  voiceName: string | null;
  /** Which speech recogniser this call uses. */
  sttEngine: "local" | "browser" | null;
};

export type VoiceDeps = {
  /** Send a voice turn; returns the assistant message id the turn will stream into. */
  send(text: string): string | null;
  /** Barge-in: abort/cancel the turn behind `messageId` and tell the server what was already spoken. */
  interrupt(messageId: string, spokenText: string): void;
  subscribe(fn: (ev: EngineEvent, ctx: EngineContext) => void): () => void;
  prefetch(text: string): void;
  metric(name: ClientMetricName, ms: number, meta?: Record<string, unknown>): void;
  isActionPending(actionId: string): boolean;
  confirm(p: ActionProposal, otp?: string): Promise<ConfirmResponse | null>;
  /** Append a user transcript to the conversation without starting a turn (voice confirmations). */
  noteUser(text: string): void;
};

const FILLER_AFTER_MS = 700;
const LONG_FILLER_AFTER_MS = 3000;
const END_OF_TURN_QUIET_MS = 250;
const PREFETCH_EVERY_MS = 400;
const ECHO_TAIL_MS = 4000; // Chrome often delivers the final result for echoed audio seconds after playback
const SAID_MEMORY_MS = 60000; // how long the assistant's own words count as possible echo (Chrome can glue ~20 s of audio into one result)
const ECHO_GUARD_MS = 8000; // drop a committed "user" turn that is mostly our own speech within this window

type SR = {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  maxAlternatives: number;
  start(): void;
  stop(): void;
  abort(): void;
  onresult: ((e: SREvent) => void) | null;
  onerror: ((e: { error: string; message?: string }) => void) | null;
  onend: (() => void) | null;
  onstart: (() => void) | null;
};
type SREvent = {
  resultIndex: number;
  results: ArrayLike<{ isFinal: boolean; 0: { transcript: string } }>;
};
type SRCtor = new () => SR;

function getRecognitionCtor(): SRCtor | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as { SpeechRecognition?: SRCtor; webkitSpeechRecognition?: SRCtor };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

export function voiceSupported(): boolean {
  return typeof window !== "undefined" && (!!getRecognitionCtor() || !!STT_URL) && "speechSynthesis" in window;
}

export class VoiceController {
  private snap: VoiceSnapshot = {
    state: "idle",
    active: false,
    interim: "",
    error: null,
    notice: null,
    supported: false,
    stream: null,
    voiceName: null,
    sttEngine: null,
  };
  private subs = new Set<() => void>();
  private rec: SR | null = null;
  private unsubscribeEngine: (() => void) | null = null;
  private speaker: Speaker | null = null;

  // user-side
  private pendingFinal = "";
  private eotTimer: ReturnType<typeof setTimeout> | null = null;
  private lastPrefetchAt = 0;
  private eosAt: number | null = null;
  private resultFirstSeen = new Map<number, number>();

  // assistant-side, per turn
  private gen = 0; // bumps on barge-in / new turn / stop so stale TTS callbacks are ignored
  private messageId: string | null = null;
  private sentences = new SentenceBuffer();
  private outstanding = 0;
  private currentSentence: string | null = null; // speakable form, for echo detection
  private currentRaw: string | null = null; // display form, for spoken_text
  private spoken: string[] = [];
  private said: { text: string; at: number }[] = []; // everything queued for speech (fillers too), for echo checks
  private speakingEndedAt = 0;
  private turnDone = true;
  private gotText = false;
  private lastStatus: string | null = null;
  private fillerTimers: ReturnType<typeof setTimeout>[] = [];
  private firstAudioReported = false;
  private pendingAction: ActionProposal | null = null;
  private endAfterSpeech = false;
  private transitions: { state: VoiceState; at: number }[] = [];

  constructor(private deps: VoiceDeps) {
    this.snap.supported = voiceSupported();
  }

  /* ---------------- external store API (useSyncExternalStore) ---------------- */
  subscribe = (fn: () => void) => {
    this.subs.add(fn);
    return () => this.subs.delete(fn);
  };
  getSnapshot = () => this.snap;
  /** Recent state transitions, for debugging / demo narration. */
  get history() {
    return this.transitions.slice();
  }

  private update(p: Partial<VoiceSnapshot>) {
    this.snap = { ...this.snap, ...p };
    this.subs.forEach((f) => f());
  }
  private setState(state: VoiceState) {
    if (this.snap.state === state) return;
    this.transitions.push({ state, at: performance.now() });
    if (this.transitions.length > 50) this.transitions.shift();
    this.update({ state });
  }

  /* ---------------- lifecycle ---------------- */
  async start() {
    if (this.snap.active) return;
    if (!voiceSupported()) {
      this.update({
        error: "Voice needs the Web Speech API. Please use a recent version of Google Chrome or Edge on desktop.",
      });
      return;
    }
    this.update({ error: null, notice: null });
    let stream: MediaStream | null = null;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
    } catch (e) {
      const name = (e as DOMException)?.name;
      this.update({
        error:
          name === "NotAllowedError" || name === "SecurityError"
            ? "Microphone access is blocked. Allow the microphone for this site in your browser's address bar, then try again."
            : name === "NotFoundError"
              ? "No microphone was found. Connect one and try again."
              : "Couldn't start the microphone.",
      });
      return;
    }

    this.speaker ??= makeSpeaker(
      (voiceName) => this.update({ voiceName }),
      (ms) => this.deps.metric("voice.tts_synth", ms),
    );

    // Prefer the local speech service (Parakeet on this machine); fall back to the browser's recogniser.
    let rec: SR;
    if (await localSttAvailable()) {
      rec = new LocalRecognizer(stream) as unknown as SR;
      this.update({ sttEngine: "local" });
    } else {
      const Ctor = getRecognitionCtor();
      if (!Ctor) {
        stream.getTracks().forEach((t) => t.stop());
        this.update({ error: "The local speech service is not running, and this browser has no built-in speech recognition." });
        return;
      }
      rec = new Ctor();
      this.update({ sttEngine: "browser" });
    }
    rec.continuous = true;
    rec.interimResults = true;
    rec.lang = "en-IN";
    rec.maxAlternatives = 1;
    rec.onresult = (e) => this.onResult(e);
    rec.onerror = (e) => this.onRecError(e.error);
    rec.onend = () => this.onRecEnd();
    this.rec = rec;

    this.unsubscribeEngine = this.deps.subscribe((ev, ctx) => this.onEngine(ev, ctx));
    this.update({ active: true, stream, interim: "" });
    this.setState("listening");
    try {
      rec.start();
    } catch {
      /* already started */
    }
  }

  stop() {
    this.endAfterSpeech = false;
    if (!this.snap.active) return;
    this.gen++;
    this.update({ active: false });
    this.clearTimers();
    if (this.eotTimer) clearTimeout(this.eotTimer);
    this.eotTimer = null;
    this.pendingFinal = "";
    this.stopSpeaking();
    try {
      this.rec?.abort();
    } catch {
      /* noop */
    }
    if (this.rec instanceof LocalRecognizer) this.rec.close();
    this.rec = null;
    this.unsubscribeEngine?.();
    this.unsubscribeEngine = null;
    this.snap.stream?.getTracks().forEach((t) => t.stop());
    this.pendingAction = null;
    this.messageId = null;
    this.update({ stream: null, interim: "" });
    this.setState("idle");
  }

  /** Typed text / chip click while the call is active: run it as a spoken turn. */
  sendText(text: string) {
    if (!this.snap.active) return;
    if (this.eotTimer) clearTimeout(this.eotTimer);
    this.eotTimer = null;
    this.pendingFinal = "";
    this.eosAt = null;
    this.pendingAction = null;
    this.update({ interim: "" });
    this.startTurn(text);
  }

  /* ---------------- recognition ---------------- */
  private onRecEnd() {
    // Chrome ends continuous recognition after silence/network hiccups; keep the call alive.
    if (!this.snap.active || !this.rec) return;
    const rec = this.rec;
    setTimeout(() => {
      if (!this.snap.active || this.rec !== rec) return;
      try {
        rec.start();
      } catch {
        setTimeout(() => {
          try {
            if (this.snap.active && this.rec === rec) rec.start();
          } catch {
            /* give up silently; next onend retries */
          }
        }, 500);
      }
    }, 120);
    this.resultFirstSeen.clear();
  }

  private onRecError(error: string) {
    if (error === "no-speech" || error === "aborted") return;
    if (error === "not-allowed" || error === "service-not-allowed" || error === "audio-capture") {
      this.update({
        error:
          error === "audio-capture"
            ? "No microphone input is available."
            : "Speech recognition was blocked. Allow the microphone for this site and try again.",
      });
      this.stop();
      return;
    }
    if (error === "network") {
      this.update({ notice: "Speech recognition lost its connection — retrying…" });
      return;
    }
    this.update({ notice: `Speech recognition error: ${error}` });
  }

  private onResult(e: SREvent) {
    const now = performance.now();
    let interim = "";
    let final = "";
    let firstSeen = now;
    for (let i = e.resultIndex; i < e.results.length; i++) {
      const r = e.results[i];
      if (!this.resultFirstSeen.has(i)) this.resultFirstSeen.set(i, now);
      firstSeen = Math.min(firstSeen, this.resultFirstSeen.get(i)!);
      if (r.isFinal) final += r[0].transcript;
      else interim += r[0].transcript;
    }
    if (this.snap.notice) this.update({ notice: null });
    interim = interim.trim();
    final = final.trim();
    if (interim) this.onInterim(interim, now, firstSeen);
    if (final) this.onFinal(final, now, firstSeen);
  }

  private assistantBusy() {
    return this.snap.state === "thinking" || this.snap.state === "speaking";
  }

  /** Everything the assistant said or queued in the last few seconds, as one body of text. */
  private echoCandidates() {
    const cutoff = performance.now() - SAID_MEMORY_MS;
    this.said = this.said.filter((s) => s.at >= cutoff);
    return [this.currentSentence, ...this.said.map((s) => s.text)];
  }

  /** Echo of the assistant picked up right after it stopped talking. */
  private isTailEcho(text: string) {
    return performance.now() - this.speakingEndedAt < ECHO_TAIL_MS && isEcho(text, this.echoCandidates());
  }

  /** Within a few seconds of our own speech, keep only the words that are not an echo of it. */
  private ownWords(text: string) {
    const recently = this.outstanding > 0 || performance.now() - this.speakingEndedAt < ECHO_GUARD_MS;
    return recently ? stripEchoPrefix(text, this.echoCandidates()) : text;
  }

  private onInterim(text: string, now: number, firstSeen: number) {
    if (this.assistantBusy()) {
      if (!shouldBargeIn(text, this.echoCandidates())) return;
      this.bargeIn(firstSeen);
    } else if (this.snap.state === "listening" && this.isTailEcho(text)) {
      return;
    }
    if (this.eotTimer) {
      clearTimeout(this.eotTimer);
      this.eotTimer = null;
    }
    text = this.ownWords(text);
    if (!text) return;
    this.setState("user_speaking");
    const full = `${this.pendingFinal} ${text}`.trim();
    this.update({ interim: full });
    if (now - this.lastPrefetchAt >= PREFETCH_EVERY_MS) {
      this.lastPrefetchAt = now;
      this.deps.prefetch(full);
    }
  }

  private onFinal(text: string, now: number, firstSeen: number) {
    if (this.assistantBusy()) {
      if (!shouldBargeIn(text, this.echoCandidates())) return;
      this.bargeIn(firstSeen);
    } else if (this.snap.state !== "user_speaking" && this.isTailEcho(text)) {
      return;
    }
    text = this.ownWords(text);
    if (!text) return;
    this.pendingFinal = `${this.pendingFinal} ${text}`.trim();
    this.eosAt = now;
    this.setState("user_speaking");
    this.update({ interim: this.pendingFinal });
    if (this.eotTimer) clearTimeout(this.eotTimer);
    this.eotTimer = setTimeout(() => this.commitUserTurn(), END_OF_TURN_QUIET_MS);
  }

  /* ---------------- turns ---------------- */
  private commitUserTurn() {
    this.eotTimer = null;
    let text = this.pendingFinal.trim();
    this.pendingFinal = "";
    this.update({ interim: "" });
    if (!text || !this.snap.active) {
      this.setState("listening");
      return;
    }
    // Last line of defence against a feedback loop: never send our own speech back as a question.
    const recentlySpoke = this.outstanding > 0 || performance.now() - this.speakingEndedAt < ECHO_GUARD_MS;
    if (recentlySpoke) text = stripEchoPrefix(text, this.echoCandidates());
    if (recentlySpoke && (!text || isEcho(text, this.echoCandidates()))) {
      this.deps.metric("voice.echo_dropped", 0, { chars: text.length });
      this.setState("listening");
      return;
    }

    const p = this.pendingAction;
    if (p && this.deps.isActionPending(p.action_id)) {
      if (p.tier === "confirm" && isAffirmative(text)) return void this.voiceConfirm(p, text);
      if (p.tier === "confirm_otp") {
        const otp = parseOtp(text);
        if (otp) return void this.voiceConfirm(p, text, otp);
        if (isAffirmative(text)) {
          this.deps.noteUser(text);
          this.speakStandalone("Sure. Please read out the six digit code we sent to your phone.");
          return;
        }
      }
    }
    this.pendingAction = null;
    if (isClosing(text)) {
      this.deps.noteUser(text);
      this.endAfterSpeech = true;
      this.speakStandalone(GOODBYE);
      setTimeout(() => this.endAfterSpeech && this.stop(), 6000); // if speech output never reports the end
      return;
    }
    if (isThanks(text)) {
      this.deps.noteUser(text);
      this.speakStandalone(YOU_ARE_WELCOME);
      return;
    }
    if (isBackchannel(text)) {
      this.setState("listening"); // "okay", "mm-hmm" on their own are acknowledgements, not questions
      return;
    }
    this.startTurn(text);
  }

  private resetTurn() {
    this.gen++;
    this.stopSpeaking();
    this.clearTimers();
    this.sentences.reset();
    this.spoken = [];
    this.gotText = false;
    this.lastStatus = null;
    this.firstAudioReported = false;
    this.turnDone = false;
  }

  private startTurn(text: string) {
    this.resetTurn();
    this.messageId = this.deps.send(text);
    if (!this.messageId) {
      this.turnDone = true;
      this.setState("listening");
      return;
    }
    this.setState("thinking");
    const gen = this.gen;
    this.fillerTimers.push(
      setTimeout(() => {
        if (gen === this.gen && !this.gotText && this.snap.state === "thinking")
          this.enqueue(fillerFromStatus(this.lastStatus), true);
      }, FILLER_AFTER_MS),
      setTimeout(() => {
        if (gen === this.gen && !this.gotText && !this.turnDone) this.enqueue(LONG_WAIT_FILLER, true);
      }, LONG_FILLER_AFTER_MS),
    );
  }

  private async voiceConfirm(p: ActionProposal, transcript: string, otp?: string) {
    this.deps.noteUser(transcript);
    this.resetTurn();
    this.messageId = null;
    this.setState("thinking");
    const gen = this.gen;
    const res = await this.deps.confirm(p, otp);
    if (gen !== this.gen || !this.snap.active) return;
    if (!res || res.status !== "otp_invalid") this.pendingAction = null;
    const msg =
      res?.message ||
      (res?.status === "otp_invalid"
        ? "That code didn't match. Please read it out again."
        : "Sorry, I couldn't complete that request.");
    this.speakStandalone(msg);
  }

  private speakStandalone(text: string) {
    this.resetTurn();
    this.turnDone = true;
    this.enqueue(text);
  }

  private onEngine(ev: EngineEvent, ctx: EngineContext) {
    if (!this.snap.active || ctx.messageId !== this.messageId) return;
    switch (ev.name) {
      case "status":
        this.lastStatus = ev.data.text;
        break;
      case "answer.delta":
        if (!this.gotText) {
          this.gotText = true;
          this.clearTimers();
        }
        for (const s of this.sentences.push(ev.data.text)) this.enqueue(s);
        break;
      case "action.proposed":
        if (ev.data.tier !== "read") {
          const { turn_id: _t, seq: _s, ts: _ts, ...proposal } = ev.data;
          void _t;
          void _s;
          void _ts;
          this.pendingAction = proposal;
        }
        break;
      case "turn.completed":
        for (const s of this.sentences.flush()) this.enqueue(s);
        this.finishTurn();
        break;
      case "turn.error":
        if (ev.data.code === "cancelled") return this.finishTurn();
        this.sentences.reset();
        this.enqueue(
          ev.data.retryable
            ? "Sorry, I couldn't get that just now. Please try asking again."
            : "Sorry, I can't help with that right now.",
        );
        this.finishTurn();
        break;
      case "local.ended":
        if (ev.data.reason === "aborted") {
          // aborted by something other than our barge-in (e.g. user typed a message)
          this.gen++;
          this.stopSpeaking();
          this.clearTimers();
          this.turnDone = true;
          this.messageId = null;
          if (this.assistantBusy()) this.setState("listening");
        } else {
          this.enqueue("Sorry, I lost the connection. Please try again.");
          this.finishTurn();
        }
        break;
    }
  }

  private finishTurn() {
    this.turnDone = true;
    this.clearTimers();
    if (this.outstanding === 0 && this.assistantBusy()) this.setState("listening");
  }

  /* ---------------- speech output ---------------- */
  private enqueue(sentence: string, filler = false) {
    const speakable = toSpeakable(sentence);
    if (!speakable || !/[\p{L}\p{N}]/u.test(speakable)) return;
    const gen = this.gen;
    this.said.push({ text: speakable, at: performance.now() });
    const onstart = () => {
      if (gen !== this.gen) return;
      this.currentSentence = speakable;
      this.currentRaw = filler ? null : stripMarkdown(sentence).trim();
      if (!this.firstAudioReported && this.eosAt != null) {
        this.firstAudioReported = true;
        this.deps.metric("voice.eos_to_first_audio", performance.now() - this.eosAt, {
          first_audio: filler ? "filler" : "answer",
        });
      }
      if (this.snap.active) this.setState("speaking");
    };
    const done = () => {
      if (gen !== this.gen) return;
      this.outstanding = Math.max(0, this.outstanding - 1);
      if (!filler) this.spoken.push(stripMarkdown(sentence).trim());
      const last = this.said.findLast((x) => x.text === speakable);
      if (last) last.at = performance.now(); // the echo window runs from when it finished playing
      this.currentSentence = null;
      this.currentRaw = null;
      this.speakingEndedAt = performance.now();
      if (this.outstanding === 0) {
        if (this.endAfterSpeech) {
          this.endAfterSpeech = false;
          this.stop(); // goodbye has been said: end the call
          return;
        }
        if (this.turnDone && this.snap.active && this.assistantBusy()) {
          this.setState("listening");
          this.restartRecognition(); // start a fresh result: echo heard during playback is never glued onto the next turn
        }
      }
    };
    this.outstanding++;
    this.speaker?.speak({ text: speakable, onstart, onend: done });
  }

  private stopSpeaking() {
    this.outstanding = 0;
    this.currentSentence = null;
    this.currentRaw = null;
    this.speaker?.cancel();
  }

  private clearTimers() {
    this.fillerTimers.forEach(clearTimeout);
    this.fillerTimers = [];
  }

  /** Begin a new recognition session, discarding whatever the current one has accumulated. */
  private restartRecognition() {
    if (!this.rec || !this.snap.active || this.snap.state === "user_speaking") return;
    this.pendingFinal = "";
    this.resultFirstSeen.clear();
    try {
      this.rec.abort(); // onRecEnd starts it again
    } catch {
      /* not running */
    }
  }

  /** User talked over the assistant: stop audio, cancel the turn, report how quickly we stopped. */
  private bargeIn(firstHeardAt: number) {
    const spokenText = [...this.spoken, ...(this.currentRaw ? [this.currentRaw] : [])].join(" ");
    const messageId = this.messageId;
    this.gen++;
    this.stopSpeaking();
    this.clearTimers();
    this.sentences.reset();
    this.turnDone = true;
    this.messageId = null;
    if (messageId) this.deps.interrupt(messageId, spokenText);
    this.deps.metric("voice.bargein_stop", performance.now() - firstHeardAt, { spoken_chars: spokenText.length });
    this.setState("interrupted");
  }
}
