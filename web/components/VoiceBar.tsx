"use client";

import { useEffect, useRef } from "react";
import { cx } from "@/lib/format";
import type { VoiceState } from "@/lib/voice-controller";
import { IconPhoneOff } from "./icons";

const LABEL: Record<VoiceState, string> = {
  idle: "Voice off",
  listening: "Listening",
  user_speaking: "Hearing you",
  thinking: "Thinking",
  speaking: "Speaking",
  interrupted: "Go ahead",
};

/** Live mic level bars drawn from an AnalyserNode; falls back to a breathing dot. */
function Waveform({ stream, state }: { stream: MediaStream | null; state: VoiceState }) {
  const barsRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!stream || !barsRef.current) return;
    const AC = window.AudioContext ?? (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
    if (!AC) return;
    const ctx = new AC();
    const src = ctx.createMediaStreamSource(stream);
    const an = ctx.createAnalyser();
    an.fftSize = 256;
    an.smoothingTimeConstant = 0.7;
    src.connect(an);
    const buf = new Uint8Array(an.frequencyBinCount);
    const bars = Array.from(barsRef.current.children) as HTMLElement[];
    let raf = 0;
    const tick = () => {
      an.getByteFrequencyData(buf);
      const step = Math.floor(buf.length / 2 / bars.length) || 1;
      bars.forEach((b, i) => {
        let sum = 0;
        for (let j = 0; j < step; j++) sum += buf[i * step + j + 2] ?? 0;
        const v = Math.min(1, sum / step / 160);
        b.style.transform = `scaleY(${0.15 + v * 0.85})`;
      });
      raf = requestAnimationFrame(tick);
    };
    tick();
    return () => {
      cancelAnimationFrame(raf);
      src.disconnect();
      void ctx.close();
    };
  }, [stream]);

  const speaking = state === "speaking";
  return (
    <div className="relative grid size-11 shrink-0 place-items-center">
      <span
        className={cx(
          "breathe absolute inset-0 rounded-full",
          speaking ? "bg-accent" : state === "thinking" ? "bg-line-strong" : "bg-brand",
        )}
        aria-hidden
      />
      <div
        ref={barsRef}
        className="relative flex h-6 items-center gap-[3px]"
        aria-hidden
      >
        {Array.from({ length: 5 }, (_, i) => (
          <span
            key={i}
            className={cx(
              "h-full w-[3px] origin-center rounded-full transition-transform duration-75",
              speaking ? "bg-accent" : "bg-brand",
            )}
            style={{ transform: "scaleY(0.2)" }}
          />
        ))}
      </div>
    </div>
  );
}

export function VoiceBar({
  state,
  interim,
  error,
  notice,
  stream,
  voiceName,
  sttEngine,
  onEnd,
}: {
  state: VoiceState;
  interim: string;
  error: string | null;
  notice: string | null;
  stream: MediaStream | null;
  voiceName: string | null;
  sttEngine?: "local" | "browser" | null;
  onEnd: () => void;
}) {
  return (
    <div
      className="rise flex items-center gap-3 rounded-2xl border border-brand/30 bg-brand-soft/70 px-3 py-2.5"
      role="region"
      aria-label="Voice call"
    >
      <Waveform stream={stream} state={state} />
      <div className="min-w-0 flex-1">
        <p className="flex items-center gap-2 text-[13px] font-semibold text-brand" aria-live="polite">
          {LABEL[state]}
          {state === "thinking" && <span className="text-[12px] font-normal text-muted">· working on it</span>}
          {sttEngine && (
            <span className="ml-auto text-[11px] font-normal text-muted" title="Speech recognition engine">
              {sttEngine === "local" ? "On-device recognition" : "Browser recognition"}
            </span>
          )}
        </p>
        <p className={cx("truncate text-[13.5px]", interim ? "text-ink" : "text-muted")}>
          {interim ? `“${interim}”` : notice ?? error ?? (state === "speaking" ? "You can interrupt any time." : "Ask about your loan, card or payments.")}
        </p>
        {voiceName && <p className="sr-only">Voice: {voiceName}</p>}
      </div>
      <button
        type="button"
        onClick={onEnd}
        className="inline-flex shrink-0 items-center gap-1.5 rounded-full bg-bad px-3.5 py-2 text-[13px] font-semibold text-white hover:opacity-90"
      >
        <IconPhoneOff size={16} />
        <span className="hidden sm:inline">End</span>
        <span className="sr-only sm:hidden">End voice call</span>
      </button>
    </div>
  );
}
