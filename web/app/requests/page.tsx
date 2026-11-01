"use client";

import { useEffect, useState } from "react";
import { AppShell, PageHeader } from "@/components/AppShell";
import { IconDoc } from "@/components/icons";
import { api } from "@/lib/api";
import { cx, formatDate, formatDateTime, humanize } from "@/lib/format";
import type { ServiceRequest } from "@/lib/types";

function tone(status: string) {
  const s = status.toLowerCase();
  if (/fail|reject|cancel/.test(s)) return "bg-bad-soft text-bad";
  if (/done|complete|closed|resolved|succeed|ready|fulfilled/.test(s)) return "bg-ok-soft text-ok";
  return "bg-warn-soft text-warn";
}

export default function RequestsPage() {
  const [rows, setRows] = useState<ServiceRequest[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.requests().then(setRows, (e: Error) => setError(e.message));
  }, []);

  return (
    <AppShell>
      <div className="mx-auto w-full max-w-5xl px-4 py-8 sm:px-6">
        <PageHeader kicker="Service" title="Your requests" />
        <p className="mt-2 max-w-2xl text-[14px] text-ink-2">
          Everything raised through the assistant, with its reference number and the date we&apos;ve committed to resolve
          it by.
        </p>

        <div className="mt-6 overflow-hidden rounded-xl border border-line bg-surface shadow-card">
          {error && <p className="px-4 py-6 text-[13.5px] text-bad">Couldn&apos;t load requests: {error}</p>}
          {!rows && !error && <p className="px-4 py-6 text-[13.5px] text-muted">Loading…</p>}
          {rows && rows.length === 0 && (
            <div className="px-6 py-12 text-center">
              <p className="font-display text-lg font-semibold">No requests yet</p>
              <p className="mt-1 text-[13.5px] text-muted">
                Ask the assistant for a statement, a prepayment or to dispute a charge.
              </p>
            </div>
          )}
          {rows && rows.length > 0 && (
            <div className="scroll-thin relative overflow-x-auto">
              <table className="w-full min-w-[720px] text-[13.5px]">
                <thead className="bg-surface-2 text-left text-[12px] text-muted">
                  <tr>
                    <th scope="col" className="px-4 py-2.5 font-semibold">Reference</th>
                    <th scope="col" className="px-4 py-2.5 font-semibold">Request</th>
                    <th scope="col" className="px-4 py-2.5 font-semibold">Status</th>
                    <th scope="col" className="px-4 py-2.5 font-semibold">Raised</th>
                    <th scope="col" className="px-4 py-2.5 font-semibold">Resolve by</th>
                    <th scope="col" className="px-4 py-2.5 font-semibold">
                      <span className="sr-only">Download</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.request_id} className="border-t border-line align-top">
                      <td className="num whitespace-nowrap px-4 py-3 font-semibold">{r.request_id}</td>
                      <td className="px-4 py-3">
                        <p className="font-semibold">{humanize(r.type)}</p>
                        <p className="text-[12.5px] text-ink-2">{r.summary}</p>
                      </td>
                      <td className="px-4 py-3">
                        <span className={cx("rounded-full px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide", tone(r.status))}>
                          {humanize(r.status)}
                        </span>
                      </td>
                      <td className="num whitespace-nowrap px-4 py-3 text-ink-2">{formatDateTime(r.created_at)}</td>
                      <td className="num whitespace-nowrap px-4 py-3 text-ink-2">{formatDate(r.sla_due)}</td>
                      <td className="px-4 py-3 text-right">
                        {/statement/i.test(r.type) && (
                          <a
                            href={api.statementUrl(r.request_id)}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex items-center gap-1.5 rounded-md border border-line-strong px-2.5 py-1 text-[12.5px] font-semibold text-brand hover:bg-brand-soft"
                          >
                            <IconDoc size={14} /> Download
                          </a>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </AppShell>
  );
}
