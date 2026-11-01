"use client";

// Owns the single in-flight turn of the session: POSTs the turn, parses the SSE stream,
// writes into the chat store and fans events out to listeners (the VoiceController).

import { ApiError, api, authHeaders, toApiError } from "./api";
import { uid, useChat } from "./chat-store";
import { createSSEParser } from "./sse-parser";
import type { ActionProposal, AnyTurnEvent, Channel, ConfirmResponse, TurnEventName } from "./types";

export type LocalEnd = { name: "local.ended"; data: { reason: "aborted" | "network" | "incomplete" } };
export type EngineEvent = AnyTurnEvent | LocalEnd;
export type EngineContext = { messageId: string; channel: Channel; turnId: string | null };
type Listener = (ev: EngineEvent, ctx: EngineContext) => void;

type Current = {
  abort: AbortController;
  turnId: string | null;
  messageId: string;
  channel: Channel;
  sentAt: number;
  gotToken: boolean;
  terminal: boolean;
};

const KNOWN: Set<string> = new Set<TurnEventName>([
  "turn.started", "status", "tool.started", "tool.finished", "focus", "answer.delta", "answer.verified",
  "card", "action.proposed", "suggestions", "turn.completed", "turn.error",
]);

class TurnEngine {
  private current: Current | null = null;
  private listeners = new Set<Listener>();

  subscribe(fn: Listener): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  private emit(ev: EngineEvent, cur: Current) {
    const ctx = { messageId: cur.messageId, channel: cur.channel, turnId: cur.turnId };
    for (const l of this.listeners) {
      try {
        l(ev, ctx);
      } catch (e) {
        console.error("turn listener failed", e);
      }
    }
  }

  get inFlight() {
    return this.current !== null;
  }
  get currentTurnId() {
    return this.current?.turnId ?? null;
  }
  get currentChannel() {
    return this.current?.channel ?? null;
  }

