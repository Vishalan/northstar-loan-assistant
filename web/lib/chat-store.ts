"use client";

import { create } from "zustand";
import type { ActionProposal, Card, Channel, ConfirmResponse, Product } from "./types";

export type ToolProgress = {
  call_id: string;
  tool: string;
  system: string;
  label: string;
  state: "running" | "ok" | "degraded" | "unavailable";
  latency_ms?: number;
  from_cache?: boolean;
};

export type Attachment =
  | { kind: "card"; key: string; card: Card }
  | { kind: "action"; key: string; proposal: ActionProposal };

export type UserMessage = { role: "user"; id: string; text: string; channel: Channel; at: number };
export type AssistantMessage = {
  role: "assistant";
  id: string;
  turnId: string | null;
  channel: Channel;
  text: string;
  state: "streaming" | "done" | "error" | "interrupted";
  status: string | null;
  tools: ToolProgress[];
  attachments: Attachment[];
  verified?: boolean;
  corrected?: boolean;
  error?: { code: string; message: string; retryable: boolean };
  mode?: "llm" | "fallback";
  timings?: { first_token_ms?: number; total_ms?: number };
  at: number;
};
export type ChatMessage = UserMessage | AssistantMessage;

export type ActionState = {
  phase: "pending" | "submitting" | "succeeded" | "failed" | "otp_invalid" | "expired" | "cancelled" | "error";
  result?: ConfirmResponse;
  message?: string;
};

type ChatState = {
  sessionId: string | null;
  products: Product[];
  messages: ChatMessage[];
  suggestions: string[];
  focusProductId: string | null;
  actions: Record<string, ActionState>;
  overviewNonce: number;
  inFlight: boolean;

  setSession(id: string, products: Product[], suggestions: string[]): void;
  push(m: ChatMessage): void;
  patchAssistant(id: string, fn: (m: AssistantMessage) => Partial<AssistantMessage>): void;
  setSuggestions(s: string[]): void;
  setFocus(id: string | null): void;
  setAction(id: string, s: ActionState): void;
  bumpOverview(): void;
  setInFlight(v: boolean): void;
  reset(): void;
};

export const useChat = create<ChatState>((set) => ({
  sessionId: null,
  products: [],
  messages: [],
  suggestions: [],
  focusProductId: null,
  actions: {},
  overviewNonce: 0,
  inFlight: false,

  setSession: (sessionId, products, suggestions) => set({ sessionId, products, suggestions }),
  push: (m) => set((s) => ({ messages: [...s.messages, m] })),
  patchAssistant: (id, fn) =>
    set((s) => ({
      messages: s.messages.map((m) => (m.id === id && m.role === "assistant" ? { ...m, ...fn(m) } : m)),
    })),
  setSuggestions: (suggestions) => set({ suggestions }),
  setFocus: (focusProductId) => set({ focusProductId }),
  setAction: (id, st) => set((s) => ({ actions: { ...s.actions, [id]: st } })),
  bumpOverview: () => set((s) => ({ overviewNonce: s.overviewNonce + 1 })),
  setInFlight: (inFlight) => set({ inFlight }),
  reset: () =>
    set({
      sessionId: null,
      products: [],
      messages: [],
      suggestions: [],
      focusProductId: null,
      actions: {},
      inFlight: false,
    }),
}));

let counter = 0;
export const uid = (p: string) => `${p}_${Date.now().toString(36)}_${(counter++).toString(36)}`;
