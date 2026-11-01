"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { api, auth } from "@/lib/api";
import { useChat } from "@/lib/chat-store";
import { cx } from "@/lib/format";
import type { Persona } from "@/lib/types";
import { BrandMark, IconChevron, IconShield } from "@/components/icons";
import { OtpInput } from "@/components/OtpInput";

function maskPhone(p: string) {
  const d = p.replace(/\D/g, "");
  return d.length >= 4 ? `•••••• ${d.slice(-4)}` : p;
}

export default function LoginPage() {
  const router = useRouter();
  const [personas, setPersonas] = useState<Persona[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [picked, setPicked] = useState<Persona | null>(null);
  const [challenge, setChallenge] = useState<{ id: string; demo?: string } | null>(null);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expired, setExpired] = useState(false);
  const otpRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    setExpired(new URLSearchParams(window.location.search).has("expired"));
    api.personas().then(setPersonas, (e: Error) => setLoadError(e.message));
  }, []);

  async function pick(p: Persona) {
    setPicked(p);
    setError(null);
    setCode("");
    setChallenge(null);
    setBusy(true);
    try {
      const r = await api.otpStart(p.phone);
      setChallenge({ id: r.challenge_id, demo: r.demo_code });
      setTimeout(() => otpRef.current?.focus(), 50);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function verify(value = code) {
    if (!challenge || value.length !== 6) return;
    setBusy(true);
    setError(null);
    try {
      const r = await api.otpVerify(challenge.id, value);
      auth.save(r.access_token, r.customer);
      useChat.getState().reset();
      router.replace("/");
    } catch (e) {
      setError((e as Error).message || "That code didn't work.");
      setBusy(false);
    }
  }

  return (
    <div className="paper grid min-h-dvh lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
      {/* Brand side */}
      <aside className="relative hidden overflow-hidden bg-brand text-brand-ink lg:flex lg:flex-col lg:justify-between lg:p-12">
        <div className="flex items-center gap-3">
          <BrandMark size={36} />
          <span className="font-display text-2xl font-semibold">Northstar Finance</span>
        </div>
        <div className="relative z-10 max-w-md">
          <p className="font-display text-[40px] font-medium leading-[1.08] tracking-tight">
            Answers about your money, with the receipts attached.
          </p>
          <p className="mt-5 text-[15px] leading-relaxed opacity-80">
            Ask about an EMI change, a failed payment, or what prepaying would save. Every answer shows the records,
            policy clauses and calculations behind it — and nothing happens to your account without your confirmation.
          </p>
        </div>
        <p className="relative z-10 text-[12px] opacity-60">Demo with synthetic data. Northstar Finance is fictional.</p>
        <svg
          className="pointer-events-none absolute -bottom-24 -right-24 opacity-[0.12]"
          width="520"
          height="520"
          viewBox="0 0 32 32"
          aria-hidden
        >
          <path
            d="M16 2c.9 7.4 4 10.5 11.5 11.5C20 14.4 16.9 17.6 16 25c-.9-7.4-4-10.6-11.5-11.5C12 12.5 15.1 9.4 16 2z"
            fill="currentColor"
          />
        </svg>
      </aside>

      {/* Sign-in side */}
      <main className="flex items-start justify-center px-4 py-10 sm:items-center sm:px-8">
        <div className="w-full max-w-xl">
          <div className="mb-8 flex items-center gap-2.5 lg:hidden">
            <BrandMark />
            <span className="font-display text-xl font-semibold">Northstar Finance</span>
          </div>

          <h1 className="font-display text-[30px] font-semibold leading-tight tracking-tight">Sign in to your assistant</h1>
          <p className="mt-2 text-[14.5px] text-ink-2">
            Choose a demo customer. We&apos;ll send a one-time code to their registered mobile number.
          </p>

          {expired && (
            <p className="mt-4 rounded-lg border border-warn/40 bg-warn-soft px-3 py-2 text-[13px] text-warn">
              Your session expired. Please sign in again.
            </p>
          )}

          <ul className="mt-6 grid gap-2.5" aria-label="Demo customers">
            {personas === null && !loadError &&
              [0, 1, 2].map((i) => <li key={i} className="h-[74px] animate-pulse rounded-xl border border-line bg-surface" />)}
            {loadError && (
              <li className="rounded-xl border border-bad/40 bg-bad-soft px-4 py-3 text-[13.5px] text-bad">
                Couldn&apos;t load demo customers: {loadError}
              </li>
            )}
            {personas?.map((p) => {
              const active = picked?.customer_id === p.customer_id;
              return (
                <li key={p.customer_id}>
                  <button
                    onClick={() => pick(p)}
                    disabled={busy && !active}
                    aria-pressed={active}
                    className={cx(
                      "group flex w-full items-center gap-4 rounded-xl border bg-surface px-4 py-3.5 text-left shadow-card transition-all",
                      active ? "border-brand ring-2 ring-brand/20" : "border-line hover:-translate-y-px hover:border-line-strong",
                    )}
                  >
                    <span
                      className={cx(
                        "grid size-11 shrink-0 place-items-center rounded-full font-display text-[16px] font-semibold",
                        active ? "bg-brand text-brand-ink" : "bg-brand-soft text-brand",
                      )}
                      aria-hidden
                    >
                      {p.name
                        .split(/\s+/)
                        .map((s) => s[0])
                        .slice(0, 2)
                        .join("")}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="flex items-baseline gap-2">
                        <span className="text-[15.5px] font-semibold">{p.name}</span>
                        <span className="num text-[12px] text-muted">{maskPhone(p.phone)}</span>
                      </span>
                      <span className="mt-0.5 block text-[13.5px] leading-snug text-ink-2">{p.summary}</span>
                    </span>
                    <IconChevron className="shrink-0 text-muted transition-transform group-hover:translate-x-0.5" />
                  </button>
                </li>
              );
            })}
          </ul>

          {picked && (
            <section className="rise mt-6 rounded-xl border border-line bg-surface p-5 shadow-card" aria-label="Verify OTP">
              <div className="flex items-center gap-2 text-[14px] font-semibold">
                <IconShield className="text-brand" size={18} /> Verify it&apos;s {picked.name.split(" ")[0]}
              </div>
              {challenge?.demo && (
                <button
                  type="button"
                  onClick={() => {
                    setCode(challenge.demo!);
                    void verify(challenge.demo!);
                  }}
                  className="mt-3 flex w-full items-center justify-between gap-3 rounded-lg border border-dashed border-accent/60 bg-accent-soft px-3.5 py-2.5 text-left text-[13px] text-ink"
                >
                  <span>
                    Demo SMS: your code is{" "}
                    <span className="num text-[16px] font-semibold tracking-[0.2em]">{challenge.demo}</span>
                  </span>
                  <span className="shrink-0 text-[12px] font-semibold text-accent">Use code</span>
                </button>
              )}
              <form
                className="mt-4"
                onSubmit={(e) => {
                  e.preventDefault();
                  void verify();
                }}
              >
                <label htmlFor="otp" className="text-[12.5px] font-medium text-ink-2">
                  6-digit code sent to {maskPhone(picked.phone)}
                </label>
                <div className="mt-1.5 flex flex-wrap items-center gap-3">
                  <OtpInput
                    id="otp"
                    ref={otpRef}
                    value={code}
                    onChange={(v) => {
                      setCode(v);
                      if (v.length === 6) void verify(v);
                    }}
                    disabled={!challenge || busy}
                  />
                  <button
                    type="submit"
                    disabled={code.length !== 6 || busy}
                    className="h-11 rounded-lg bg-brand px-5 text-[14px] font-semibold text-brand-ink transition-opacity disabled:opacity-40"
                  >
                    {busy ? "Verifying…" : "Verify"}
                  </button>
                </div>
              </form>
              {error && (
                <p role="alert" className="mt-3 text-[13px] text-bad">
                  {error}
                </p>
              )}
            </section>
          )}

          <p className="mt-10 text-[12px] text-muted lg:hidden">Demo with synthetic data. Northstar Finance is fictional.</p>
        </div>
      </main>
    </div>
  );
}
