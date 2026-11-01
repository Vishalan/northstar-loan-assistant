#!/usr/bin/env node
// Mock implementation of docs/api-contract.md (v1) for front-end development.
// Plain Node http, no dependencies.  Usage:  node scripts/mock-api.mjs  [PORT=8787] [SPEED=1]
//   SPEED=0.25 makes the stream 4x faster (handy for screenshots/tests).

import http from "node:http";
import { randomUUID } from "node:crypto";

const PORT = Number(process.env.PORT || 8787);
const SPEED = Number(process.env.SPEED || 1);
const DEMO_LOGIN_OTP = "246810";
const DEMO_ACTION_OTP = "123456";

/* ------------------------------------------------------------------ */
/* Canned data                                                         */
/* ------------------------------------------------------------------ */
const personas = [
  {
    customer_id: "C-1001",
    name: "Rohit Mehta",
    phone: "+919820011223",
    summary: "Personal loan; EMI rose after a rate reset and one EMI bounced in June.",
  },
  {
    customer_id: "C-1002",
    name: "Ananya Rao",
    phone: "+919845533001",
    summary: "Home loan on a floating rate, thinking about a ₹2 lakh prepayment.",
  },
  {
    customer_id: "C-1003",
    name: "Priya Nair",
    phone: "+919900477812",
    summary: "Credit card holder disputing a duplicate merchant charge.",
  },
];

const today = new Date();
const iso = (d) => d.toISOString();
const dayOnly = (d) => d.toISOString().slice(0, 10);
const addDays = (n) => new Date(today.getTime() + n * 86400000);

function overviewFor(customer) {
  return {
    customer: { customer_id: customer.customer_id, name: customer.name, segment: "Salaried · Gold" },
    loans: [
      {
        loan_id: "PL-20391",
        product_name: "Personal Loan",
        rate_type: "floating_eblr",
        current_rate: 11.25,
        emi: 17486,
        outstanding_principal: 662410,
        next_due_date: dayOnly(addDays(6)),
        tenure_left_months: 44,
        principal: 800000,
        status: "active",
      },
    ],
    cards: [
      {
        card_id: "CC-7781",
        last4: "4821",
        limit: 250000,
        outstanding: 48210,
        min_due: 2411,
        due_date: dayOnly(addDays(12)),
        statement_total: 48210,
      },
    ],
    payments: [
      { txn_id: "T-9006", loan_id: "PL-20391", date: dayOnly(addDays(-24)), amount: 17486, status: "success" },
      { txn_id: "T-9005", loan_id: "PL-20391", date: dayOnly(addDays(-55)), amount: 17486, status: "success" },
      { txn_id: "T-9004", loan_id: "PL-20391", date: dayOnly(addDays(-86)), amount: 17195, status: "success" },
      {
        txn_id: "T-9003",
        loan_id: "PL-20391",
        date: dayOnly(addDays(-117)),
        amount: 17195,
        status: "failed",
        failure_reason: "Insufficient funds (NACH return)",
        charge: 590,
      },
      { txn_id: "T-9002", loan_id: "PL-20391", date: dayOnly(addDays(-148)), amount: 17195, status: "success" },
      { txn_id: "T-9001", loan_id: "PL-20391", date: dayOnly(addDays(-178)), amount: 17195, status: "success" },
    ],
    requests: state.requests,
    degraded: state.chaos === "bad_day" ? ["Card Processor"] : [],
  };
}

const state = {
  tokens: new Map(), // token -> customer
  challenges: new Map(), // id -> customer
  sessions: new Map(), // id -> customer
  turns: new Map(), // turn_id -> { cancelled }
  actions: new Map(), // action_id -> proposal
  requests: [
    {
      request_id: "SR-48120",
      type: "statement",
      status: "completed",
      created_at: iso(addDays(-9)),
      sla_due: iso(addDays(-8)),
      summary: "Loan account statement, Apr–Sep 2026",
    },
  ],
  chaos: "realistic",
  client: new Map(), // metric name -> [ms]
  turnLog: [],
};

