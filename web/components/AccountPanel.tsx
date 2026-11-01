"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { useChat } from "@/lib/chat-store";
import { cx, daysUntil, formatDate, formatINR, humanize, tenureLabel } from "@/lib/format";
import type { CreditCard, Loan, Overview, Payment, ServiceRequest } from "@/lib/types";
import { IconCard, IconWarn } from "./icons";

export function AccountPanel() {
  const nonce = useChat((s) => s.overviewNonce);
  const focus = useChat((s) => s.focusProductId);
  const [data, setData] = useState<Overview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    setRefreshing(true);
    api
      .overview(ctrl.signal)
      .then((d) => {
        setData(d);
        setError(null);
      })
      .catch((e: Error) => {
        if (e.name !== "AbortError") setError(e.message);
      })
      .finally(() => setRefreshing(false));
    return () => ctrl.abort();
  }, [nonce]);

  useEffect(() => {
    if (!focus) return;
    const el = rootRef.current?.querySelector<HTMLElement>(`[data-product-id="${CSS.escape(focus)}"]`);
    el?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [focus, data]);

  return (
    <div ref={rootRef} className="flex flex-col gap-5 p-4">
      <div className="flex items-baseline justify-between">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-muted">Your accounts</p>
          {data && (
            <p className="mt-0.5 text-[13px] text-ink-2">
              {data.customer.name}
              {data.customer.segment && <span className="text-muted"> · {data.customer.segment}</span>}
            </p>
          )}
        </div>
        <span className={cx("text-[11px] text-muted transition-opacity", refreshing ? "opacity-100" : "opacity-0")}>
          Updating…
        </span>
      </div>

      {error && !data && (
        <p className="rounded-lg border border-bad/40 bg-bad-soft px-3 py-2 text-[13px] text-bad">
          Couldn&apos;t load your accounts. {error}
        </p>
      )}
      {!data && !error && <PanelSkeleton />}

      {data && data.degraded?.length > 0 && (
        <p className="flex gap-2 rounded-lg border border-warn/40 bg-warn-soft px-3 py-2 text-[12.5px] text-warn">
          <IconWarn size={15} className="mt-px shrink-0" />
          <span>
            {data.degraded.join(", ")} {data.degraded.length > 1 ? "are" : "is"} temporarily unavailable. Some details may
            be out of date.
          </span>
        </p>
      )}

      {data?.loans.map((l) => <LoanCard key={l.loan_id} loan={l} focused={focus === l.loan_id} />)}
      {data?.cards.map((c) => <CardTile key={c.card_id} card={c} focused={focus === c.card_id} />)}
      {data && data.payments.length > 0 && <PaymentsTimeline payments={data.payments} />}
      {data && <OpenRequests requests={data.requests} />}
    </div>
  );
}

function PanelSkeleton() {
  return (
    <div className="space-y-3" aria-hidden>
      {[160, 120, 200].map((h, i) => (
        <div key={i} className="animate-pulse rounded-xl border border-line bg-surface" style={{ height: h }} />
      ))}
    </div>
  );
}

function Stat({ label, value, hint, tone }: { label: string; value: string; hint?: string; tone?: "bad" | "warn" }) {
  return (
    <div className="min-w-0">
      <dt className="text-[11px] font-medium text-muted">{label}</dt>
      <dd className={cx("num mt-0.5 truncate text-[15px] font-semibold", tone === "bad" && "text-bad", tone === "warn" && "text-warn")}>
        {value}
      </dd>
      {hint && <dd className="text-[11px] text-muted">{hint}</dd>}
    </div>
  );
}

