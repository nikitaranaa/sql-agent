export const API_URL = (import.meta.env.VITE_API_URL || "http://localhost:8000").replace(/\/$/, "");

async function asJson(res) {
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body.detail) detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch { /* not JSON */ }
    throw new Error(detail);
  }
  return res.json();
}

export const fetchSchema = () => fetch(`${API_URL}/schema`).then(asJson);
export const fetchHistory = (sessionId) => fetch(`${API_URL}/history/${sessionId}`).then(asJson);
export const deleteHistory = (sessionId) =>
  fetch(`${API_URL}/history/${sessionId}`, { method: "DELETE" }).catch(() => {});

/**
 * Send one message. Streams graph steps through `onStep` via server-sent events,
 * and falls back to the plain JSON endpoint if streaming isn't available.
 */
export async function sendMessage(body, { onStep, signal } = {}) {
  let res;
  try {
    res = await fetch(`${API_URL}/chat/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal,
    });
  } catch (err) {
    if (err.name === "AbortError") throw err;
    throw new Error(`Can't reach the API at ${API_URL}. Is the backend running? (It may take ~1 minute to wake up on a free host.)`);
  }
  if (!res.ok || !res.body) {
    const fallback = await fetch(`${API_URL}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal,
    });
    return asJson(fallback);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let result = null;
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let idx;
    while ((idx = buffer.indexOf("\n\n")) !== -1) {
      const block = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      const event = /^event: (.*)$/m.exec(block)?.[1];
      const data = /^data: (.*)$/m.exec(block)?.[1];
      if (!event || !data) continue;
      const payload = JSON.parse(data);
      if (event === "step") onStep?.(payload);
      if (event === "result") result = payload;
    }
  }
  if (!result) throw new Error("The server closed the connection without a result.");
  return result;
}