const CHAOS = {
  calm: { "Loan Management": [80, 0], Payments: [70, 0], "Card Processor": [90, 0], "Policy Library": [40, 0] },
  realistic: { "Loan Management": [180, 0.01], Payments: [240, 0.02], "Card Processor": [320, 0.03], "Policy Library": [60, 0] },
  bad_day: { "Loan Management": [900, 0.05], Payments: [1300, 0.12], "Card Processor": [2400, 0.4], "Policy Library": [90, 0] },
};
const chaosBody = () => ({
  preset: state.chaos,
  presets: Object.keys(CHAOS),
  systems: Object.fromEntries(
    Object.entries(CHAOS[state.chaos]).map(([k, [m, f]]) => [k, { median_ms: m, fail_rate: f }]),
  ),
});

/* ------------------------------------------------------------------ */
/* HTTP helpers                                                        */
/* ------------------------------------------------------------------ */
function cors(res) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Headers", "Authorization, Content-Type, Accept");
  res.setHeader("Access-Control-Allow-Methods", "GET, POST, PUT, OPTIONS");
}
function json(res, status, body) {
  cors(res);
  res.writeHead(status, { "Content-Type": "application/json" });
  res.end(JSON.stringify(body));
}
const err = (res, status, code, message, retryable = false) =>
  json(res, status, { error: { code, message, retryable } });

async function readBody(req) {
  const chunks = [];
  for await (const c of req) chunks.push(c);
  const raw = Buffer.concat(chunks).toString("utf8");
  if (!raw) return {};
  try {
    return JSON.parse(raw);
  } catch {
    return {};
  }
}
function authed(req, url) {
  const h = req.headers.authorization ?? "";
  const token = h.startsWith("Bearer ") ? h.slice(7) : url.searchParams.get("token");
  return token ? state.tokens.get(token) : undefined;
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms * SPEED));
const pct = (arr, p) => {
  if (!arr.length) return 0;
  const s = [...arr].sort((a, b) => a - b);
  return Math.round(s[Math.min(s.length - 1, Math.floor((p / 100) * s.length))]);
};

/* ------------------------------------------------------------------ */
/* Turn scenarios                                                      */
/* ------------------------------------------------------------------ */
function scenarioFor(text) {
  const t = text.toLowerCase();
  if (/fail|bounce|missed|charge|dispute/.test(t)) return failedPaymentScenario();
  if (/statement/.test(t)) return statementScenario();
  if (/prepay|part.?pay|foreclos|reduce/.test(t)) return prepaymentScenario();
  return emiScenario();
}

function emiScenario() {
  return {
    status: ["Looking up your loan and rate history…", "Checking the policy on rate resets…"],
    tools: [
      { tool: "get_loan", system: "Loan Management", label: "Loan details" },
      { tool: "get_rate_history", system: "Loan Management", label: "Rate history" },
      { tool: "search_policy", system: "Policy Library", label: "Loan terms" },
    ],
    focus: "PL-20391",
    answer:
      "Your EMI on **PL-20391** went up from **₹17,195** to **₹17,486** (+₹291) from your August instalment.\n\n" +
      "This happened because your loan is on a floating rate linked to the bank's EBLR, which rose by 0.25% on 1 July. " +
      "Your tenure was kept the same, so the change shows up in the EMI.\n\n" +
      "- New rate: **11.25%** (was 11.00%)\n- Tenure left: 44 months\n- No action is needed from you.",
    cards: [
      {
        type: "emi_change",
        title: "Why your EMI changed",
        subtitle: "Loan PL-20391 · Personal Loan",
        metrics: [
          { label: "Old EMI", value: "₹17,195" },
          { label: "New EMI", value: "₹17,486", emphasis: true, delta: "+₹291" },
          { label: "Rate", value: "11.25%", delta: "+0.25%" },
        ],
        table: {
          columns: ["Effective", "EBLR", "Spread", "Your rate", "EMI"],
          rows: [
            ["1 Jan 2026", "8.75%", "2.25%", "11.00%", "₹17,195"],
            ["1 Jul 2026", "9.00%", "2.25%", "11.25%", "₹17,486"],
          ],
          row_status: [null, "warn"],
        },
        notes: ["Floating rate linked to EBLR; resets are passed on from the next instalment.", "You can choose to keep the EMI and extend tenure instead."],
        actions: [
          { label: "Keep EMI, extend tenure", prompt: "Can I keep my old EMI and extend the tenure instead?" },
          { label: "What if I prepay ₹50,000?", prompt: "What would a ₹50,000 prepayment save me?" },
        ],
        sources: [
          { kind: "record", system: "Loan Management", ref: "rate_history/PL-20391", as_of: iso(today) },
          { kind: "policy", ref: "LOAN-TNC-7.2", text: "For floating rate loans, any change in the External Benchmark Lending Rate shall be passed on to the borrower from the next EMI cycle, by revising the EMI while keeping the tenure unchanged, unless the borrower opts otherwise." },
          { kind: "calc", ref: "emi_recalc", steps: ["Outstanding ₹6,78,920 at reset, 47 months remaining", "Monthly rate 11.25% ÷ 12 = 0.9375%", "EMI = P·r·(1+r)^n ÷ ((1+r)^n − 1) = ₹17,486"] },
        ],
      },
    ],
    action: null,
    chips: ["What if I prepay ₹50,000?", "Show my recent payments", "Download my loan statement"],
  };
}

