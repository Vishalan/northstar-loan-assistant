// Types mirroring docs/api-contract.md (v1). Keep in sync with the contract.

export type Persona = { customer_id: string; name: string; phone: string; summary: string };

export type OtpStartResponse = { challenge_id: string; demo_code?: string };
export type OtpVerifyResponse = {
  access_token: string;
  expires_in: number;
  customer: { customer_id: string; name: string };
};

export type Product = { type: "loan" | "card"; id: string; label: string };
export type SessionResponse = {
  session_id: string;
  customer: { customer_id: string; name: string };
  products: Product[];
  suggestions: string[];
};

export type Channel = "text" | "voice";

export type Metric = { label: string; value: string; emphasis?: boolean; delta?: string };
export type RowStatus = "ok" | "warn" | "bad" | null;
export type CardSource =
  | { kind: "record"; system: string; ref: string; as_of?: string }
  | { kind: "policy"; ref: string; text?: string }
  | { kind: "calc"; ref: string; steps?: string[] };

export type Card = {
  type: string;
  title: string;
  subtitle?: string;
  metrics?: Metric[];
  columns?: { label: string; metrics: Metric[] }[];
  table?: { columns: string[]; rows: string[][]; row_status?: RowStatus[] };
  notes?: string[];
  actions?: { label: string; prompt: string }[];
  sources?: CardSource[];
};

export type ActionTier = "read" | "confirm" | "confirm_otp";
export type ActionProposal = {
  action_id: string;
  action: string;
  title: string;
  summary: { label: string; value: string }[];
  tier: ActionTier;
  expires_at?: string;
  demo_otp?: string;
};

export type ConfirmResponse = {
  action_id: string;
  status: "succeeded" | "failed" | "otp_invalid" | "expired";
  request_id?: string;
  sla_due?: string;
  message: string;
};

type Base = { turn_id: string; seq: number; ts: number };
export type TurnEventMap = {
  "turn.started": Base & { session_id: string; channel: Channel };
  status: Base & { text: string };
  "tool.started": Base & { call_id: string; tool: string; system: string; label: string };
  "tool.finished": Base & {
    call_id: string;
    tool: string;
    status: "ok" | "degraded" | "unavailable";
    latency_ms: number;
    from_cache: boolean;
  };
  focus: Base & { product_id: string };
  "answer.delta": Base & { text: string };
  "answer.verified": Base & { ok: boolean; replaced_text?: string };
  card: Base & Card;
  "action.proposed": Base & ActionProposal;
  suggestions: Base & { chips: string[] };
  "turn.completed": Base & {
    timings: {
      first_status_ms?: number;
      first_token_ms?: number;
      total_ms?: number;
      llm_ms?: number;
      tools_ms?: number;
    };
    mode: "llm" | "fallback";
  };
  "turn.error": Base & { code: string; message: string; retryable: boolean };
};
export type TurnEventName = keyof TurnEventMap;
export type AnyTurnEvent = {
  [K in TurnEventName]: { name: K; data: TurnEventMap[K] };
}[TurnEventName];

export type Loan = {
  loan_id: string;
  product_name: string;
  rate_type: string;
  current_rate: number;
  emi: number;
  outstanding_principal: number;
  next_due_date: string;
  tenure_left_months: number;
  principal: number;
  status: string;
};
export type CreditCard = {
  card_id: string;
  last4: string;
  limit: number;
  outstanding: number;
  min_due: number;
  due_date: string;
  statement_total: number;
};
export type Payment = {
  txn_id: string;
  loan_id: string;
  date: string;
  amount: number;
  status: "success" | "failed" | "reversed";
  failure_reason?: string;
  charge?: number;
};
export type ServiceRequest = {
  request_id: string;
  type: string;
  status: string;
  created_at: string;
  sla_due: string;
  summary: string;
};
export type Overview = {
  customer: { customer_id: string; name: string; segment: string };
  loans: Loan[];
  cards: CreditCard[];
  payments: Payment[];
  requests: ServiceRequest[];
  degraded: string[];
};

export type StageStat = { name: string; count: number; p50_ms: number; p95_ms: number };
export type LatencyMetrics = {
  stages: StageStat[];
  systems: { system: string; count: number; p50_ms: number; p95_ms: number; error_rate: number }[];
  turns: {
    turn_id: string;
    channel: Channel;
    mode: string;
    first_token_ms: number | null;
    total_ms: number | null;
    at: string;
  }[];
  client: StageStat[];
};
export type ClientMetricName = "voice.eos_to_first_audio" | "voice.bargein_stop" | "voice.echo_dropped" | "text.first_token_render";

export type ChaosPreset = "calm" | "realistic" | "bad_day";
export type ChaosState = {
  preset: string;
  presets: string[];
  systems: Record<string, { median_ms: number; fail_rate: number }>;
};

export type EvalCase = {
  id: string;
  pack: string;
  question: string;
  passed: boolean;
  reason: string;
  latency_ms: number;
};
export type EvalRun = {
  run_at?: string;
  total?: number;
  passed?: number;
  figure_accuracy?: number;
  cases?: EvalCase[];
};
