"use client";

import { useEffect, useMemo, useState } from "react";
import { AppShell, PageHeader } from "@/components/AppShell";
import { IconCheck, IconX } from "@/components/icons";
import { api } from "@/lib/api";
import { cx, formatDateTime, formatMs } from "@/lib/format";
import type { EvalRun } from "@/lib/types";

export default function EvalsPage() {
  const [run, setRun] = useState<EvalRun | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<"all" | "failed">("all");

  useEffect(() => {
    api.evals().then(setRun, (e: Error) => setError(e.message));
  }, []);

  const empty = run && (!run.cases || Object.keys(run).length === 0);
  const cases = useMemo(
    () => (run?.cases ?? []).filter((c) => filter === "all" || !c.passed),
    [run, filter],
  );
  const packs = useMemo(() => {
    const m = new Map<string, { total: number; passed: number }>();
    for (const c of run?.cases ?? []) {
      const p = m.get(c.pack) ?? { total: 0, passed: 0 };
      p.total++;
      if (c.passed) p.passed++;
      m.set(c.pack, p);
    }
    return [...m.entries()];
  }, [run]);

  return (
    <AppShell>
      <div className="mx-auto w-full max-w-6xl px-4 py-8 sm:px-6">
        <PageHeader kicker="Quality evidence" title="Evaluation results" />
        {error && <p className="mt-4 text-[13.5px] text-bad">Couldn&apos;t load evals: {error}</p>}
        {!run && !error && <p className="mt-6 text-[13.5px] text-muted">Loading…</p>}
        {empty && (
          <div className="mt-6 rounded-xl border border-dashed border-line-strong bg-surface px-6 py-14 text-center">
            <p className="font-display text-lg font-semibold">No evaluation run yet</p>
            <p className="mt-1 text-[13.5px] text-muted">Run the eval suite on the backend; the latest results will appear here.</p>
          </div>
        )}
        {run && !empty && (
          <>
            <p className="mt-2 text-[13.5px] text-ink-2">Run at {formatDateTime(run.run_at)}</p>
            <div className="mt-5 grid gap-3 sm:grid-cols-3">
              <Kpi label="Cases passed" value={`${run.passed ?? 0} / ${run.total ?? 0}`} pct={(run.passed ?? 0) / Math.max(1, run.total ?? 0)} />
              <Kpi label="Pass rate" value={`${(((run.passed ?? 0) / Math.max(1, run.total ?? 0)) * 100).toFixed(1)}%`} pct={(run.passed ?? 0) / Math.max(1, run.total ?? 0)} />
              <Kpi label="Figure accuracy" value={`${((run.figure_accuracy ?? 0) * 100).toFixed(1)}%`} pct={run.figure_accuracy ?? 0} />
            </div>
            {packs.length > 0 && (
              <div className="mt-4 flex flex-wrap gap-2">
                {packs.map(([name, p]) => (
                  <span key={name} className="rounded-full border border-line bg-surface px-3 py-1 text-[12.5px]">
                    {name} <span className="num font-semibold">{p.passed}/{p.total}</span>
                  </span>
                ))}
              </div>
            )}
            <div className="mt-6 overflow-hidden rounded-xl border border-line bg-surface shadow-card">
              <div className="flex items-center justify-between border-b border-line px-4 py-2.5">
                <h2 className="font-display text-[16px] font-semibold">Cases</h2>
                <div className="flex rounded-md border border-line p-0.5 text-[12.5px]" role="group" aria-label="Filter">
                  {(["all", "failed"] as const).map((f) => (
                    <button
                      key={f}
                      onClick={() => setFilter(f)}
                      aria-pressed={filter === f}
                      className={cx("rounded px-2.5 py-1 font-semibold capitalize", filter === f ? "bg-brand-soft text-brand" : "text-ink-2")}
                    >
                      {f}
                    </button>
                  ))}
                </div>
              </div>
              <div className="scroll-thin relative overflow-x-auto">
                <table className="w-full min-w-[720px] text-[13px]">
                  <thead className="bg-surface-2 text-left text-[12px] text-muted">
                    <tr>
                      <th className="px-4 py-2 font-semibold">Result</th>
                      <th className="px-4 py-2 font-semibold">Case</th>
                      <th className="px-4 py-2 font-semibold">Question</th>
                      <th className="px-4 py-2 font-semibold">Reason</th>
                      <th className="px-4 py-2 text-right font-semibold">Latency</th>
                    </tr>
                  </thead>
                  <tbody>
                    {cases.map((c) => (
                      <tr key={c.id} className={cx("border-t border-line align-top", !c.passed && "bg-bad-soft/50")}>
                        <td className="px-4 py-2.5">
                          {c.passed ? (
                            <span className="inline-flex items-center gap-1 font-semibold text-ok">
                              <IconCheck size={14} /> Pass
                            </span>
                          ) : (
                            <span className="inline-flex items-center gap-1 font-semibold text-bad">
                              <IconX size={14} /> Fail
                            </span>
                          )}
                        </td>
                        <td className="px-4 py-2.5">
                          <p className="num font-medium">{c.id}</p>
                          <p className="text-[11.5px] text-muted">{c.pack}</p>
                        </td>
                        <td className="px-4 py-2.5">{c.question}</td>
                        <td className="px-4 py-2.5 text-ink-2">{c.reason}</td>
                        <td className="num px-4 py-2.5 text-right">{formatMs(c.latency_ms)}</td>
                      </tr>
                    ))}
                    {cases.length === 0 && (
                      <tr>
                        <td colSpan={5} className="px-4 py-8 text-center text-muted">
                          No cases match.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </>
        )}
      </div>
    </AppShell>
  );
}

function Kpi({ label, value, pct }: { label: string; value: string; pct: number }) {
  return (
    <div className="rounded-xl border border-line bg-surface p-4 shadow-card">
      <p className="text-[12px] font-medium text-muted">{label}</p>
      <p className="num mt-1 text-[28px] font-semibold leading-none">{value}</p>
      <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-sunken">
        <div
          className={cx("h-full rounded-full", pct >= 0.9 ? "bg-ok" : pct >= 0.7 ? "bg-warn" : "bg-bad")}
          style={{ width: `${Math.min(100, pct * 100)}%` }}
        />
      </div>
    </div>
  );
}
