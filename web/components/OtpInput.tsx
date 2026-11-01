"use client";

import { forwardRef } from "react";
import { cx } from "@/lib/format";

/** Single input styled as six digit slots (one real input keeps paste, autofill and a11y simple). */
export const OtpInput = forwardRef<
  HTMLInputElement,
  { id?: string; value: string; onChange: (v: string) => void; disabled?: boolean; size?: "md" | "sm"; label?: string }
>(function OtpInput({ id, value, onChange, disabled, size = "md", label }, ref) {
  const slot = size === "md" ? "w-9 h-11 text-[20px]" : "w-7 h-9 text-[16px]";
  return (
    <div className="group relative inline-flex">
      <input
        ref={ref}
        id={id}
        aria-label={label}
        inputMode="numeric"
        autoComplete="one-time-code"
        pattern="[0-9]*"
        maxLength={6}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value.replace(/\D/g, "").slice(0, 6))}
        className="absolute inset-0 z-10 w-full cursor-text opacity-0 disabled:cursor-not-allowed"
      />
      <div className="flex gap-1.5" aria-hidden>
        {Array.from({ length: 6 }, (_, i) => {
          const ch = value[i];
          const current = i === Math.min(value.length, 5);
          return (
            <span
              key={i}
              className={cx(
                "num grid place-items-center rounded-md border bg-surface-2 font-semibold",
                slot,
                ch ? "border-line-strong" : "border-line",
                current && "group-focus-within:border-brand group-focus-within:ring-2 group-focus-within:ring-brand/25",
                disabled && "opacity-60",
              )}
            >
              {ch ?? ""}
            </span>
          );
        })}
      </div>
    </div>
  );
});