function prepaymentScenario() {
  return {
    status: ["Pulling your outstanding balance…", "Comparing prepayment options…"],
    tools: [
      { tool: "get_loan", system: "Loan Management", label: "Loan details" },
      { tool: "simulate_prepayment", system: "Loan Management", label: "Prepayment calculator" },
      { tool: "search_policy", system: "Policy Library", label: "Prepayment rules" },
    ],
    focus: "PL-20391",
    answer:
      "A **₹50,000** prepayment on PL-20391 can either cut your tenure or lower your EMI. " +
      "Reducing tenure saves more interest — about **₹31,200** — and you'd finish 4 months early. " +
      "There is no prepayment charge on floating-rate loans.\n\nShall I raise a prepayment request to reduce your tenure? You'll need to confirm it with an OTP.",
    cards: [
      {
        type: "prepayment_compare",
        title: "Prepaying ₹50,000",
        subtitle: "Loan PL-20391 · outstanding ₹6,62,410",
        metrics: [
          { label: "Prepayment", value: "₹50,000" },
          { label: "Charges", value: "₹0" },
        ],
        columns: [
          { label: "Reduce tenure", metrics: [ { label: "Interest saved", value: "₹31,200", emphasis: true }, { label: "Tenure", value: "40 months", delta: "−4 mo" }, { label: "EMI", value: "₹17,486" } ] },
          { label: "Reduce EMI", metrics: [ { label: "Interest saved", value: "₹11,840" }, { label: "Tenure", value: "44 months" }, { label: "EMI", value: "₹16,166", delta: "−₹1,320" } ] },
        ],
        table: {
          columns: ["Option", "Total interest", "Last EMI"],
          rows: [
            ["No prepayment", "₹1,06,974", "Jun 2030"],
            ["Reduce tenure", "₹75,774", "Feb 2030"],
            ["Reduce EMI", "₹95,134", "Jun 2030"],
          ],
          row_status: [null, "ok", null],
        },
        notes: ["No prepayment charge applies to floating-rate loans (RBI guidelines)."],
        actions: [{ label: "Request this prepayment", prompt: "Go ahead and request a ₹50,000 prepayment to reduce my tenure" }],
        sources: [
          { kind: "record", system: "Loan Management", ref: "loan/PL-20391", as_of: iso(today) },
          { kind: "policy", ref: "LOAN-TNC-9.1", text: "No foreclosure or part-prepayment charges shall be levied on floating rate term loans sanctioned to individual borrowers." },
          { kind: "calc", ref: "prepayment_savings", steps: ["Outstanding ₹6,62,410 − ₹50,000 = ₹6,12,410", "At EMI ₹17,486 and 0.9375%/month, n = 40 months", "Interest: 40 × ₹17,486 − ₹6,12,410 = ₹75,774 (vs ₹1,06,974)", "Saving = ₹31,200"] },
        ],
      },
    ],
    action: {
      action: "create_prepayment_request",
      title: "Prepayment request",
      summary: [
        { label: "Loan", value: "PL-20391" },
        { label: "Amount", value: "₹50,000" },
        { label: "Apply to", value: "Reduce tenure" },
        { label: "Debit from", value: "HDFC ••2290 (registered)" },
      ],
      tier: "confirm_otp",
      demo_otp: DEMO_ACTION_OTP,
    },
    chips: ["What if I prepay ₹1,00,000 instead?", "When will the prepayment reflect?"],
  };
}

