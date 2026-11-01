"use client";

import { useEffect, useState } from "react";
import { AppShell, PageHeader } from "@/components/AppShell";
import { api } from "@/lib/api";
import { cx, formatDateTime, formatMs, humanize } from "@/lib/format";
import type { LatencyMetrics, StageStat } from "@/lib/types";

const REFRESH_MS = 5000;

export default function LatencyPage() {
  const [data, setData] = useState<LatencyMetrics | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);
  const [paused, setPaused] = useState(false);

  useEffect(() => {
    let alive = true;
    const load = () =>
      api.latency(200).then(
        (d) => {
          if (!alive) return;
          setData(d);
          setError(null);
          setUpdatedAt(new Date());
        },
        (e: Error) => alive && setError(e.message),
      );
    void load();
    if (paused) return () => void (alive = false);
    const t = setInterval(load, REFRESH_MS);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, [paused]);

  return (
    <AppShell>
      <div className="mx-auto w-full max-w-6xl px-4 py-8 sm:px-6">
        <PageHeader kicker="Performance evidence" title="Latency">
          <div className="flex items-center gap-3 text-[12.5px] text-muted">
            <span className="flex items-center gap-1.5" aria-live="polite">
              <span className={cx("size-2 rounded-full", paused ? "bg-line-strong" : "bg-ok", !paused && "animate-pulse")} />
              {updatedAt ? `Updated ${updatedAt.toLocaleTimeString("en-IN")}` : "Loading…"}
            </span>
            <button
              onClick={() => setPaused((p) => !p)}
              className="rounded-md border border-line-strong px-2.5 py-1 font-semibold text-ink-2 hover:bg-surface"
            >
              {paused ? "Resume" : "Pause"}
            </button>
          </div>
        </PageHeader>
        <p className="mt-2 max-w-3xl text-[14px] text-ink-2">
          Measured over the last 200 turns. p50 is the typical experience, p95 the slow tail. Refreshes every 5 seconds.
        </p>
        {error && <p className="mt-4 rounded-lg border border-bad/30 bg-bad-soft px-3 py-2 text-[13px] text-bad">{error}</p>}

        {data && (
          <div className="mt-6 grid gap-6 lg:grid-cols-2">
            <Panel title="Pipeline stages" className="lg:col-span-2">
              <StageBars stages={data.stages} />
              <StageTable stages={data.stages} />
            </Panel>

            <Panel title="Back-end systems">
              <table className="w-full text-[13px]">
                <thead className="text-left text-[12px] text-muted">
                  <tr>
                    <th className="py-2 font-semibold">System</th>
                    <th className="py-2 text-right font-semibold">Calls</th>
                    <th className="py-2 text-right font-semibold">p50</th>
                    <th className="py-2 text-right font-semibold">p95</th>
                    <th className="py-2 text-right font-semibold">Errors</th>
                  </tr>
                </thead>
                <tbody>
                  {data.systems.map((s) => (
                    <tr key={s.system} className="border-t border-line">
                      <td className="py-2">{s.system}</td>
                      <td className="num py-2 text-right">{s.count}</td>
                      <td className="num py-2 text-right">{formatMs(s.p50_ms)}</td>
                      <td className="num py-2 text-right">{formatMs(s.p95_ms)}</td>
                      <td
                        className={cx(
                          "num py-2 text-right font-semibold",
                          s.error_rate >= 0.1 ? "text-bad" : s.error_rate > 0.02 ? "text-warn" : "text-ok",
                        )}
                      >
                        {(s.error_rate * 100).toFixed(1)}%
                      </td>
                    </tr>
                  ))}
                  {data.systems.length === 0 && <EmptyRow cols={5} />}
                </tbody>
              </table>
            </Panel>

            <Panel title="Measured in the browser">
              <p className="-mt-1 mb-2 text-[12px] text-muted">
                Voice: end of your speech → first audio, and how fast speech stops when you interrupt. Text: send → first
                words on screen.
              </p>
              <StageTable stages={data.client} labels={CLIENT_LABELS} />
            </Panel>

            <Panel title="Recent turns" className="lg:col-span-2">
              <div className="scroll-thin relative overflow-x-auto">
                <table className="w-full min-w-[560px] text-[13px]">
                  <thead className="text-left text-[12px] text-muted">
                    <tr>
                      <th className="py-2 font-semibold">Turn</th>
                      <th className="py-2 font-semibold">Channel</th>
                      <th className="py-2 font-semibold">Mode</th>
                      <th className="py-2 text-right font-semibold">First token</th>
                      <th className="py-2 text-right font-semibold">Total</th>
                      <th className="py-2 text-right font-semibold">At</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.turns.slice(0, 25).map((t) => (
                      <tr key={t.turn_id} className="border-t border-line">
                        <td className="num py-2 text-ink-2">{t.turn_id}</td>
                        <td className="py-2">{humanize(t.channel)}</td>
                        <td className="py-2">
                          <span
                            className={cx(
                              "rounded-full px-2 py-0.5 text-[11px] font-semibold",
                              t.mode === "fallback" ? "bg-warn-soft text-warn" : "bg-brand-soft text-brand",
                            )}
                          >
                            {t.mode}
                          </span>
                        </td>
                        <td className="num py-2 text-right">{formatMs(t.first_token_ms)}</td>
                        <td className="num py-2 text-right">{formatMs(t.total_ms)}</td>
                        <td className="num py-2 text-right text-muted">{formatDateTime(t.at)}</td>
                      </tr>
                    ))}
                    {data.turns.length === 0 && <EmptyRow cols={6} />}
                  </tbody>
                </table>
              </div>
            </Panel>
          </div>
        )}
      </div>
    </AppShell>
  );
}

