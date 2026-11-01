const inr = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 });
const num = new Intl.NumberFormat("en-IN");

export const formatINR = (n: number | null | undefined) => (n == null || Number.isNaN(n) ? "—" : inr.format(n));
export const formatNumber = (n: number | null | undefined) => (n == null ? "—" : num.format(n));

export function formatDate(iso: string | null | undefined, opts: Intl.DateTimeFormatOptions = {}) {
  if (!iso) return "—";
  const d = new Date(iso.length === 10 ? `${iso}T00:00:00` : iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric", ...opts });
}

export function formatDateTime(iso: string | null | undefined) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("en-IN", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });
}

export function formatMs(ms: number | null | undefined) {
  if (ms == null || Number.isNaN(ms)) return "—";
  if (ms >= 10_000) return `${(ms / 1000).toFixed(1)} s`;
  if (ms >= 1000) return `${(ms / 1000).toFixed(2)} s`;
  return `${Math.round(ms)} ms`;
}

export function daysUntil(iso: string): number | null {
  const d = new Date(iso.length === 10 ? `${iso}T00:00:00` : iso);
  if (Number.isNaN(d.getTime())) return null;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return Math.round((d.getTime() - today.getTime()) / 86_400_000);
}

export function tenureLabel(months: number) {
  const y = Math.floor(months / 12);
  const m = months % 12;
  if (!y) return `${m} mo`;
  return m ? `${y} yr ${m} mo` : `${y} yr`;
}

const ACRONYMS = /\b(eblr|mclr|emi|nach|otp|sla|gst|pdf)\b/gi;
export function humanize(s: string) {
  return s
    .replace(/[_.-]+/g, " ")
    .replace(/^\w/, (c) => c.toUpperCase())
    .replace(ACRONYMS, (a) => a.toUpperCase());
}

export const cx = (...c: Array<string | false | null | undefined>) => c.filter(Boolean).join(" ");
