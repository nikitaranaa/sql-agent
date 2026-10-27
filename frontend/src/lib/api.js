export const API_URL = (import.meta.env.VITE_API_URL || "http://localhost:8000").replace(/\/$/, "");

const AUTH_KEY = "sql-agent:auth:v1";

// --- auth token ---------------------------------------------------------------------------
export function loadAuth() {
  try {
    const a = JSON.parse(localStorage.getItem(AUTH_KEY) || "null");
    return a?.token && a?.username ? a : null;
  } catch {
    return null;
  }
}

export function saveAuth(auth) {
  try {
    if (auth) localStorage.setItem(AUTH_KEY, JSON.stringify(auth));
    else localStorage.removeItem(AUTH_KEY);
  } catch { /* storage blocked: the sign-in lasts for this tab only */ }
}

/** Thrown when the server rejects the saved sign-in, so the app can sign the user out. */
export class AuthError extends Error {}

function headers(json = true) {
  const h = json ? { "Content-Type": "application/json" } : {};
  const auth = loadAuth();
  if (auth) h.Authorization = `Bearer ${auth.token}`;
  return h;
}

async function errorFrom(res) {
  let detail = `${res.status} ${res.statusText}`;
  try {
    const body = await res.json();
    if (body.detail) detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
  } catch { /* not JSON */ }
  return res.status === 401 ? new AuthError(detail) : new Error(detail);
}

async function asJson(res) {
  if (!res.ok) throw await errorFrom(res);
  return res.json();
}

function unreachable(err) {
  if (err.name === "AbortError") return err;
  return new Error(`Can't reach the API at ${API_URL}. Is the backend running? (On free hosting it can take about a minute to wake up.)`);
}

const post = (path, body, opts = {}) =>
  fetch(`${API_URL}${path}`, { method: "POST", headers: headers(), body: JSON.stringify(body), ...opts });

// --- simple endpoints --------------------------------------------------------------------------
export const ping = (signal) => fetch(`${API_URL}/health`, { signal }).then((r) => r.ok);
export const fetchSchema = () => fetch(`${API_URL}/schema`).then(asJson);
export const deleteHistory = (sessionId) =>
  fetch(`${API_URL}/history/${sessionId}`, { method: "DELETE", headers: headers(false) }).catch(() => {});

export const runSql = (body) => post("/run", body).then(asJson, (e) => { throw unreachable(e); });
export const sendFeedback = (body) => post("/feedback", body).then(asJson).catch(() => null);

export const register = (username, password) => post("/auth/register", { username, password }).then(asJson);
export const login = (username, password) => post("/auth/login", { username, password }).then(asJson);

export const listConversations = () =>
  fetch(`${API_URL}/conversations`, { headers: headers(false) }).then(asJson);
export const saveConversation = (c) =>
  fetch(`${API_URL}/conversations/${c.id}`, {
    method: "PUT", headers: headers(), body: JSON.stringify({ title: c.title, messages: c.messages }),
  }).then(asJson);
export const deleteConversation = (id) =>
  fetch(`${API_URL}/conversations/${id}`, { method: "DELETE", headers: headers(false) }).then(asJson);

/** Full results as a CSV blob (beyond the 100-row preview). */
export async function exportCsv(sql) {
  const res = await post("/export", { sql });
  if (!res.ok) throw await errorFrom(res);
  return { blob: await res.blob(), truncated: res.headers.get("X-Truncated") === "true" };
}

/**
 * Send one message. Streams graph steps through `onStep` and explanation text through
 * `onToken` (server-sent events), and falls back to the plain JSON endpoint if needed.
 */
export async function sendMessage(body, { onStep, onToken, signal } = {}) {
  let res;
  try {
    res = await post("/chat/stream", body, { signal });
  } catch (err) {
    throw unreachable(err);
  }
  if (res.status === 401 || res.status === 429 || res.status === 422) throw await errorFrom(res);
  if (!res.ok || !res.body) return asJson(await post("/chat", body, { signal }));

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let result = null;
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
    let idx;
    while ((idx = buffer.indexOf("\n\n")) !== -1) {
      const block = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      const event = /^event: (.*)$/m.exec(block)?.[1];
      const data = /^data: (.*)$/m.exec(block)?.[1];
      if (!event || !data) continue;
      const payload = JSON.parse(data);
      if (event === "step") onStep?.(payload);
      if (event === "token") onToken?.(payload.text);
      if (event === "result") result = payload;
    }
  }
  if (!result) throw new Error("The server closed the connection without a result.");
  return result;
}
