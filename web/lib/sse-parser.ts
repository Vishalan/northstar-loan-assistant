// Minimal text/event-stream parser (WHATWG semantics for `event:` / `data:` fields).
// Pure and dependency-free so it can be unit-tested with `node --test`.

export type SSEFrame = { event: string; data: string };

export function createSSEParser(onFrame: (frame: SSEFrame) => void) {
  let buffer = "";
  let event = "";
  let data: string[] = [];

  function dispatch() {
    if (data.length > 0) onFrame({ event: event || "message", data: data.join("\n") });
    event = "";
    data = [];
  }

  function line(l: string) {
    if (l === "") return dispatch();
    if (l.startsWith(":")) return; // comment / heartbeat
    const idx = l.indexOf(":");
    const field = idx === -1 ? l : l.slice(0, idx);
    let value = idx === -1 ? "" : l.slice(idx + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "event") event = value;
    else if (field === "data") data.push(value);
    // `id` and `retry` are ignored: turns are not resumable.
  }

  return {
    feed(chunk: string) {
      let text = buffer + chunk;
      // A trailing "\r" may be the first half of a "\r\n" split across chunks — hold it back.
      let hold = "";
      if (text.endsWith("\r")) {
        hold = "\r";
        text = text.slice(0, -1);
      }
      // Split on any line terminator; keep the trailing partial line in the buffer.
      const parts = text.split(/\r\n|\r|\n/);
      buffer = (parts.pop() ?? "") + hold;
      for (const p of parts) line(p);
    },
    end() {
      if (buffer) line(buffer);
      buffer = "";
      dispatch();
    },
  };
}
