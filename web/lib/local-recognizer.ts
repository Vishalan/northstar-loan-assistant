// Local speech recognition: streams the microphone to the Northstar speech service (Parakeet on this machine)
// and exposes the same surface as the browser's SpeechRecognition, so the voice controller does not change.
//
// Audio: the shared mic stream (echo cancellation on) → AudioWorklet → 16 kHz mono PCM16 in 100 ms frames → WS.
// Results: the service sends start / partial / final per utterance; each utterance is one recognition result.

// Defaults to the local service; set NEXT_PUBLIC_STT_URL="" to always use the browser recogniser.
export const STT_URL = (process.env.NEXT_PUBLIC_STT_URL ?? "http://localhost:8200").replace(/\/$/, "");

type Result = { isFinal: boolean; 0: { transcript: string } };
type RecEvent = { resultIndex: number; results: ArrayLike<Result> };

const WORKLET = `
class Tap extends AudioWorkletProcessor {
  process(inputs) { const ch = inputs[0] && inputs[0][0]; if (ch) this.port.postMessage(ch.slice(0)); return true; }
}
registerProcessor("northstar-tap", Tap);`;

const TARGET_RATE = 16000;
const FRAME_SAMPLES = 1600; // 100 ms at 16 kHz

/** Is the local speech service up? Checked once when a voice call starts. */
export async function localSttAvailable(timeoutMs = 800): Promise<boolean> {
  if (!STT_URL) return false;
  try {
    const ctl = new AbortController();
    const t = setTimeout(() => ctl.abort(), timeoutMs);
    const r = await fetch(`${STT_URL}/healthz`, { signal: ctl.signal });
    clearTimeout(t);
    return r.ok;
  } catch {
    return false;
  }
}

export class LocalRecognizer {
  continuous = true;
  interimResults = true;
  lang = "en-IN";
  maxAlternatives = 1;
  onresult: ((e: RecEvent) => void) | null = null;
  onerror: ((e: { error: string; message?: string }) => void) | null = null;
  onend: (() => void) | null = null;
  onstart: (() => void) | null = null;

  private ws: WebSocket | null = null;
  private ctx: AudioContext | null = null;
  private node: AudioWorkletNode | null = null;
  private running = false;
  private closed = false;
  private pending = new Float32Array(0);
  private results: Result[] = [];
  private indexById = new Map<number, number>();

  constructor(private stream: MediaStream) {}

  start() {
    this.running = true;
    if (!this.ws) void this.open();
    else this.sendJSON({ type: "reset" });
    setTimeout(() => this.onstart?.(), 0);
  }

  /** Stop listening; drop the utterance in progress. The controller calls start() again to resume. */
  abort() {
    this.running = false;
    this.sendJSON({ type: "reset" });
    this.results = [];
    this.indexById.clear();
    setTimeout(() => this.onend?.(), 0);
  }

  stop() {
    this.abort();
  }

  /** Release the socket and the audio graph (end of the voice call). */
  close() {
    this.closed = true;
    this.running = false;
    this.ws?.close();
    this.node?.disconnect();
    void this.ctx?.close();
    this.ws = this.ctx = this.node = null;
  }

  private sendJSON(msg: object) {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(msg));
  }

  private async open() {
    const wsUrl = STT_URL.replace(/^http/, "ws") + "/v1/stt";
    const ws = new WebSocket(wsUrl);
    ws.binaryType = "arraybuffer";
    this.ws = ws;
    ws.onmessage = (ev) => this.onMessage(JSON.parse(String(ev.data)));
    ws.onerror = () => this.onerror?.({ error: "network", message: "Local speech service unreachable" });
    ws.onclose = () => {
      this.ws = null;
      if (!this.closed) setTimeout(() => this.onend?.(), 0); // controller restarts us, which reconnects
    };

    if (this.ctx) return; // reconnect: the audio graph is still running, only the socket was recreated
    // 16 kHz context where the browser supports it (Chrome resamples for us); otherwise we resample below.
    let ctx: AudioContext;
    try {
      ctx = new AudioContext({ sampleRate: TARGET_RATE });
    } catch {
      ctx = new AudioContext();
    }
    this.ctx = ctx;
    const url = URL.createObjectURL(new Blob([WORKLET], { type: "application/javascript" }));
    await ctx.audioWorklet.addModule(url);
    URL.revokeObjectURL(url);
    const source = ctx.createMediaStreamSource(this.stream);
    const node = new AudioWorkletNode(ctx, "northstar-tap");
    this.node = node;
    node.port.onmessage = (e: MessageEvent<Float32Array>) => this.onAudio(e.data, ctx.sampleRate);
    source.connect(node); // not connected to the destination: nothing is played back
  }

  private onAudio(chunk: Float32Array, rate: number) {
    if (!this.running || this.ws?.readyState !== WebSocket.OPEN) return;
    const samples = rate === TARGET_RATE ? chunk : resample(chunk, rate, TARGET_RATE);
    const merged = new Float32Array(this.pending.length + samples.length);
    merged.set(this.pending);
    merged.set(samples, this.pending.length);
    let offset = 0;
    while (merged.length - offset >= FRAME_SAMPLES) {
      this.ws.send(toPcm16(merged.subarray(offset, offset + FRAME_SAMPLES)));
      offset += FRAME_SAMPLES;
    }
    this.pending = merged.slice(offset);
  }

  private onMessage(msg: { type: string; id?: number; text?: string; decode_ms?: number }) {
    if (!this.running || msg.id === undefined) return;
    if (msg.type !== "partial" && msg.type !== "final") return;
    let idx = this.indexById.get(msg.id);
    if (idx === undefined) {
      idx = this.results.length;
      this.indexById.set(msg.id, idx);
      this.results.push({ isFinal: false, 0: { transcript: "" } });
    }
    this.results[idx] = { isFinal: msg.type === "final", 0: { transcript: msg.text ?? "" } };
    this.onresult?.({ resultIndex: idx, results: this.results });
  }
}

function toPcm16(f: Float32Array): ArrayBuffer {
  const out = new Int16Array(f.length);
  for (let i = 0; i < f.length; i++) out[i] = Math.max(-1, Math.min(1, f[i])) * 0x7fff;
  return out.buffer;
}

/** Linear-interpolation resampler; only used when the browser will not open a 16 kHz context. */
export function resample(input: Float32Array, from: number, to: number): Float32Array {
  const ratio = from / to;
  const out = new Float32Array(Math.floor(input.length / ratio));
  for (let i = 0; i < out.length; i++) {
    const pos = i * ratio;
    const j = Math.floor(pos);
    const frac = pos - j;
    out[i] = input[j] * (1 - frac) + (input[Math.min(j + 1, input.length - 1)] ?? 0) * frac;
  }
  return out;
}
