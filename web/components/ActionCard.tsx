"use client";

import { useId, useState } from "react";
import { useChat } from "@/lib/chat-store";
import { cx, formatDate } from "@/lib/format";
import { turnEngine } from "@/lib/turn-engine";
import type { ActionProposal } from "@/lib/types";
import { IconCheck, IconShield, IconSpinner, IconWarn, IconX } from "./icons";
import { OtpInput } from "./OtpInput";

const TIER: Record<ActionProposal["tier"], { label: string; cls: string }> = {
  read: { label: "Information only", cls: "bg-sunken text-ink-2" },
  confirm: { label: "Needs your confirmation", cls: "bg-brand-soft text-brand" },
  confirm_otp: { label: "Needs OTP", cls: "bg-accent-soft text-accent" },
};

export function ActionCard({ proposal }: { proposal: ActionProposal }) {
  const state = useChat((s) => s.actions[proposal.action_id]) ?? { phase: "pending" as const };
  const [otp, setOtp] = useState("");
  const titleId = useId();
  const tier = TIER[proposal.tier] ?? TIER.confirm;
  const needsOtp = proposal.tier === "confirm_otp";
  const actionable = state.phase === "pending" || state.phase === "otp_invalid" || state.phase === "error";
  const submitting = state.phase === "submitting";
  const done = !actionable && !submitting;
  const expires = proposal.expires_at ? new Date(proposal.expires_at) : null;

  return (
    <section
      aria-labelledby={titleId}
      className={cx(
        "rise overflow-hidden rounded-xl border-2 bg-surface shadow-card",
        state.phase === "succeeded" ? "border-ok/50" : done ? "border-line" : "border-brand/40",
      )}
    >
      <header className="flex flex-wrap items-center justify-between gap-2 px-4 pt-3.5">
        <h3 id={titleId} className="flex items-center gap-2 font-display text-[16.5px] font-semibold">
          <IconShield size={17} className="text-brand" />
          {proposal.title}
        </h3>
        <span className={cx("rounded-full px-2 py-0.5 text-[10.5px] font-semibold uppercase tracking-wide", tier.cls)}>
          {tier.label}
        </span>
      </header>

      <dl className="mx-4 mt-3 divide-y divide-line rounded-lg border border-line">
        {proposal.summary.map((r, i) => (
          <div key={i} className="flex items-baseline justify-between gap-4 px-3 py-2">
            <dt className="text-[12.5px] text-muted">{r.label}</dt>
            <dd className="num text-right text-[14px] font-semibold">{r.value}</dd>
          </div>
        ))}
      </dl>

      <div className="px-4 pb-4 pt-3">
        {actionable && (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (needsOtp && otp.length !== 6) return;
              void turnEngine.confirmAction(proposal, { otp: needsOtp ? otp : undefined, via: "button" });
            }}
          >
            {needsOtp && (
              <div className="mb-3">
                <label className="text-[12.5px] font-medium text-ink-2" htmlFor={`${titleId}-otp`}>
                  Enter the 6-digit code sent to your registered mobile
                </label>
                <div className="mt-1.5 flex flex-wrap items-center gap-3">
                  <OtpInput id={`${titleId}-otp`} size="sm" value={otp} onChange={setOtp} />
                  {proposal.demo_otp && (
                    <button
                      type="button"
                      onClick={() => setOtp(proposal.demo_otp!)}
                      className="rounded-md border border-dashed border-accent/60 bg-accent-soft px-2 py-1 text-[11.5px] text-ink"
                    >
                      Demo code <span className="num font-semibold tracking-[0.15em]">{proposal.demo_otp}</span>
                    </button>
                  )}
                </div>
              </div>
            )}
            {(state.phase === "otp_invalid" || state.phase === "error") && (
              <p role="alert" className="mb-2 flex items-center gap-1.5 text-[12.5px] text-bad">
                <IconWarn size={14} /> {state.message ?? "That didn't work. Please try again."}
              </p>
            )}
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="submit"
                disabled={needsOtp && otp.length !== 6}
                className="rounded-lg bg-brand px-4 py-2 text-[13.5px] font-semibold text-brand-ink hover:bg-brand-2 disabled:opacity-40"
              >
                Confirm
              </button>
              <button
                type="button"
                onClick={() => void turnEngine.cancelAction(proposal)}
                className="rounded-lg border border-line-strong px-4 py-2 text-[13.5px] font-semibold text-ink-2 hover:bg-surface-2"
              >
                Cancel
              </button>
              {expires && !Number.isNaN(expires.getTime()) && (
                <span className="ml-auto text-[11.5px] text-muted">
                  Valid until {expires.toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit" })}
                </span>
              )}
            </div>
            <p className="mt-2 text-[11.5px] text-muted">Or say “yes, go ahead” in voice mode.</p>
          </form>
        )}

        {submitting && (
          <p className="flex items-center gap-2 text-[13px] text-ink-2" role="status">
            <IconSpinner size={15} /> Submitting…
          </p>
        )}

        {done && (
          <div
            role="status"
            className={cx(
              "rounded-lg px-3 py-2.5 text-[13px]",
              state.phase === "succeeded" ? "bg-ok-soft" : state.phase === "cancelled" ? "bg-sunken" : "bg-bad-soft",
            )}
          >
            <p
              className={cx(
                "flex items-center gap-1.5 font-semibold",
                state.phase === "succeeded" ? "text-ok" : state.phase === "cancelled" ? "text-ink-2" : "text-bad",
              )}
            >
              {state.phase === "succeeded" ? <IconCheck size={15} /> : <IconX size={15} />}
              {state.phase === "succeeded"
                ? "Request submitted"
                : state.phase === "cancelled"
                  ? "Cancelled"
                  : state.phase === "expired"
                    ? "This request expired"
                    : "Request failed"}
            </p>
            {state.message && <p className="mt-1 text-ink-2">{state.message}</p>}
            {state.result?.request_id && (
              <p className="mt-1.5 flex flex-wrap gap-x-4 gap-y-0.5 text-[12px] text-ink-2">
                <span>
                  Reference <span className="num font-semibold text-ink">{state.result.request_id}</span>
                </span>
                {state.result.sla_due && (
                  <span>
                    Resolution by <span className="font-semibold text-ink">{formatDate(state.result.sla_due)}</span>
                  </span>
                )}
              </p>
            )}
          </div>
        )}
      </div>
    </section>
  );
}
