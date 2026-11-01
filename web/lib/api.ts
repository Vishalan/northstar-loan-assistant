import type {
  ChaosPreset,
  ChaosState,
  ClientMetricName,
  ConfirmResponse,
  EvalRun,
  LatencyMetrics,
  OtpStartResponse,
  OtpVerifyResponse,
  Overview,
  Persona,
  ServiceRequest,
  SessionResponse,
} from "./types";

export const API_URL = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");

const TOKEN_KEY = "ns.token";
const CUSTOMER_KEY = "ns.customer";

export type StoredCustomer = { customer_id: string; name: string };

function safeSession(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.sessionStorage;
  } catch {
    return null;
  }
}

export const auth = {
  token(): string | null {
    return safeSession()?.getItem(TOKEN_KEY) ?? null;
  },
  customer(): StoredCustomer | null {
    const raw = safeSession()?.getItem(CUSTOMER_KEY);
    if (!raw) return null;
    try {
      return JSON.parse(raw) as StoredCustomer;
    } catch {
      return null;
    }
  },
  save(token: string, customer: StoredCustomer) {
    const s = safeSession();
    s?.setItem(TOKEN_KEY, token);
    s?.setItem(CUSTOMER_KEY, JSON.stringify(customer));
  },
  clear() {
    const s = safeSession();
    s?.removeItem(TOKEN_KEY);
    s?.removeItem(CUSTOMER_KEY);
  },
};

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public code: string,
    public retryable: boolean,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export async function toApiError(res: Response): Promise<ApiError> {
  let code = `http_${res.status}`;
  let message = res.statusText || "Request failed";
  let retryable = res.status >= 500;
  try {
    const body = await res.json();
    if (body?.error) {
      code = body.error.code ?? code;
      message = body.error.message ?? message;
      retryable = Boolean(body.error.retryable);
    }
  } catch {
    /* non-JSON body */
  }
  return new ApiError(message, res.status, code, retryable);
}

function handleUnauthorized(status: number) {
  if (status === 401 && typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
    auth.clear();
    window.location.assign("/login?expired=1");
  }
}

export function authHeaders(): Record<string, string> {
  const t = auth.token();
  return t ? { Authorization: `Bearer ${t}` } : {};
}

type ReqOpts = { method?: string; body?: unknown; signal?: AbortSignal; noAuth?: boolean };

export async function request<T>(path: string, opts: ReqOpts = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  if (!opts.noAuth) Object.assign(headers, authHeaders());
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      method: opts.method ?? (opts.body !== undefined ? "POST" : "GET"),
      headers,
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
      signal: opts.signal,
    });
  } catch (e) {
    if ((e as Error).name === "AbortError") throw e;
    throw new ApiError("Can't reach Northstar servers. Check your connection.", 0, "network", true);
  }
  if (!res.ok) {
    handleUnauthorized(res.status);
    throw await toApiError(res);
  }
  return (await res.json()) as T;
}

const enc = encodeURIComponent;

export const api = {
  personas: () => request<Persona[]>("/v1/personas", { noAuth: true }),
  otpStart: (phone: string) =>
    request<OtpStartResponse>("/v1/auth/otp/start", { body: { phone }, noAuth: true }),
  otpVerify: (challenge_id: string, code: string) =>
    request<OtpVerifyResponse>("/v1/auth/otp/verify", { body: { challenge_id, code }, noAuth: true }),

  createSession: () => request<SessionResponse>("/v1/sessions", { body: {} }),
  prefetch: (sessionId: string, text: string) =>
    request<{ warmed: string[] }>(`/v1/sessions/${enc(sessionId)}/prefetch`, { body: { text } }),
  cancelTurn: (turnId: string, spoken_text?: string) =>
    request<{ ok: boolean }>(`/v1/turns/${enc(turnId)}/cancel`, {
      body: spoken_text ? { spoken_text } : {},
    }),
  confirmAction: (actionId: string, body: { otp?: string; via: "button" | "voice" }) =>
    request<ConfirmResponse>(`/v1/actions/${enc(actionId)}/confirm`, { body }),
  cancelAction: (actionId: string) =>
    request<{ action_id: string; status: "cancelled" }>(`/v1/actions/${enc(actionId)}/cancel`, { body: {} }),

  overview: (signal?: AbortSignal) => request<Overview>("/v1/account/overview", { signal }),
  requests: () => request<ServiceRequest[]>("/v1/requests"),

  latency: (window = 200) => request<LatencyMetrics>(`/v1/metrics/latency?window=${window}`),
  clientMetric: (name: ClientMetricName, ms: number, meta?: Record<string, unknown>) =>
    request<{ ok: boolean }>("/v1/metrics/client", { body: { name, ms: Math.round(ms), meta } }).catch(() => ({
      ok: false,
    })),

  chaos: () => request<ChaosState>("/v1/demo/chaos"),
  setChaos: (preset: ChaosPreset) => request<ChaosState>("/v1/demo/chaos", { method: "PUT", body: { preset } }),
  evals: () => request<EvalRun>("/v1/evals/latest"),

  statementUrl: (requestId: string) =>
    `${API_URL}/v1/statements/${enc(requestId)}?token=${enc(auth.token() ?? "")}`,
  turnUrl: (sessionId: string) => `${API_URL}/v1/sessions/${enc(sessionId)}/turns`,
};
