"use client";

import { useEffect, useRef, useState } from "react";
import { type AssistantMessage, type ToolProgress, useChat } from "@/lib/chat-store";
import { cx, formatMs } from "@/lib/format";
import { turnEngine } from "@/lib/turn-engine";
import { useVoice } from "@/lib/use-voice";
import { ActionCard } from "./ActionCard";
import { CardView } from "./CardView";
import { BrandMark, IconCheck, IconMic, IconSend, IconSpinner, IconWarn } from "./icons";
import { Markdown } from "./Markdown";
import { VoiceBar } from "./VoiceBar";

export function Conversation({ customerName }: { customerName?: string }) {
  const messages = useChat((s) => s.messages);
  const suggestions = useChat((s) => s.suggestions);
  const inFlight = useChat((s) => s.inFlight);
  const sessionId = useChat((s) => s.sessionId);
  const voice = useVoice();
  const scrollRef = useRef<HTMLDivElement>(null);
  const stickRef = useRef(true);

  // Keep pinned to the bottom while streaming unless the user scrolled up.
  useEffect(() => {
    const el = scrollRef.current;
    if (el && stickRef.current) el.scrollTo({ top: el.scrollHeight });
  }, [messages, suggestions]);

  // In voice mode, typed messages and chip clicks go through the voice controller so answers are spoken.
  const send = (text: string) => (voice.active ? voice.sendText(text) : void turnEngine.send(text, "text"));
  const first = customerName?.split(/\s+/)[0];

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div
        ref={scrollRef}
        onScroll={(e) => {
          const el = e.currentTarget;
          stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
        }}
        className="scroll-thin min-h-0 flex-1 overflow-y-auto"
      >
        <div className="mx-auto w-full max-w-[760px] px-3 pb-6 pt-6 sm:px-6">
          {messages.length === 0 && (
            <div className="rise pb-6 pt-[6vh]">
              <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-accent">Northstar Assistant</p>
              <h1 className="mt-2 font-display text-[30px] font-semibold leading-[1.1] tracking-tight sm:text-[36px]">
                {first ? `Namaste, ${first}.` : "Namaste."} How can I help with your accounts today?
              </h1>
              <p className="mt-3 max-w-xl text-[14.5px] leading-relaxed text-ink-2">
                I answer from your own loan and card records, show you the evidence behind every figure, and can raise
                service requests once you confirm. Type, or tap the mic to talk.
              </p>
            </div>
          )}

          <div role="log" aria-live="polite" aria-relevant="additions" aria-label="Conversation" className="space-y-6">
            {messages.map((m) =>
              m.role === "user" ? (
                <div key={m.id} className="rise flex justify-end">
                  <div className="max-w-[85%] rounded-2xl rounded-br-md bg-brand px-4 py-2.5 text-[14.5px] leading-relaxed text-brand-ink">
                    {m.channel === "voice" && (
                      <span className="mb-0.5 flex items-center gap-1 text-[10.5px] font-semibold uppercase tracking-wide opacity-70">
                        <IconMic size={11} /> Spoken
                      </span>
                    )}
                    <span className="whitespace-pre-wrap">{m.text}</span>
                  </div>
                </div>
              ) : (
                <AssistantBubble key={m.id} m={m} onAction={send} />
              ),
            )}
          </div>

          {suggestions.length > 0 && !inFlight && (
            <div className="mt-5 flex flex-wrap gap-2" aria-label="Suggested questions">
              {suggestions.map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => send(s)}
                  disabled={!sessionId}
                  className="rise rounded-full border border-line-strong bg-surface px-3.5 py-1.5 text-[13px] text-ink-2 shadow-card transition-colors hover:border-brand hover:text-brand disabled:opacity-50"
                >
                  {s}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="border-t border-line bg-surface/85 px-3 pb-3 pt-3 backdrop-blur sm:px-6">
        <div className="mx-auto w-full max-w-[760px] space-y-2">
          {voice.active && (
            <VoiceBar
              state={voice.state}
              interim={voice.interim}
              error={voice.error}
              notice={voice.notice}
              stream={voice.stream}
              voiceName={voice.voiceName}
              sttEngine={voice.sttEngine}
              onEnd={voice.stop}
            />
          )}
          {!voice.active && voice.error && (
            <p role="alert" className="flex items-start gap-2 rounded-lg border border-warn/40 bg-warn-soft px-3 py-2 text-[12.5px] text-warn">
              <IconWarn size={15} className="mt-px shrink-0" /> {voice.error}
            </p>
          )}
          <Composer
            disabled={!sessionId}
            busy={inFlight}
            voiceActive={voice.active}
            voiceSupported={voice.supported}
            onSend={send}
            onMic={() => (voice.active ? voice.stop() : void voice.start())}
          />
        </div>
      </div>
    </div>
  );
}

function AssistantBubble({ m, onAction }: { m: AssistantMessage; onAction: (p: string) => void }) {
  const streaming = m.state === "streaming";
  return (
    <article className="rise flex gap-3" aria-busy={streaming}>
      <div className="mt-0.5 shrink-0">
        <BrandMark size={26} />
      </div>
      <div className="min-w-0 flex-1 space-y-3">
        {(m.text || streaming) && (
          <div className="text-[15px] leading-relaxed text-ink">
            {m.text ? (
              <div className={cx(streaming && "streaming")}>
                <Markdown text={m.text} />
              </div>
            ) : (
              <span className="sr-only">Assistant is working</span>
            )}
          </div>
        )}

        <ProgressLine m={m} />

        {m.attachments.map((a) =>
          a.kind === "card" ? (
            <CardView key={a.key} card={a.card} onAction={onAction} />
          ) : (
            <ActionCard key={a.key} proposal={a.proposal} />
          ),
        )}

        <div className="flex flex-wrap items-center gap-2 text-[11px] text-muted">
          {m.state === "interrupted" && (
            <span className="rounded-full border border-line px-2 py-0.5 font-medium">Interrupted</span>
          )}
          {m.corrected && (
            <span className="rounded-full bg-warn-soft px-2 py-0.5 font-medium text-warn" title="The answer was re-checked against your records and corrected.">
              Corrected after verification
            </span>
          )}
          {m.state === "done" && m.verified && !m.corrected && (
            <span className="inline-flex items-center gap-1 text-ok">
              <IconCheck size={12} /> Figures verified
            </span>
          )}
          {m.state === "done" && m.mode === "fallback" && (
            <span className="rounded-full bg-sunken px-2 py-0.5">Simplified answer</span>
          )}
          {m.state === "done" && m.timings?.total_ms != null && (
            <span className="num">
              {m.timings.first_token_ms != null && <>first words {formatMs(m.timings.first_token_ms)} · </>}
              total {formatMs(m.timings.total_ms)}
            </span>
          )}
        </div>

        {m.state === "error" && m.error && (
          <p role="alert" className="flex items-start gap-2 rounded-lg border border-bad/30 bg-bad-soft px-3 py-2 text-[13px] text-bad">
            <IconWarn size={15} className="mt-px shrink-0" />
            <span>
              {m.error.message}
              {m.error.retryable && " Please try again."}
            </span>
          </p>
        )}
      </div>
    </article>
  );
}

function ToolChip({ t }: { t: ToolProgress }) {
  const bad = t.state === "unavailable";
  const warn = t.state === "degraded";
  return (
    <li
      className={cx(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[12px]",
        bad ? "border-bad/30 bg-bad-soft text-bad" : warn ? "border-warn/30 bg-warn-soft text-warn" : "border-line bg-surface text-ink-2",
      )}
    >
      {t.state === "running" ? (
        <IconSpinner size={13} className="text-brand" />
      ) : t.state === "ok" ? (
        <IconCheck size={13} className="text-ok" />
      ) : (
        <IconWarn size={13} />
      )}
      <span>{t.label}</span>
      {t.latency_ms != null && (
        <span className="num text-[11px] opacity-70">
          {t.from_cache ? "cached" : formatMs(t.latency_ms)}
        </span>
      )}
      {bad && <span className="sr-only">unavailable</span>}
      {warn && <span className="sr-only">degraded</span>}
    </li>
  );
}

function ProgressLine({ m }: { m: AssistantMessage }) {
  const streaming = m.state === "streaming";
  const [open, setOpen] = useState(false);
  if (!streaming && m.tools.length === 0) return null;

  if (!streaming) {
    const problems = m.tools.filter((t) => t.state !== "ok").length;
    return (
      <div>
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          className="inline-flex items-center gap-1.5 rounded-md text-[12px] text-muted hover:text-ink-2"
        >
          {problems ? <IconWarn size={13} className="text-warn" /> : <IconCheck size={13} className="text-ok" />}
          Checked {m.tools.length} {m.tools.length === 1 ? "system" : "systems"}
          {problems > 0 && <span className="text-warn">· {problems} with issues</span>}
        </button>
        {open && (
          <ul className="mt-2 flex flex-wrap gap-1.5">
            {m.tools.map((t) => (
              <ToolChip key={t.call_id} t={t} />
            ))}
          </ul>
        )}
      </div>
    );
  }

  return (
    <div className="space-y-2" role="status">
      <p className="flex items-center gap-2 text-[13px] text-ink-2">
        <span className="relative flex size-2">
          <span className="absolute inline-flex size-full animate-ping rounded-full bg-brand opacity-50" />
          <span className="relative inline-flex size-2 rounded-full bg-brand" />
        </span>
        {m.status ?? (m.text ? "Writing…" : "Thinking…")}
      </p>
      {m.tools.length > 0 && (
        <ul className="flex flex-wrap gap-1.5" aria-label="Systems being checked">
          {m.tools.map((t) => (
            <ToolChip key={t.call_id} t={t} />
          ))}
        </ul>
      )}
    </div>
  );
}

function Composer({
  disabled,
  busy,
  voiceActive,
  voiceSupported,
  onSend,
  onMic,
}: {
  disabled: boolean;
  busy: boolean;
  voiceActive: boolean;
  voiceSupported: boolean;
  onSend: (t: string) => void;
  onMic: () => void;
}) {
  const [text, setText] = useState("");
  const ref = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }, [text]);

  function submit() {
    const t = text.trim();
    if (!t || disabled) return;
    onSend(t);
    setText("");
  }

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
      className="flex items-end gap-2 rounded-2xl border border-line-strong bg-surface p-1.5 pl-3.5 shadow-card focus-within:border-brand focus-within:ring-2 focus-within:ring-brand/15"
    >
      <label htmlFor="composer" className="sr-only">
        Message the assistant
      </label>
      <textarea
        id="composer"
        ref={ref}
        rows={1}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault();
            submit();
          }
        }}
        placeholder={voiceActive ? "Speak, or type here…" : "Ask about your EMI, payments, prepayment…"}
        disabled={disabled}
        className="min-h-[40px] flex-1 resize-none bg-transparent py-2 text-[15px] leading-6 outline-none focus-visible:outline-none placeholder:text-muted disabled:opacity-50"
      />
      <button
        type="button"
        onClick={onMic}
        aria-pressed={voiceActive}
        aria-label={voiceActive ? "End voice mode" : "Start voice mode"}
        title={voiceSupported ? (voiceActive ? "End voice mode" : "Talk to the assistant") : "Voice needs Chrome or Edge"}
        disabled={disabled}
        className={cx(
          "grid size-10 shrink-0 place-items-center rounded-xl transition-colors disabled:opacity-40",
          voiceActive ? "bg-accent text-white" : "text-ink-2 hover:bg-surface-2 hover:text-brand",
        )}
      >
        <IconMic size={19} />
      </button>
      <button
        type="submit"
        disabled={disabled || !text.trim()}
        aria-label={busy ? "Send (stops the current answer)" : "Send"}
        className="grid size-10 shrink-0 place-items-center rounded-xl bg-brand text-brand-ink transition-opacity hover:bg-brand-2 disabled:opacity-35"
      >
        <IconSend size={18} />
      </button>
    </form>
  );
}
