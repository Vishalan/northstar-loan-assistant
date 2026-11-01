"use client";

// Speech output behind one interface, so the voice can be swapped without touching the voice controller.
//   BrowserSpeaker  the browser's own speechSynthesis voice (default, no setup)
//   ServerSpeaker   POST {text} to a speech service's /v1/tts (Kokoro on our GPU box, or any engine the
//                   service is configured with). Sentences are fetched in parallel and played in order; a
//                   sentence whose audio fails falls back to the browser voice.
// Set NEXT_PUBLIC_TTS_URL to the speech service to use the server voice.

export type SpeakItem = { text: string; onstart: () => void; onend: () => void };

export interface Speaker {
  readonly name: string;
  speak(item: SpeakItem): void;
  cancel(): void;
}

export const TTS_URL = (process.env.NEXT_PUBLIC_TTS_URL ?? "").replace(/\/$/, "");

function pickVoice(): SpeechSynthesisVoice | null {
  const voices = window.speechSynthesis.getVoices();
  const by = (lang: string) =>
    voices.filter((v) => v.lang.replace("_", "-").toLowerCase() === lang.toLowerCase());
  for (const lang of ["en-IN", "en-GB", "en-US"]) {
    const list = by(lang);
    if (list.length) return list.find((v) => /google|natural|neural|premium|enhanced/i.test(v.name)) ?? list[0];
  }
  return voices.find((v) => v.lang.toLowerCase().startsWith("en")) ?? null;
}

export class BrowserSpeaker implements Speaker {
  private voice: SpeechSynthesisVoice | null = null;
  private utterances: SpeechSynthesisUtterance[] = []; // keep refs (Chrome GC bug drops onend)

  constructor(onVoice?: (name: string | null) => void) {
    const load = () => {
      this.voice = pickVoice();
      onVoice?.(this.voice ? `${this.voice.name} (${this.voice.lang})` : null);
    };
    load();
    window.speechSynthesis.onvoiceschanged = load;
  }

  get name() {
    return this.voice ? `${this.voice.name} (${this.voice.lang})` : "browser";
  }

  speak({ text, onstart, onend }: SpeakItem) {
    const u = new SpeechSynthesisUtterance(text);
    if (this.voice) u.voice = this.voice;
    u.lang = this.voice?.lang ?? "en-IN";
    u.rate = 1.04;
    u.onstart = onstart;
    const done = () => {
      this.utterances = this.utterances.filter((x) => x !== u);
      onend();
    };
    u.onend = done;
    u.onerror = done;
    this.utterances.push(u);
    window.speechSynthesis.speak(u);
  }

  cancel() {
    this.utterances = [];
    window.speechSynthesis.cancel();
  }
}

type Pending = SpeakItem & { audio: Promise<Blob | null> };

export class ServerSpeaker implements Speaker {
  readonly name: string;
  private queue: Pending[] = [];
  private playing: HTMLAudioElement | null = null;
  private busy = false;
  private ctl = new AbortController();

  constructor(
    private url: string,
    private fallback: Speaker,
    private onSynth?: (ms: number) => void,
  ) {
    this.name = `server voice (${new URL(url).host})`;
  }

  speak(item: SpeakItem) {
    const started = performance.now();
    const audio = fetch(`${this.url}/v1/tts`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ text: item.text }),
      signal: this.ctl.signal,
    })
      .then((r) => (r.ok ? r.blob() : null))
      .then((b) => {
        if (b) this.onSynth?.(performance.now() - started);
        return b;
      })
      .catch(() => null);
    this.queue.push({ ...item, audio });
    void this.drain();
  }

  private async drain() {
    if (this.busy) return;
    this.busy = true;
    const ctl = this.ctl;
    while (this.queue.length && !ctl.signal.aborted) {
      const item = this.queue.shift()!;
      const blob = await item.audio;
      if (ctl.signal.aborted) break;
      if (!blob) {
        await new Promise<void>((resolve) =>
          this.fallback.speak({ ...item, onend: () => (item.onend(), resolve()) }),
        );
        continue;
      }
      const src = URL.createObjectURL(blob);
      const el = new Audio(src);
      this.playing = el;
      await new Promise<void>((resolve) => {
        const end = () => {
          URL.revokeObjectURL(src);
          el.onended = el.onerror = el.onpause = null;
          item.onend();
          resolve();
        };
        el.onplaying = () => item.onstart();
        el.onended = end;
        el.onerror = end;
        el.onpause = () => ctl.signal.aborted && end();
        el.play().catch(end);
      });
      if (this.ctl === ctl) this.playing = null;
    }
    if (this.ctl === ctl) this.busy = false; // a cancel() mid-drain has already handed over to a new drain
  }

  cancel() {
    this.ctl.abort();
    this.ctl = new AbortController();
    this.queue = [];
    this.playing?.pause();
    this.playing = null;
    this.busy = false;
    this.fallback.cancel();
  }
}

export function makeSpeaker(onVoice: (name: string | null) => void, onSynth?: (ms: number) => void): Speaker {
  const browser = new BrowserSpeaker(TTS_URL ? undefined : onVoice);
  if (!TTS_URL) return browser;
  const server = new ServerSpeaker(TTS_URL, browser, onSynth);
  onVoice(server.name);
  return server;
}
