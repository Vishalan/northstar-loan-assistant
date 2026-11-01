"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { auth, type StoredCustomer } from "@/lib/api";
import { useChat } from "@/lib/chat-store";
import { cx } from "@/lib/format";
import { DemoDrawer } from "./DemoDrawer";
import { BrandMark, IconBolt, IconLogout } from "./icons";

const NAV = [
  { href: "/", label: "Assistant" },
  { href: "/requests", label: "Requests" },
  { href: "/latency", label: "Latency" },
  { href: "/evals", label: "Evals" },
];

function useDemoMode() {
  const [demo, setDemo] = useState(false);
  useEffect(() => {
    try {
      const q = new URLSearchParams(window.location.search).get("demo");
      if (q === "1") sessionStorage.setItem("ns.demo", "1");
      if (q === "0") sessionStorage.removeItem("ns.demo");
      setDemo(sessionStorage.getItem("ns.demo") === "1");
    } catch {
      /* storage blocked */
    }
  }, []);
  return demo;
}

/** Authenticated page frame: guard, top bar, footer. */
export function AppShell({
  children,
  leading,
  fill = false,
}: {
  children: ReactNode;
  leading?: ReactNode;
  /** Main screen: fixed-height app layout instead of a scrolling document. */
  fill?: boolean;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const [customer, setCustomer] = useState<StoredCustomer | null>(null);
  const [ready, setReady] = useState(false);
  const [demoOpen, setDemoOpen] = useState(false);
  const demo = useDemoMode();

  useEffect(() => {
    if (!auth.token()) {
      router.replace("/login");
      return;
    }
    setCustomer(auth.customer());
    setReady(true);
  }, [router]);

  function signOut() {
    auth.clear();
    useChat.getState().reset();
    router.replace("/login");
  }

  return (
    <div className={cx("paper flex flex-col", fill ? "h-dvh overflow-hidden" : "min-h-dvh")}>
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:z-50 focus:rounded-md focus:bg-surface focus:px-3 focus:py-2"
      >
        Skip to content
      </a>
      <header className="sticky top-0 z-30 border-b border-line bg-surface/90 backdrop-blur supports-[backdrop-filter]:bg-surface/75">
        <div className="flex h-14 items-center gap-2 px-3 sm:gap-3 sm:px-5">
          {leading}
          <Link href="/" className="flex shrink-0 items-center gap-2.5 rounded-md" aria-label="Northstar Finance home">
            <BrandMark />
            <span className="hidden leading-none sm:block">
              <span className="block font-display text-[17px] font-semibold tracking-tight">Northstar</span>
              <span className="block text-[10.5px] font-medium uppercase tracking-[0.16em] text-muted">Finance</span>
            </span>
          </Link>
          <nav aria-label="Primary" className="ml-1 flex min-w-0 items-center gap-0.5 overflow-x-auto sm:ml-4">
            {NAV.map((n) => {
              const active = n.href === "/" ? pathname === "/" : pathname.startsWith(n.href);
              return (
                <Link
                  key={n.href}
                  href={n.href}
                  aria-current={active ? "page" : undefined}
                  className={cx(
                    "whitespace-nowrap rounded-md px-2 py-1.5 text-[13px] font-medium transition-colors sm:px-2.5",
                    active ? "bg-brand-soft text-brand" : "text-ink-2 hover:bg-surface-2 hover:text-ink",
                    n.href === "/evals" && "hidden md:block",
                  )}
                >
                  {n.label}
                </Link>
              );
            })}
          </nav>
          <div className="ml-auto flex shrink-0 items-center gap-1.5 sm:gap-2">
            {demo && (
              <button
                type="button"
                onClick={() => setDemoOpen(true)}
                className="inline-flex items-center gap-1.5 rounded-md border border-accent/40 bg-accent-soft px-2 py-1.5 text-[12.5px] font-semibold text-accent hover:border-accent"
              >
                <IconBolt size={14} />
                <span className="hidden sm:inline">Demo</span>
              </button>
            )}
            {customer && (
              <span className="hidden items-center gap-2 rounded-full border border-line bg-surface-2 py-1 pl-1 pr-3 text-[13px] md:inline-flex">
                <span className="grid size-6 place-items-center rounded-full bg-brand text-[11px] font-semibold text-brand-ink">
                  {customer.name
                    .split(/\s+/)
                    .map((p) => p[0])
                    .slice(0, 2)
                    .join("")}
                </span>
                <span className="max-w-[12rem] truncate font-medium">{customer.name}</span>
              </span>
            )}
            <button
              type="button"
              onClick={signOut}
              className="grid size-9 place-items-center rounded-md text-ink-2 hover:bg-surface-2 hover:text-ink"
              aria-label="Sign out"
              title="Sign out"
            >
              <IconLogout size={18} />
            </button>
          </div>
        </div>
      </header>

      <div id="main" className={cx("flex min-h-0 flex-1 flex-col")}>
        {ready ? children : <div className="flex-1" aria-busy="true" />}
      </div>

      <footer className="border-t border-line bg-surface/60 px-4 py-2 text-center text-[11.5px] text-muted">
        Demo with synthetic data. Northstar Finance is fictional.
      </footer>

      {demo && <DemoDrawer open={demoOpen} onClose={() => setDemoOpen(false)} />}
    </div>
  );
}

/** Simple page heading for the secondary pages. */
export function PageHeader({ title, kicker, children }: { title: string; kicker?: string; children?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3">
      <div>
        {kicker && <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-accent">{kicker}</p>}
        <h1 className="mt-1 font-display text-[28px] font-semibold leading-tight tracking-tight">{title}</h1>
      </div>
      {children}
    </div>
  );
}