const CLIENT_LABELS: Record<string, string> = {
  "voice.eos_to_first_audio": "Voice · end of speech → first audio",
  "voice.bargein_stop": "Voice · barge-in → audio stopped",
  "voice.tts_synth": "Voice · server speech synthesis per sentence",
  "text.first_token_render": "Text · send → first words rendered",
};

function Panel({ title, className, children }: { title: string; className?: string; children: React.ReactNode }) {
  return (
    <section className={cx("min-w-0 rounded-xl border border-line bg-surface p-4 shadow-card sm:p-5", className)}>
      <h2 className="mb-3 font-display text-[17px] font-semibold">{title}</h2>
      <div className="scroll-thin relative overflow-x-auto">{children}</div>
    </section>
  );
}

function EmptyRow({ cols }: { cols: number }) {
  return (
    <tr>
      <td colSpan={cols} className="py-6 text-center text-[13px] text-muted">
        No data yet — have a conversation first.
      </td>
    </tr>
  );
}

function StageTable({ stages, labels }: { stages: StageStat[]; labels?: Record<string, string> }) {
  return (
    <table className="mt-2 w-full text-[13px]">
      <thead className="text-left text-[12px] text-muted">
        <tr>
          <th className="py-2 font-semibold">Stage</th>
          <th className="py-2 text-right font-semibold">Count</th>
          <th className="py-2 text-right font-semibold">p50</th>
          <th className="py-2 text-right font-semibold">p95</th>
        </tr>
      </thead>
      <tbody>
        {stages.map((s) => (
          <tr key={s.name} className="border-t border-line">
            <td className="py-2">{labels?.[s.name] ?? s.name}</td>
            <td className="num py-2 text-right">{s.count}</td>
            <td className="num py-2 text-right">{formatMs(s.p50_ms)}</td>
            <td className="num py-2 text-right">{formatMs(s.p95_ms)}</td>
          </tr>
        ))}
        {stages.length === 0 && <EmptyRow cols={4} />}
      </tbody>
    </table>
  );
}

/** Hand-rolled horizontal bars: solid = p50, light extension = p95, on a shared scale. */
function StageBars({ stages }: { stages: StageStat[] }) {
  if (stages.length === 0) return null;
  const max = Math.max(...stages.map((s) => s.p95_ms || 0), 1);
  const ticks = niceTicks(max);
  const scale = ticks[ticks.length - 1];
  return (
    <figure className="mb-4">
      <div className="space-y-2">
        {stages.map((s) => (
          <div key={s.name} className="grid grid-cols-[minmax(90px,170px)_1fr] items-center gap-3">
            <span className="truncate text-[12.5px] text-ink-2" title={s.name}>
              {s.name}
            </span>
            <div
              className="relative h-5 rounded bg-sunken"
              role="img"
              aria-label={`${s.name}: p50 ${formatMs(s.p50_ms)}, p95 ${formatMs(s.p95_ms)}`}
            >
              <div
                className="absolute inset-y-0 left-0 rounded bg-brand/25"
                style={{ width: `${(s.p95_ms / scale) * 100}%` }}
              />
              <div className="absolute inset-y-0 left-0 rounded bg-brand" style={{ width: `${(s.p50_ms / scale) * 100}%` }} />
              <span
                className="num absolute top-1/2 -translate-y-1/2 pl-1.5 text-[11px] text-ink-2"
                style={{ left: `min(${(s.p95_ms / scale) * 100}%, calc(100% - 64px))` }}
              >
                {formatMs(s.p95_ms)}
              </span>
            </div>
          </div>
        ))}
      </div>
      <div className="mt-1 grid grid-cols-[minmax(90px,170px)_1fr] gap-3">
        <span />
        <div className="relative h-4">
          {ticks.map((t) => (
            <span
              key={t}
              className="num absolute -translate-x-1/2 whitespace-nowrap text-[10.5px] text-muted first:translate-x-0 last:-translate-x-full"
              style={{ left: `${(t / scale) * 100}%` }}
            >
              {formatMs(t)}
            </span>
          ))}
        </div>
      </div>
      <figcaption className="mt-2 flex gap-4 text-[11.5px] text-muted">
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-2.5 w-4 rounded-sm bg-brand" /> p50
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-2.5 w-4 rounded-sm bg-brand/25" /> p95
        </span>
      </figcaption>
    </figure>
  );
}

function niceTicks(max: number): number[] {
  const raw = max / 4;
  const pow = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * pow).find((s) => s >= raw) ?? raw;
  const out: number[] = [];
  for (let v = 0; v <= max + step * 0.999; v += step) out.push(Math.round(v));
  return out;
}
