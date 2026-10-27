// Conversations are kept in localStorage so history survives a page reload.
// The backend keeps its own copy (LangGraph checkpointer) keyed by the same session id.
const KEY = "sql-agent:sessions:v1";

export function newSession() {
  return { id: crypto.randomUUID(), title: "New chat", messages: [], createdAt: Date.now() };
}

export function loadSessions() {
  try {
    const sessions = JSON.parse(localStorage.getItem(KEY) || "[]");
    return Array.isArray(sessions) && sessions.length ? sessions : [newSession()];
  } catch {
    return [newSession()];
  }
}

export function saveSessions(sessions) {
  try {
    localStorage.setItem(KEY, JSON.stringify(sessions.slice(0, 30)));
  } catch { /* storage full or blocked: history just won't persist */ }
}

export function loadPref(key, fallback) {
  try {
    const v = localStorage.getItem(key);
    return v === null ? fallback : JSON.parse(v);
  } catch {
    return fallback;
  }
}

export function savePref(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* ignore */ }
}
