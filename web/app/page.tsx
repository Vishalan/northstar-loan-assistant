"use client";

import { useEffect, useState } from "react";
import { AccountPanel } from "@/components/AccountPanel";
import { AppShell } from "@/components/AppShell";
import { Conversation } from "@/components/Conversation";
import { IconMenu, IconX } from "@/components/icons";
import { api, auth } from "@/lib/api";
import { useChat } from "@/lib/chat-store";
import { cx } from "@/lib/format";

function useSession() {
  const sessionId = useChat((s) => s.sessionId);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (sessionId || !auth.token()) return;
    let cancelled = false;
    api.createSession().then(
      (r) => {
        if (cancelled) return;
        useChat.getState().setSession(r.session_id, r.products, r.suggestions ?? []);
        setError(null);
      },
      (e: Error) => !cancelled && setError(e.message),
    );
    return () => {
      cancelled = true;
    };
  }, [sessionId, attempt]);
  return { error, retry: () => setAttempt((a) => a + 1) };
}

export default function Home() {
  const [drawer, setDrawer] = useState(false);
  const [name, setName] = useState<string | undefined>();
  const focus = useChat((s) => s.focusProductId);
  const session = useSession();

  useEffect(() => setName(auth.customer()?.name), []);
  useEffect(() => {
    if (!drawer) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setDrawer(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [drawer]);

  return (
    <AppShell
      fill
      leading={
        <button
          type="button"
          onClick={() => setDrawer(true)}
          className="relative grid size-9 place-items-center rounded-md text-ink-2 hover:bg-surface-2 lg:hidden"
          aria-label="Show accounts"
          aria-expanded={drawer}
          aria-controls="account-panel"
        >
          <IconMenu size={20} />
          {focus && <span className="absolute right-1.5 top-1.5 size-2 rounded-full bg-accent" aria-hidden />}
        </button>
      }
    >
      <div className="flex min-h-0 flex-1">
        {/* Account panel: fixed column on desktop, drawer on mobile */}
        {drawer && (
          <button
            className="fixed inset-0 z-40 bg-ink/30 lg:hidden"
            aria-label="Close accounts"
            onClick={() => setDrawer(false)}
          />
        )}
        <aside
          id="account-panel"
          aria-label="Your accounts"
          className={cx(
            "scroll-thin z-40 w-[320px] shrink-0 overflow-y-auto border-r border-line bg-surface-2",
            "fixed inset-y-0 left-0 max-w-[88vw] shadow-pop transition-transform duration-200 lg:static lg:max-w-none lg:translate-x-0 lg:shadow-none",
            drawer ? "translate-x-0" : "-translate-x-full",
          )}
        >
          <div className="flex justify-end p-2 lg:hidden">
            <button
              onClick={() => setDrawer(false)}
              className="grid size-9 place-items-center rounded-md hover:bg-surface"
              aria-label="Close accounts"
            >
              <IconX size={18} />
            </button>
          </div>
          <AccountPanel />
        </aside>

        <main className="flex min-w-0 flex-1 flex-col" aria-label="Assistant">
          {session.error && (
            <div className="border-b border-bad/30 bg-bad-soft px-4 py-2 text-center text-[13px] text-bad" role="alert">
              Couldn&apos;t start a conversation: {session.error}{" "}
              <button className="font-semibold underline" onClick={session.retry}>
                Retry
              </button>
            </div>
          )}
          <Conversation customerName={name} />
        </main>
      </div>
    </AppShell>
  );
}