function Shell({
  id,
  focused,
  children,
}: {
  id: string;
  focused: boolean;
  children: React.ReactNode;
}) {
  return (
    <article
      data-product-id={id}
      aria-current={focused ? "true" : undefined}
      className={cx(
        "relative rounded-xl border bg-surface p-4 shadow-card transition-[border-color,box-shadow] duration-300",
        focused ? "focus-pulse border-accent ring-2 ring-accent/30" : "border-line",
      )}
    >
      {focused && (
        <span className="absolute -top-2 right-3 rounded-full bg-accent px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-white">
          In discussion
        </span>
      )}
      {children}
    </article>
  );
}

function LoanCard({ loan, focused }: { loan: Loan; focused: boolean }) {
  const repaid = loan.principal > 0 ? Math.min(1, Math.max(0, 1 - loan.outstanding_principal / loan.principal)) : 0;
  const days = daysUntil(loan.next_due_date);
  return (
    <Shell id={loan.loan_id} focused={focused}>
      <header className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="truncate text-[14px] font-semibold">{loan.product_name}</h3>
          <p className="num text-[11.5px] text-muted">{loan.loan_id}</p>
        </div>
        <StatusPill status={loan.status} />
      </header>
      <p className="mt-3 text-[11px] font-medium text-muted">Outstanding principal</p>
      <p className="num text-[26px] font-semibold leading-tight tracking-tight">{formatINR(loan.outstanding_principal)}</p>
      <div className="mt-2" aria-label={`${Math.round(repaid * 100)}% repaid`}>
        <div className="h-1.5 overflow-hidden rounded-full bg-sunken">
          <div className="h-full rounded-full bg-brand" style={{ width: `${repaid * 100}%` }} />
        </div>
        <p className="mt-1 text-[11px] text-muted">
          {Math.round(repaid * 100)}% repaid of <span className="num">{formatINR(loan.principal)}</span>
        </p>
      </div>
      <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-2.5 border-t border-line pt-3">
        <Stat label="Rate" value={`${loan.current_rate.toFixed(2)}%`} hint={humanize(loan.rate_type)} />
        <Stat label="EMI" value={formatINR(loan.emi)} />
        <Stat
          label="Next due"
          value={formatDate(loan.next_due_date, { year: undefined })}
          hint={days == null ? undefined : days < 0 ? `${-days} days overdue` : days === 0 ? "Today" : `in ${days} days`}
          tone={days != null && days < 0 ? "bad" : days != null && days <= 3 ? "warn" : undefined}
        />
        <Stat label="Tenure left" value={tenureLabel(loan.tenure_left_months)} />
      </dl>
    </Shell>
  );
}

function CardTile({ card, focused }: { card: CreditCard; focused: boolean }) {
  const used = card.limit > 0 ? Math.min(1, card.outstanding / card.limit) : 0;
  const days = daysUntil(card.due_date);
  return (
    <Shell id={card.card_id} focused={focused}>
      <header className="flex items-center justify-between">
        <h3 className="flex items-center gap-2 text-[14px] font-semibold">
          <IconCard size={17} className="text-brand" /> Credit card
        </h3>
        <span className="num text-[13px] tracking-[0.12em] text-ink-2">•••• {card.last4}</span>
      </header>
      <p className="mt-3 text-[11px] font-medium text-muted">Outstanding</p>
      <p className="num text-[22px] font-semibold leading-tight">{formatINR(card.outstanding)}</p>
      <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-sunken" aria-label={`${Math.round(used * 100)}% of limit used`}>
        <div
          className={cx("h-full rounded-full", used > 0.8 ? "bg-bad" : used > 0.5 ? "bg-warn" : "bg-brand")}
          style={{ width: `${used * 100}%` }}
        />
      </div>
      <p className="mt-1 text-[11px] text-muted">
        {Math.round(used * 100)}% of <span className="num">{formatINR(card.limit)}</span> limit
      </p>
      <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-2.5 border-t border-line pt-3">
        <Stat label="Statement total" value={formatINR(card.statement_total)} />
        <Stat label="Minimum due" value={formatINR(card.min_due)} />
        <Stat
          label="Due date"
          value={formatDate(card.due_date, { year: undefined })}
          hint={days == null ? undefined : days < 0 ? `${-days} days overdue` : `in ${days} days`}
          tone={days != null && days < 0 ? "bad" : undefined}
        />
      </dl>
    </Shell>
  );
}