function failedPaymentScenario() {
  return {
    status: ["Checking your recent payments…", "Looking up the bounce charge…"],
    tools: [
      { tool: "get_payments", system: "Payments", label: "Payment history" },
      { tool: "get_charges", system: "Loan Management", label: "Charges" },
      { tool: "get_card", system: "Card Processor", label: "Card account" },
    ],
    focus: "PL-20391",
    answer:
      "Your June EMI of **₹17,195** on PL-20391 failed because the NACH debit was returned for insufficient funds. " +
      "A bounce charge of **₹590** (₹500 + GST) was added.\n\nYou paid on time in every other month, so you can ask for a one-time waiver. Do you want me to raise a dispute for the charge?",
    cards: [
      {
        type: "payment_history",
        title: "Payments in the last 6 months",
        subtitle: "Loan PL-20391",
        metrics: [
          { label: "On time", value: "5 of 6" },
          { label: "Bounce charge", value: "₹590", emphasis: true },
        ],
        table: {
          columns: ["Date", "Amount", "Status", "Reason"],
          rows: [
            ["Oct 2026", "₹17,486", "Paid", "—"],
            ["Sep 2026", "₹17,486", "Paid", "—"],
            ["Aug 2026", "₹17,195", "Paid", "—"],
            ["Jun 2026", "₹17,195", "Failed", "Insufficient funds"],
            ["May 2026", "₹17,195", "Paid", "—"],
          ],
          row_status: ["ok", "ok", "ok", "bad", "ok"],
        },
        notes: ["One-time waiver is available if no other bounce in 12 months."],
        actions: [{ label: "Dispute the charge", prompt: "Please raise a dispute for the ₹590 bounce charge" }],
        sources: [
          { kind: "record", system: "Payments", ref: "nach/PL-20391?months=6", as_of: iso(today) },
          { kind: "policy", ref: "FEES-3.4", text: "A dishonour charge of ₹500 plus applicable taxes is levied per returned instrument or mandate. One waiver may be granted in a rolling 12-month period." },
        ],
      },
    ],
    action: {
      action: "create_payment_dispute",
      title: "Dispute bounce charge",
      summary: [
        { label: "Loan", value: "PL-20391" },
        { label: "Charge", value: "₹590" },
        { label: "Reason", value: "First bounce in 12 months — waiver request" },
      ],
      tier: "confirm",
    },
    chips: ["How do I avoid this next time?", "Show my card dues"],
  };
}

function statementScenario() {
  return {
    status: ["Preparing your statement request…"],
    tools: [{ tool: "get_loan", system: "Loan Management", label: "Loan details" }],
    focus: "PL-20391",
    answer: "I can generate a statement for **PL-20391** covering the last six months. Shall I go ahead?",
    cards: [],
    action: {
      action: "create_statement_request",
      title: "Loan statement",
      summary: [
        { label: "Loan", value: "PL-20391" },
        { label: "Period", value: "Last 6 months" },
        { label: "Format", value: "PDF" },
      ],
      tier: "confirm",
    },
    chips: ["Why did my EMI change?"],
  };
}

