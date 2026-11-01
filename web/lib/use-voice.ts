"use client";

import { useEffect, useState, useSyncExternalStore } from "react";
import { api } from "./api";
import { uid, useChat } from "./chat-store";
import { turnEngine } from "./turn-engine";
import { VoiceController, type VoiceSnapshot } from "./voice-controller";

let singleton: VoiceController | null = null;

function getController(): VoiceController {
  if (singleton) return singleton;
  singleton = new VoiceController({
    send(text) {
      void turnEngine.send(text, "voice");
      const msgs = useChat.getState().messages;
      const last = msgs[msgs.length - 1];
      return last && last.role === "assistant" && last.state === "streaming" ? last.id : null;
    },
    interrupt(messageId, spokenText) {
      const store = useChat.getState();
      const msg = store.messages.find((m) => m.id === messageId);
      if (!msg || msg.role !== "assistant") return;
      if (msg.state === "streaming") {
        turnEngine.interrupt(spokenText);
      } else {
        // Turn already finished server-side but we were still reading it out.
        if (msg.turnId) api.cancelTurn(msg.turnId, spokenText).catch(() => {});
        store.patchAssistant(messageId, () => ({ state: "interrupted" }));
      }
    },
    subscribe: (fn) => turnEngine.subscribe(fn),
    prefetch(text) {
      const sid = useChat.getState().sessionId;
      if (sid && text.trim()) api.prefetch(sid, text).catch(() => {});
    },
    metric(name, ms, meta) {
      void api.clientMetric(name, ms, meta);
    },
    isActionPending: (id) => (useChat.getState().actions[id]?.phase ?? "pending") === "pending" ||
      useChat.getState().actions[id]?.phase === "otp_invalid",
    confirm: (p, otp) => turnEngine.confirmAction(p, { otp, via: "voice" }),
    noteUser(text) {
      useChat.getState().push({ role: "user", id: uid("u"), text, channel: "voice", at: Date.now() });
    },
  });
  return singleton;
}

const SERVER_SNAPSHOT: VoiceSnapshot = {
  state: "idle",
  active: false,
  interim: "",
  error: null,
  notice: null,
  supported: false,
  stream: null,
  voiceName: null,
  sttEngine: null,
};

export function useVoice() {
  const [controller] = useState(() => (typeof window === "undefined" ? null : getController()));
  const snap = useSyncExternalStore(
    controller?.subscribe ?? (() => () => {}),
    controller?.getSnapshot ?? (() => SERVER_SNAPSHOT),
    () => SERVER_SNAPSHOT,
  );
  useEffect(() => () => controller?.stop(), [controller]);
  return {
    ...snap,
    start: () => controller?.start(),
    stop: () => controller?.stop(),
    sendText: (text: string) => controller?.sendText(text),
  };
}