function StatusPill({ status }: { status: string }) {
  const s = status.toLowerCase();
  const tone =
    /active|open|current|regular|succeeded|completed|closed/.test(s) && !/overdue|fail/.test(s)
      ? "ok"
      : /overdue|fail|reject|npa|default/.test(s)
        ? "bad"
        : "warn";
  return (
    <span
      className={cx(
        "shrink-0 rounded-full px-2 py-0.5 text-[10.5px] font-semibold uppercase tracking-wide",
        tone === "ok" && "bg-ok-soft text-ok",
        tone === "bad" && "bg-bad-soft text-bad",
        tone === "warn" && "bg-warn-soft text-warn",
      )}
    >
      {humanize(status)}
    </span>
  );
}

function PaymentsTimeline({ payments }: { payments: Payment[] }) {
  return (
    <section aria-labelledby="payments-h">
      <h3 id="payments-h" className="mb-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-muted">
        Payments · last 6 months
      </h3>
      <ol className="relative ml-1.5 border-l border-line">
        {payments.map((p) => {
          const bad = p.status === "failed";
          const rev = p.status === "reversed";
          return (
            <li key={p.txn_id} className="relative pb-3 pl-4 last:pb-0">
              <span
                className={cx(
                  "absolute -left-[5px] top-1.5 size-[9px] rounded-full ring-2 ring-bg",
                  bad ? "bg-bad" : rev ? "bg-warn" : "bg-ok",
                )}
                aria-hidden
              />
              <div className="flex items-baseline justify-between gap-2">
                <span className="text-[12.5px] text-ink-2">{formatDate(p.date)}</span>
                <span className={cx("num text-[13.5px] font-semibold", bad && "text-bad line-through decoration-1")}>
                  {formatINR(p.amount)}
                </span>
              </div>
              <div className="flex items-baseline justify-between gap-2 text-[11.5px]">
                <span className="text-muted">{p.loan_id}</span>
                <span className={cx("font-medium", bad ? "text-bad" : rev ? "text-warn" : "text-ok")}>
                  {bad ? "Failed" : rev ? "Reversed" : "Paid"}
                </span>
              </div>
              {(p.failure_reason || p.charge) && (
                <p className="mt-1 rounded-md bg-bad-soft px-2 py-1 text-[11.5px] text-bad">
                  {p.failure_reason}
                  {p.charge ? (
                    <>
                      {p.failure_reason ? " · " : ""}Charge <span className="num font-semibold">{formatINR(p.charge)}</span>
                    </>
                  ) : null}
                </p>
              )}
            </li>
          );
        })}
      </ol>
    </section>
  );
}

function OpenRequests({ requests }: { requests: ServiceRequest[] }) {
  const open = requests.filter((r) => !/closed|completed|resolved|cancel/i.test(r.status));
  return (
    <section aria-labelledby="req-h">
      <h3 id="req-h" className="mb-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-muted">
        Open requests
      </h3>
      {open.length === 0 ? (
        <p className="text-[12.5px] text-muted">No open service requests.</p>
      ) : (
        <ul className="space-y-2">
          {open.map((r) => (
            <li key={r.request_id} className="rise rounded-lg border border-line bg-surface px-3 py-2">
              <div className="flex items-center justify-between gap-2">
                <span className="truncate text-[13px] font-semibold">{humanize(r.type)}</span>
                <StatusPill status={r.status} />
              </div>
              <p className="mt-0.5 line-clamp-2 text-[12px] text-ink-2">{r.summary}</p>
              <p className="num mt-1 text-[11px] text-muted">
                {r.request_id} · due {formatDate(r.sla_due, { year: undefined })}
              </p>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