  /** Send a user turn. Any in-flight turn is aborted and cancelled server-side first. */
  async send(text: string, channel: Channel = "text"): Promise<void> {
    const trimmed = text.trim();
    const store = useChat.getState();
    if (!trimmed || !store.sessionId) return;
    if (this.current) this.interrupt();

    const messageId = uid("a");
    store.push({ role: "user", id: uid("u"), text: trimmed, channel, at: Date.now() });
    store.push({
      role: "assistant",
      id: messageId,
      turnId: null,
      channel,
      text: "",
      state: "streaming",
      status: null,
      tools: [],
      attachments: [],
      at: Date.now(),
    });
    store.setSuggestions([]);
    store.setInFlight(true);

    const cur: Current = {
      abort: new AbortController(),
      turnId: null,
      messageId,
      channel,
      sentAt: performance.now(),
      gotToken: false,
      terminal: false,
    };
    this.current = cur;

    try {
      const res = await fetch(api.turnUrl(store.sessionId), {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "text/event-stream", ...authHeaders() },
        body: JSON.stringify({ text: trimmed, channel }),
        signal: cur.abort.signal,
      });
      if (!res.ok) {
        if (res.status === 401) {
          window.location.assign("/login?expired=1");
        }
        throw await toApiError(res);
      }
      if (!res.body) throw new ApiError("Streaming not supported by this browser.", 0, "no_stream", false);

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      const parser = createSSEParser((f) => this.handleFrame(f.event, f.data, cur));
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        parser.feed(decoder.decode(value, { stream: true }));
      }
      parser.feed(decoder.decode());
      parser.end();
      if (!cur.terminal && !cur.abort.signal.aborted) {
        this.fail(cur, { code: "incomplete", message: "The connection closed before the answer finished.", retryable: true });
        this.emit({ name: "local.ended", data: { reason: "incomplete" } }, cur);
      }
    } catch (e) {
      if (cur.abort.signal.aborted) return; // interrupt() already updated the UI
      const err =
        e instanceof ApiError
          ? { code: e.code, message: e.message, retryable: e.retryable }
          : { code: "network", message: "Can't reach the assistant right now. Please try again.", retryable: true };
      this.fail(cur, err);
      this.emit({ name: "local.ended", data: { reason: "network" } }, cur);
    } finally {
      if (this.current === cur) {
        this.current = null;
        useChat.getState().setInFlight(false);
      }
    }
  }

  /** Stop the in-flight turn (new message or voice barge-in). */
  interrupt(spokenText?: string) {
    const cur = this.current;
    if (!cur) return;
    this.current = null;
    cur.abort.abort();
    if (cur.turnId) api.cancelTurn(cur.turnId, spokenText).catch(() => {});
    const store = useChat.getState();
    store.patchAssistant(cur.messageId, (m) => ({
      state: m.state === "streaming" ? "interrupted" : m.state,
      status: null,
      tools: m.tools.map((t) => (t.state === "running" ? { ...t, state: "unavailable" as const } : t)),
    }));
    store.setInFlight(false);
    this.emit({ name: "local.ended", data: { reason: "aborted" } }, cur);
  }

  private fail(cur: Current, error: { code: string; message: string; retryable: boolean }) {
    useChat.getState().patchAssistant(cur.messageId, (m) => ({
      state: error.code === "cancelled" ? "interrupted" : "error",
      error: error.code === "cancelled" ? undefined : error,
      status: null,
      tools: m.tools.map((t) => (t.state === "running" ? { ...t, state: "unavailable" as const } : t)),
    }));
  }

  private handleFrame(name: string, raw: string, cur: Current) {
    if (cur.abort.signal.aborted || !KNOWN.has(name)) return;
    let data: Record<string, unknown>;
    try {
      data = JSON.parse(raw);
    } catch {
      return;
    }
    const ev = { name, data } as AnyTurnEvent;
    const store = useChat.getState();
    const patch = (fn: Parameters<typeof store.patchAssistant>[1]) => store.patchAssistant(cur.messageId, fn);

    if (!cur.turnId && typeof data.turn_id === "string") {
      cur.turnId = data.turn_id;
      patch(() => ({ turnId: cur.turnId }));
    }

    switch (ev.name) {
      case "status":
        patch(() => ({ status: ev.data.text }));
        break;
      case "tool.started":
        patch((m) => ({
          tools: [
            ...m.tools.filter((t) => t.call_id !== ev.data.call_id),
            {
              call_id: ev.data.call_id,
              tool: ev.data.tool,
              system: ev.data.system,
              label: ev.data.label,
              state: "running",
            },
          ],
        }));
        break;
      case "tool.finished":
        patch((m) => ({
          tools: m.tools.map((t) =>
            t.call_id === ev.data.call_id
              ? { ...t, state: ev.data.status, latency_ms: ev.data.latency_ms, from_cache: ev.data.from_cache }
              : t,
          ),
        }));
        break;
      case "focus":
        store.setFocus(ev.data.product_id);
        break;
      case "answer.delta":
        if (!cur.gotToken) {
          cur.gotToken = true;
          if (cur.channel === "text") {
            const sentAt = cur.sentAt;
            requestAnimationFrame(() =>
              api.clientMetric("text.first_token_render", performance.now() - sentAt, { turn_id: cur.turnId }),
            );
          }
        }
        patch((m) => ({ text: m.text + ev.data.text }));
        break;
      case "answer.verified":
        patch(() =>
          ev.data.replaced_text != null
            ? { text: ev.data.replaced_text, verified: ev.data.ok, corrected: true }
            : { verified: ev.data.ok },
        );
        break;
      case "card": {
        const { turn_id: _t, seq, ts: _ts, ...card } = ev.data;
        void _t;
        void _ts;
        patch((m) => ({ attachments: [...m.attachments, { kind: "card", key: `c${seq}`, card }] }));
        break;
      }
      case "action.proposed": {
        const { turn_id: _t, seq: _s, ts: _ts, ...proposal } = ev.data;
        void _t;
        void _s;
        void _ts;
        store.setAction(proposal.action_id, { phase: "pending" });
        patch((m) => ({
          attachments: [...m.attachments, { kind: "action", key: proposal.action_id, proposal }],
        }));
        break;
      }
      case "suggestions":
        store.setSuggestions(ev.data.chips ?? []);
        break;
      case "turn.completed":
        cur.terminal = true;
        patch(() => ({
          state: "done",
          status: null,
          mode: ev.data.mode,
          timings: { first_token_ms: ev.data.timings?.first_token_ms, total_ms: ev.data.timings?.total_ms },
        }));
        store.bumpOverview();
        break;
      case "turn.error":
        cur.terminal = true;
        this.fail(cur, { code: ev.data.code, message: ev.data.message, retryable: ev.data.retryable });
        break;
    }
    this.emit(ev, cur);
  }

  /** Confirm a proposed action (button or voice). Updates the store and refreshes the account panel. */
  async confirmAction(
    proposal: ActionProposal,
    opts: { otp?: string; via: "button" | "voice" },
  ): Promise<ConfirmResponse | null> {
    const store = useChat.getState();
    store.setAction(proposal.action_id, { phase: "submitting" });
    try {
      const res = await api.confirmAction(proposal.action_id, {
        via: opts.via,
        ...(opts.otp ? { otp: opts.otp } : {}),
      });
      store.setAction(proposal.action_id, { phase: res.status, result: res, message: res.message });
      store.bumpOverview();
      return res;
    } catch (e) {
      const message = e instanceof Error ? e.message : "Something went wrong.";
      store.setAction(proposal.action_id, { phase: "error", message });
      return null;
    }
  }

  async cancelAction(proposal: ActionProposal) {
    const store = useChat.getState();
    store.setAction(proposal.action_id, { phase: "submitting" });
    try {
      await api.cancelAction(proposal.action_id);
      store.setAction(proposal.action_id, { phase: "cancelled", message: "Request cancelled. Nothing was changed." });
      store.bumpOverview();
    } catch (e) {
      store.setAction(proposal.action_id, {
        phase: "error",
        message: e instanceof Error ? e.message : "Could not cancel.",
      });
    }
  }
}

export const turnEngine = new TurnEngine();
