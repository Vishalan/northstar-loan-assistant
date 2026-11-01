"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { cx, formatMs } from "@/lib/format";
import type { ChaosPreset, ChaosState } from "@/lib/types";
import { IconX } from "./icons";

const PRESETS: { id: ChaosPreset; label: string; blurb: string }[] = [
  { id: "calm", label: "Calm", blurb: "All core systems fast and healthy." },
  { id: "realistic", label: "Realistic", blurb: "Typical production latency with occasional blips." },
  { id: "bad_day", label: "Bad day", blurb: "Slow core banking, flaky card processor. Watch degradation." },
];

export function DemoDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [state, setState] = useState<ChaosState | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    closeRef.current?.focus();
    api.chaos().then(setState, (e: Error) => setError(e.message));
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  async function choose(p: ChaosPreset) {
    setBusy(p);
    setError(null);
    try {
      setState(await api.setChaos(p));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex justify-end" role="dialog" aria-modal="true" aria-label="Demo controls">
      <button className="absolute inset-0 bg-ink/30" aria-label="Close demo controls" onClick={onClose} />
      <aside className="rise relative flex h-full w-full max-w-sm flex-col border-l border-line bg-surface shadow-pop">
        <div className="flex items-center justify-between border-b border-line px-5 py-4">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-accent">Presenter only</p>
            <h2 className="font-display text-xl font-semibold">Demo controls</h2>
          </div>
          <button
            ref={closeRef}
            onClick={onClose}
            className="grid size-9 place-items-center rounded-md hover:bg-surface-2"
            aria-label="Close"
          >
            <IconX size={18} />
          </button>
        </div>
        <div className="scroll-thin flex-1 space-y-5 overflow-y-auto px-5 py-5">
          <section>
            <h3 className="text-[13px] font-semibold text-ink-2">Backend conditions</h3>
            <p className="mt-1 text-[12.5px] text-muted">
              Injects latency and failures into the simulated core systems so you can show graceful degradation.
            </p>
            <div className="mt-3 grid gap-2">
              {PRESETS.map((p) => {
                const active = state?.preset === p.id;
                return (
                  <button
                    key={p.id}
                    onClick={() => choose(p.id)}
                    disabled={busy !== null}
                    aria-pressed={active}
                    className={cx(
                      "rounded-lg border px-3.5 py-2.5 text-left transition-colors disabled:opacity-60",
                      active ? "border-brand bg-brand-soft" : "border-line hover:border-line-strong hover:bg-surface-2",
                    )}
                  >
                    <span className="flex items-center justify-between text-[14px] font-semibold">
                      {p.label}
                      {active && <span className="text-[11px] font-semibold uppercase tracking-wide text-brand">Active</span>}
                      {busy === p.id && <span className="text-[11px] text-muted">Applying…</span>}
                    </span>
                    <span className="mt-0.5 block text-[12.5px] text-muted">{p.blurb}</span>
                  </button>
                );
              })}
            </div>
            {error && <p className="mt-2 text-[12.5px] text-bad">{error}</p>}
          </section>
          {state && Object.keys(state.systems ?? {}).length > 0 && (
            <section>
              <h3 className="text-[13px] font-semibold text-ink-2">Simulated systems</h3>
              <table className="mt-2 w-full text-[12.5px]">
                <thead>
                  <tr className="text-left text-muted">
                    <th className="py-1 font-medium">System</th>
                    <th className="py-1 text-right font-medium">Median</th>
                    <th className="py-1 text-right font-medium">Fail rate</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(state.systems).map(([name, s]) => (
                    <tr key={name} className="border-t border-line">
                      <td className="py-1.5">{name}</td>
                      <td className="num py-1.5 text-right">{formatMs(s.median_ms)}</td>
                      <td className={cx("num py-1.5 text-right", s.fail_rate > 0.05 && "text-bad")}>
                        {(s.fail_rate * 100).toFixed(0)}%
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          )}
          <p className="text-[12px] text-muted">
            Open with <code className="rounded bg-sunken px-1">?demo=1</code>; hide with{" "}
            <code className="rounded bg-sunken px-1">?demo=0</code>.
          </p>
        </div>
      </aside>
    </div>
  );
}