async function streamTurn(req, res, session, body) {
  const turn_id = `turn_${randomUUID().slice(0, 8)}`;
  const turn = { cancelled: false };
  state.turns.set(turn_id, turn);
  const started = Date.now();
  let seq = 0;
  let closed = false;
  req.on("close", () => (closed = true));
  res.on("close", () => (closed = true));

  cors(res);
  res.writeHead(200, { "Content-Type": "text/event-stream", "Cache-Control": "no-cache", Connection: "keep-alive" });
  const send = (event, data) => {
    if (closed) return;
    res.write(`event: ${event}\ndata: ${JSON.stringify({ turn_id, seq: seq++, ts: Date.now(), ...data })}\n\n`);
  };
  const stop = () => closed || turn.cancelled;

  const sc = scenarioFor(String(body.text ?? ""));
  const sys = CHAOS[state.chaos];
  let firstToken = null;
  try {
    send("turn.started", { session_id: session, channel: body.channel ?? "text" });
    await sleep(60);
    send("status", { text: sc.status[0] });
    for (const [i, t] of sc.tools.entries()) {
      if (stop()) break;
      const call_id = `call_${i}_${turn_id}`;
      send("tool.started", { call_id, ...t });
      const [median, fail] = sys[t.system] ?? [100, 0];
      const latency = Math.round(median * (0.6 + Math.random() * 0.8));
      await sleep(Math.min(latency, 1500));
      const status = Math.random() < fail ? (fail > 0.2 ? "unavailable" : "degraded") : "ok";
      send("tool.finished", { call_id, tool: t.tool, status, latency_ms: latency, from_cache: i === 0 && Math.random() < 0.3 });
      if (i === 0 && sc.status[1]) send("status", { text: sc.status[1] });
    }
    if (!stop()) send("focus", { product_id: sc.focus });
    // stream the answer in small word-ish chunks
    const chunks = sc.answer.match(/\S+\s*|\s+/g) ?? [];
    for (let i = 0; i < chunks.length && !stop(); i += 2) {
      if (firstToken == null) firstToken = Date.now() - started;
      send("answer.delta", { text: chunks.slice(i, i + 2).join("") });
      await sleep(45);
    }
    if (!stop()) send("answer.verified", { ok: true });
    for (const card of sc.cards) {
      if (stop()) break;
      await sleep(120);
      send("card", card);
    }
    if (sc.action && !stop()) {
      const action_id = `act_${randomUUID().slice(0, 8)}`;
      const proposal = { action_id, ...sc.action, expires_at: iso(new Date(Date.now() + 10 * 60000)) };
      state.actions.set(action_id, proposal);
      send("action.proposed", proposal);
    }
    if (!stop()) send("suggestions", { chips: sc.chips });
    if (turn.cancelled) {
      send("turn.error", { code: "cancelled", message: "Turn cancelled", retryable: false });
    } else if (!closed) {
      const total = Date.now() - started;
      send("turn.completed", {
        timings: { first_status_ms: 60, first_token_ms: firstToken, total_ms: total, llm_ms: Math.round(total * 0.55), tools_ms: Math.round(total * 0.3) },
        mode: "llm",
      });
    }
    state.turnLog.unshift({ turn_id, channel: body.channel ?? "text", mode: "llm", first_token_ms: firstToken, total_ms: Date.now() - started, at: iso(new Date()) });
    state.turnLog = state.turnLog.slice(0, 200);
  } finally {
    state.turns.delete(turn_id);
    if (!closed) res.end();
  }
}

