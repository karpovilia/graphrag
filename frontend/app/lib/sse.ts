// Minimal SSE consumer for the /api/reason/stream endpoint.
//
// Phase 6.4. EventSource doesn't support POST bodies (it does GET only),
// so we hand-roll a fetch + stream-reader that parses
// `event: <type>\ndata: <json>\n\n` frames. Caller passes per-event
// handlers; the function returns a cancel handle.

export type SSEHandlers = {
  onEvent: (event: string, data: unknown) => void;
  onError?: (err: unknown) => void;
  onClose?: () => void;
};

export type SSEHandle = {
  cancel: () => void;
  done: Promise<void>;
};

export function streamSSE(
  url: string,
  init: RequestInit,
  handlers: SSEHandlers,
): SSEHandle {
  const ctrl = new AbortController();
  const headers = new Headers(init.headers || {});
  headers.set("accept", "text/event-stream");
  if (init.body && !headers.has("content-type")) {
    headers.set("content-type", "application/json");
  }

  const done = (async () => {
    try {
      const resp = await fetch(url, {
        ...init,
        headers,
        signal: ctrl.signal,
      });
      if (!resp.ok) {
        throw new Error(`SSE request failed: ${resp.status}`);
      }
      if (!resp.body) {
        throw new Error("SSE response has no body");
      }
      const reader = resp.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let buffer = "";
      while (true) {
        const { value, done: doneStream } = await reader.read();
        if (doneStream) break;
        buffer += decoder.decode(value, { stream: true });
        const frames = buffer.split("\n\n");
        buffer = frames.pop() ?? "";
        for (const frame of frames) {
          dispatchFrame(frame, handlers);
        }
      }
      if (buffer.trim()) dispatchFrame(buffer, handlers);
    } catch (e) {
      if ((e as { name?: string }).name === "AbortError") return;
      handlers.onError?.(e);
    } finally {
      handlers.onClose?.();
    }
  })();

  return { cancel: () => ctrl.abort(), done };
}

function dispatchFrame(frame: string, handlers: SSEHandlers) {
  const lines = frame.split("\n");
  let event = "message";
  const dataLines: string[] = [];
  for (const line of lines) {
    if (!line) continue;
    if (line.startsWith(":")) continue; // SSE comment
    if (line.startsWith("event:")) {
      event = line.slice(6).trim();
    } else if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trim());
    }
  }
  const raw = dataLines.join("\n");
  let data: unknown = raw;
  if (raw) {
    try {
      data = JSON.parse(raw);
    } catch {
      // not JSON — pass the raw string
    }
  }
  handlers.onEvent(event, data);
}
