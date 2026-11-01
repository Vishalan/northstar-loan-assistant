"use client";

import { useId, useState } from "react";
import { cx, formatDateTime } from "@/lib/format";
import type { Card, CardSource, Metric, RowStatus } from "@/lib/types";
import { IconCalc, IconChevron, IconDatabase, IconScale } from "./icons";

/** One component renders every card type the orchestrator emits. */
export function CardView({ card, onAction, disabled }: { card: Card; onAction: (prompt: string) => void; disabled?: boolean }) {
  const titleId = useId();
  return (
    <section
      aria-labelledby={titleId}
      data-card-type={card.type}
      className="rise overflow-hidden rounded-xl border border-line bg-surface shadow-card"
    >
      <header className="border-b border-line bg-surface-2 px-4 py-3">
        <h3 id={titleId} className="font-display text-[16.5px] font-semibold leading-snug">
          {card.title}
        </h3>
        {card.subtitle && <p className="mt-0.5 text-[12.5px] text-muted">{card.subtitle}</p>}
      </header>

      <div className="space-y-4 px-4 py-4">
        {card.metrics && card.metrics.length > 0 && <MetricGrid metrics={card.metrics} />}

        {card.columns && card.columns.length > 0 && (
          <div
            className="grid gap-3"
            style={{ gridTemplateColumns: `repeat(auto-fit, minmax(min(100%, 180px), 1fr))` }}
          >
            {card.columns.map((col, i) => (
              <div key={i} className="rounded-lg border border-line bg-surface-2 p-3">
                <p className="text-[12.5px] font-semibold text-brand">{col.label}</p>
                <dl className="mt-2 space-y-2">
                  {col.metrics.map((m, j) => (
                    <div key={j} className="flex items-baseline justify-between gap-3">
                      <dt className="text-[12px] text-ink-2">{m.label}</dt>
                      <dd className={cx("num text-right text-[14.5px]", m.emphasis ? "font-bold text-ink" : "font-semibold")}>
                        {m.value}
                        {m.delta && <Delta delta={m.delta} />}
                      </dd>
                    </div>
                  ))}
                </dl>
              </div>
            ))}
          </div>
        )}

        {card.table && card.table.rows.length > 0 && (
          <div className="scroll-thin -mx-1 overflow-x-auto px-1">
            <table className="w-full border-collapse text-[12.5px]">
              <thead>
                <tr>
                  {card.table.columns.map((c, i) => (
                    <th key={i} scope="col" className="border-b border-line-strong px-2 py-1.5 text-left font-semibold text-muted first:pl-0">
                      {c}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {card.table.rows.map((row, ri) => {
                  const st: RowStatus = card.table?.row_status?.[ri] ?? null;
                  return (
                    <tr
                      key={ri}
                      className={cx(
                        "border-b border-line last:border-0",
                        st === "bad" && "bg-bad-soft text-bad",
                        st === "warn" && "bg-warn-soft",
                        st === "ok" && "",
                      )}
                    >
                      {row.map((cell, ci) => (
                        <td
                          key={ci}
                          className={cx(
                            "px-2 py-1.5 align-top first:pl-2",
                            /^[-+]?₹|^[-+]?\d[\d,.]*%?$/.test(cell.trim()) && "num whitespace-nowrap text-right",
                            ci === 0 && st && "relative",
                          )}
                        >
                          {ci === 0 && st && (
                            <span
                              className={cx(
                                "absolute left-0 top-0 h-full w-[3px]",
                                st === "bad" && "bg-bad",
                                st === "warn" && "bg-warn",
                                st === "ok" && "bg-ok",
                              )}
                              aria-hidden
                            />
                          )}
                          {cell}
                        </td>
                      ))}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {card.notes && card.notes.length > 0 && (
          <ul className="space-y-1.5">
            {card.notes.map((n, i) => (
              <li key={i} className="flex gap-2 text-[12.5px] leading-snug text-ink-2">
                <span className="mt-[7px] size-1 shrink-0 rounded-full bg-accent" aria-hidden />
                {n}
              </li>
            ))}
          </ul>
        )}

        {card.actions && card.actions.length > 0 && (
          <div className="flex flex-wrap gap-2 pt-1">
            {card.actions.map((a, i) => (
              <button
                key={i}
                type="button"
                disabled={disabled}
                onClick={() => onAction(a.prompt)}
                title={a.prompt}
                className={cx(
                  "rounded-lg px-3.5 py-2 text-[13px] font-semibold transition-colors disabled:opacity-50",
                  i === 0
                    ? "bg-brand text-brand-ink hover:bg-brand-2"
                    : "border border-line-strong bg-surface text-ink hover:bg-surface-2",
                )}
              >
                {a.label}
              </button>
            ))}
          </div>
        )}
      </div>

      {card.sources && card.sources.length > 0 && <Sources sources={card.sources} />}
    </section>
  );
}

function Delta({ delta }: { delta: string }) {
  const up = delta.trim().startsWith("+");
  const down = /^[-−]/.test(delta.trim());
  return (
    <span
      className={cx(
        "ml-1.5 rounded px-1 py-px align-middle text-[11px] font-semibold",
        up && "bg-warn-soft text-warn",
        down && "bg-ok-soft text-ok",
        !up && !down && "bg-sunken text-ink-2",
      )}
    >
      {delta}
    </span>
  );
}

function MetricGrid({ metrics }: { metrics: Metric[] }) {
  return (
    <dl className="grid gap-x-4 gap-y-3" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 130px), 1fr))" }}>
      {metrics.map((m, i) => (
        <div
          key={i}
          className={cx("rounded-lg px-3 py-2", m.emphasis ? "bg-brand-soft ring-1 ring-brand/25" : "bg-surface-2")}
        >
          <dt className="text-[11.5px] font-medium text-muted">{m.label}</dt>
          <dd className="mt-0.5 flex flex-wrap items-baseline">
            <span className={cx("num text-[19px] leading-tight", m.emphasis ? "font-bold text-brand" : "font-semibold")}>
              {m.value}
            </span>
            {m.delta && <Delta delta={m.delta} />}
          </dd>
        </div>
      ))}
    </dl>
  );
}

function Sources({ sources }: { sources: CardSource[] }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const counts = {
    record: sources.filter((s) => s.kind === "record").length,
    policy: sources.filter((s) => s.kind === "policy").length,
    calc: sources.filter((s) => s.kind === "calc").length,
  };
  const summary = [
    counts.record && `${counts.record} record${counts.record > 1 ? "s" : ""}`,
    counts.policy && `${counts.policy} polic${counts.policy > 1 ? "ies" : "y"}`,
    counts.calc && `${counts.calc} calculation${counts.calc > 1 ? "s" : ""}`,
  ]
    .filter(Boolean)
    .join(" · ");
  return (
    <footer className="border-t border-line bg-surface-2/60">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2 px-4 py-2.5 text-left text-[12.5px] font-semibold text-ink-2 hover:text-ink"
      >
        <IconChevron size={14} className={cx("transition-transform", open && "rotate-90")} />
        Sources
        <span className="font-normal text-muted">{summary}</span>
      </button>
      <div id={id} hidden={!open} className="space-y-3 px-4 pb-4">
        {sources.map((s, i) => (
          <SourceItem key={i} s={s} />
        ))}
      </div>
    </footer>
  );
}

function SourceItem({ s }: { s: CardSource }) {
  if (s.kind === "record")
    return (
      <div className="flex gap-2.5 text-[12.5px]">
        <IconDatabase size={15} className="mt-0.5 shrink-0 text-brand" />
        <div className="min-w-0">
          <p>
            <span className="font-semibold">{s.system}</span>{" "}
            <code className="break-all rounded bg-sunken px-1 py-px text-[11.5px] text-ink-2">{s.ref}</code>
          </p>
          {s.as_of && <p className="text-[11.5px] text-muted">As of {formatDateTime(s.as_of)}</p>}
        </div>
      </div>
    );
  if (s.kind === "policy")
    return (
      <div className="flex gap-2.5 text-[12.5px]">
        <IconScale size={15} className="mt-0.5 shrink-0 text-accent" />
        <div className="min-w-0">
          <p className="font-semibold">Policy {s.ref}</p>
          {s.text && (
            <blockquote className="mt-1 border-l-2 border-accent/60 pl-2.5 text-[12.5px] italic leading-snug text-ink-2">
              “{s.text}”
            </blockquote>
          )}
        </div>
      </div>
    );
  if (s.kind === "calc")
    return (
      <div className="flex gap-2.5 text-[12.5px]">
        <IconCalc size={15} className="mt-0.5 shrink-0 text-ok" />
        <div className="min-w-0 flex-1">
          <p className="font-semibold">Calculation · {s.ref}</p>
          {s.steps && (
            <ol className="mt-1 space-y-0.5">
              {s.steps.map((st, i) => (
                <li key={i} className="flex gap-2 leading-snug text-ink-2">
                  <span className="num w-4 shrink-0 text-right text-muted">{i + 1}</span>
                  <span className="num">{st}</span>
                </li>
              ))}
            </ol>
          )}
        </div>
      </div>
    );
  return null;
}