/* ------------------------------------------------------------------ */
/* Router                                                              */
/* ------------------------------------------------------------------ */
const server = http.createServer(async (req, res) => {
  const url = new URL(req.url ?? "/", `http://${req.headers.host}`);
  const p = url.pathname;
  const m = req.method ?? "GET";
  if (m === "OPTIONS") {
    cors(res);
    res.writeHead(204);
    return res.end();
  }
  console.log(`${m} ${p}`);

  // ---- public
  if (m === "GET" && p === "/v1/personas") return json(res, 200, personas);
  if (m === "POST" && p === "/v1/auth/otp/start") {
    const { phone } = await readBody(req);
    const c = personas.find((x) => x.phone === phone);
    if (!c) return err(res, 404, "unknown_phone", "That number isn't registered with us.");
    const challenge_id = `ch_${randomUUID().slice(0, 8)}`;
    state.challenges.set(challenge_id, c);
    return json(res, 200, { challenge_id, demo_code: DEMO_LOGIN_OTP });
  }
  if (m === "POST" && p === "/v1/auth/otp/verify") {
    const { challenge_id, code } = await readBody(req);
    const c = state.challenges.get(challenge_id);
    if (!c) return err(res, 400, "challenge_expired", "This code has expired. Please request a new one.");
    if (code !== DEMO_LOGIN_OTP) return err(res, 400, "otp_invalid", "That code is incorrect. Please try again.");
    const access_token = `tok_${randomUUID()}`;
    state.tokens.set(access_token, c);
    return json(res, 200, { access_token, expires_in: 3600, customer: { customer_id: c.customer_id, name: c.name } });
  }

  // ---- authenticated
  const customer = authed(req, url);
  if (!customer) return err(res, 401, "unauthorized", "Please sign in again.");

  if (m === "POST" && p === "/v1/sessions") {
    const session_id = `sess_${randomUUID().slice(0, 8)}`;
    state.sessions.set(session_id, customer);
    return json(res, 200, {
      session_id,
      customer: { customer_id: customer.customer_id, name: customer.name },
      products: [
        { type: "loan", id: "PL-20391", label: "Personal Loan ••0391" },
        { type: "card", id: "CC-7781", label: "Credit Card ••4821" },
      ],
      suggestions: ["Why did my EMI change?", "Why did my June payment fail?", "What if I prepay ₹50,000?", "Download my loan statement"],
    });
  }
  let mm;
  if (m === "POST" && (mm = p.match(/^\/v1\/sessions\/([^/]+)\/turns$/))) {
    if (!state.sessions.has(mm[1])) return err(res, 404, "session_not_found", "Session not found.");
    return streamTurn(req, res, mm[1], await readBody(req));
  }
  if (m === "POST" && (mm = p.match(/^\/v1\/sessions\/([^/]+)\/prefetch$/))) {
    const { text } = await readBody(req);
    return json(res, 200, { warmed: /pay|emi/i.test(text ?? "") ? ["get_loan", "get_payments"] : ["get_loan"] });
  }
  if (m === "POST" && (mm = p.match(/^\/v1\/turns\/([^/]+)\/cancel$/))) {
    const body = await readBody(req);
    const t = state.turns.get(mm[1]);
    if (t) t.cancelled = true;
    console.log(`  cancel ${mm[1]} spoken_text=${JSON.stringify(body.spoken_text ?? "")}`);
    return json(res, 200, { ok: true });
  }
  if (m === "POST" && (mm = p.match(/^\/v1\/actions\/([^/]+)\/(confirm|cancel)$/))) {
    const a = state.actions.get(mm[1]);
    if (!a) return err(res, 404, "action_not_found", "This request is no longer available.");
    if (mm[2] === "cancel") {
      state.actions.delete(mm[1]);
      return json(res, 200, { action_id: a.action_id, status: "cancelled" });
    }
    const body = await readBody(req);
    await sleep(400);
    if (a.tier === "confirm_otp" && body.otp !== DEMO_ACTION_OTP)
      return json(res, 200, { action_id: a.action_id, status: "otp_invalid", message: "That OTP didn't match. Please check and try again." });
    state.actions.delete(mm[1]);
    const request_id = `SR-${Math.floor(48200 + Math.random() * 700)}`;
    const type = a.action.replace(/^create_/, "").replace(/_request$/, "");
    const sla_due = iso(addDays(type === "statement" ? 1 : 3));
    state.requests.unshift({ request_id, type, status: type === "statement" ? "completed" : "submitted", created_at: iso(new Date()), sla_due, summary: a.summary.map((s) => s.value).join(" · ") });
    return json(res, 200, {
      action_id: a.action_id,
      status: "succeeded",
      request_id,
      sla_due,
      message: `Done. Your ${a.title.toLowerCase()} is raised with reference ${request_id}. We'll complete it within ${type === "statement" ? "1 working day" : "3 working days"}.`,
    });
  }
  if (m === "GET" && p === "/v1/account/overview") return json(res, 200, overviewFor(customer));
  if (m === "GET" && p === "/v1/requests") return json(res, 200, state.requests);
  if (m === "GET" && p === "/v1/metrics/latency") {
    const turns = state.turnLog;
    const tok = turns.map((t) => t.first_token_ms).filter((x) => x != null);
    const tot = turns.map((t) => t.total_ms);
    return json(res, 200, {
      stages: [
        { name: "first_status", count: turns.length || 40, p50_ms: 62, p95_ms: 118 },
        { name: "tools", count: turns.length || 40, p50_ms: 420, p95_ms: 1180 },
        { name: "llm_first_token", count: turns.length || 40, p50_ms: 610, p95_ms: 1340 },
        { name: "first_token", count: tok.length || 40, p50_ms: pct(tok, 50) || 780, p95_ms: pct(tok, 95) || 1650 },
        { name: "total", count: tot.length || 40, p50_ms: pct(tot, 50) || 2900, p95_ms: pct(tot, 95) || 5200 },
      ],
      systems: Object.entries(CHAOS[state.chaos]).map(([system, [med, fail]]) => ({ system, count: 120, p50_ms: med, p95_ms: Math.round(med * 2.4), error_rate: fail })),
      turns,
      client: [...state.client.entries()].map(([name, arr]) => ({ name, count: arr.length, p50_ms: pct(arr, 50), p95_ms: pct(arr, 95) })),
    });
  }
  if (m === "POST" && p === "/v1/metrics/client") {
    const { name, ms } = await readBody(req);
    if (!state.client.has(name)) state.client.set(name, []);
    state.client.get(name).push(Number(ms));
    return json(res, 200, { ok: true });
  }
  if (p === "/v1/demo/chaos") {
    if (m === "PUT") {
      const { preset } = await readBody(req);
      if (!CHAOS[preset]) return err(res, 400, "bad_preset", "Unknown preset.");
      state.chaos = preset;
    }
    return json(res, 200, chaosBody());
  }
  if (m === "GET" && p === "/v1/evals/latest") {
    if (url.searchParams.get("empty") === "1") return json(res, 200, {});
    return json(res, 200, {
      run_at: iso(addDays(-1)),
      total: 6,
      passed: 5,
      figure_accuracy: 0.975,
      cases: [
        { id: "emi-001", pack: "emi", question: "Why did my EMI change?", passed: true, reason: "All figures match records", latency_ms: 2140 },
        { id: "emi-002", pack: "emi", question: "What is my current rate?", passed: true, reason: "Exact", latency_ms: 1210 },
        { id: "pay-001", pack: "payments", question: "Why did my June payment fail?", passed: true, reason: "Reason and charge cited", latency_ms: 2380 },
        { id: "pre-001", pack: "prepayment", question: "What does a ₹50,000 prepayment save?", passed: false, reason: "Interest saved off by ₹120 (rounding)", latency_ms: 3010 },
        { id: "pre-002", pack: "prepayment", question: "Is there a prepayment charge?", passed: true, reason: "Policy clause cited", latency_ms: 1640 },
        { id: "act-001", pack: "actions", question: "Raise a statement request", passed: true, reason: "Action proposed with confirm tier", latency_ms: 1720 },
      ],
    });
  }
  if (m === "GET" && (mm = p.match(/^\/v1\/statements\/([^/]+)$/))) {
    const pdf = minimalPdf(`Northstar Finance - Statement ${mm[1]} (synthetic demo data)`);
    cors(res);
    res.writeHead(200, { "Content-Type": "application/pdf", "Content-Disposition": `inline; filename="${mm[1]}.pdf"` });
    return res.end(pdf);
  }
  return err(res, 404, "not_found", `No route for ${m} ${p}`);
});

function minimalPdf(text) {
  const content = `BT /F1 14 Tf 60 760 Td (${text.replace(/[()\\]/g, "")}) Tj ET`;
  const objs = [
    "<< /Type /Catalog /Pages 2 0 R >>",
    "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
    `<< /Length ${content.length} >>\nstream\n${content}\nendstream`,
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
  ];
  let out = "%PDF-1.4\n";
  const offsets = [];
  objs.forEach((o, i) => {
    offsets.push(out.length);
    out += `${i + 1} 0 obj\n${o}\nendobj\n`;
  });
  const xref = out.length;
  out += `xref\n0 ${objs.length + 1}\n0000000000 65535 f \n${offsets.map((o) => `${String(o).padStart(10, "0")} 00000 n \n`).join("")}`;
  out += `trailer\n<< /Size ${objs.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF`;
  return Buffer.from(out, "latin1");
}

server.listen(PORT, () => {
  console.log(`Northstar mock API on http://localhost:${PORT}  (login OTP ${DEMO_LOGIN_OTP}, action OTP ${DEMO_ACTION_OTP}, SPEED=${SPEED})`);
});
