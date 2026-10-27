import { useEffect, useMemo, useRef, useState } from "react";
import AuthDialog from "./components/AuthDialog.jsx";
import ChatPanel from "./components/ChatPanel.jsx";
import Header from "./components/Header.jsx";
import ResultPanel from "./components/ResultPanel.jsx";
import Sidebar from "./components/Sidebar.jsx";
import {
  AuthError, deleteConversation, deleteHistory, fetchSchema, listConversations, loadAuth, ping,
  runSql, saveAuth, saveConversation, sendFeedback, sendMessage,
} from "./lib/api.js";
import { loadPref, loadSessions, newSession, savePref, saveSessions } from "./lib/storage.js";

const FALLBACK_EXAMPLES = [
  "Show all employees hired after January 2024",
  "Top 5 customers by total revenue",
  "Which products have never been ordered?",
];

const isMobile = () => window.matchMedia?.("(max-width: 767px)").matches;
const syncKey = (s) => JSON.stringify([s.title, s.messages]);

export default function App() {
  const [sessions, setSessions] = useState(loadSessions);
  const [activeId, setActiveId] = useState(() => sessions[0].id);
  const [selectedId, setSelectedId] = useState(null);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [steps, setSteps] = useState([]);
  const [streamText, setStreamText] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [waking, setWaking] = useState(false);
  const [schema, setSchema] = useState(null);
  const [schemaError, setSchemaError] = useState("");
  const [dialect, setDialect] = useState(() => loadPref("dialect", "sqlite"));
  const [execute, setExecute] = useState(() => loadPref("execute", true));
  const [dark, setDark] = useState(() => document.documentElement.classList.contains("dark"));
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [detailsOpen, setDetailsOpen] = useState(false); // mobile: show details instead of chat
  const [auth, setAuth] = useState(loadAuth);
  const [authOpen, setAuthOpen] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const inputRef = useRef(null);
  const abortRef = useRef(null);
  const synced = useRef(new Map());   // conversation id -> what the server last saw

  const active = sessions.find((s) => s.id === activeId) || sessions[0];
  const messages = active.messages;

  useEffect(() => { saveSessions(sessions); }, [sessions]);
  useEffect(() => { savePref("dialect", dialect); }, [dialect]);
  useEffect(() => { savePref("execute", execute); }, [execute]);
  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    try { localStorage.setItem("theme", dark ? "dark" : "light"); } catch { /* ignore */ }
  }, [dark]);

  // Wake the backend as soon as the page opens. If it's slow, the free host is asleep: say so.
  useEffect(() => {
    const slow = setTimeout(() => setWaking(true), 2500);
    const done = () => { clearTimeout(slow); setWaking(false); };
    ping().then(done, done);
    fetchSchema().then(setSchema).catch((e) => setSchemaError(`Couldn't load schema: ${e.message}`));
    return () => clearTimeout(slow);
  }, []);

  // --- account sync -------------------------------------------------------------------------
  function signOut(message = "") {
    saveAuth(null);
    setAuth(null);
    synced.current.clear();
    if (message) setError(message);
  }

  function handleError(e) {
    if (e instanceof AuthError) signOut("Your sign-in expired. Please sign in again; your chats are still here.");
    else if (e.name !== "AbortError") setError(e.message || "Request failed.");
  }

  // On sign-in (and on load when already signed in): merge server and local conversations.
  useEffect(() => {
    if (!auth) return;
    let cancelled = false;
    setSyncing(true);
    listConversations()
      .then((remote) => {
        if (cancelled) return;
        remote.forEach((c) => synced.current.set(c.id, syncKey(c)));
        setSessions((local) => {
          const ids = new Set(remote.map((c) => c.id));
          const onlyLocal = local.filter((s) => !ids.has(s.id) && s.messages.length);
          const merged = [...onlyLocal, ...remote.map((c) => ({ id: c.id, title: c.title, messages: c.messages }))];
          return merged.length ? merged : [newSession()];
        });
      })
      .catch(handleError)
      .finally(() => !cancelled && setSyncing(false));
    return () => { cancelled = true; };
  }, [auth]);

  // Push changed conversations to the account, debounced.
  useEffect(() => {
    if (!auth) return;
    const changed = sessions.filter((s) => s.messages.length && synced.current.get(s.id) !== syncKey(s));
    if (!changed.length) return;
    const timer = setTimeout(async () => {
      setSyncing(true);
      try {
        for (const s of changed) {
          await saveConversation(s);
          synced.current.set(s.id, syncKey(s));
        }
      } catch (e) {
        handleError(e);
      } finally {
        setSyncing(false);
      }
    }, 800);
    return () => clearTimeout(timer);
  }, [sessions, auth]);

  // Keep the selected answer in sync if the active chat changes under it (e.g. after a merge).
  useEffect(() => {
    if (!sessions.some((s) => s.id === activeId)) setActiveId(sessions[0].id);
  }, [sessions, activeId]);

  // Show the latest SQL answer of the active conversation by default.
  const selectedMsg = useMemo(() => {
    const pick = messages.find((m) => m.id === selectedId) ||
      [...messages].reverse().find((m) => m.role === "assistant" && m.response?.type === "sql");
    return pick?.response?.type === "sql" ? pick : null;
  }, [messages, selectedId]);

  const updateSession = (id, fn) => setSessions((all) => all.map((s) => (s.id === id ? fn(s) : s)));
  const updateMessage = (msgId, patch) =>
    updateSession(active.id, (s) => ({
      ...s, messages: s.messages.map((m) => (m.id === msgId ? { ...m, ...patch(m) } : m)),
    }));

  // --- chat -------------------------------------------------------------------------------------
  async function send(text) {
    const message = text.trim();
    if (!message || loading) return;
    const sessionId = active.id;
    setInput("");
    setError("");
    setNotice("");
    setSteps([]);
    setStreamText("");
    setLoading(true);
    // The browser's copy of the last successful query, so follow-ups still work if the
    // server forgot this conversation (restart, or a sleeping free-tier host).
    const lastSqlIdx = messages.findLastIndex((m) => m.role === "assistant" && m.response?.type === "sql");
    const context = lastSqlIdx === -1 ? {} : {
      previous_sql: messages[lastSqlIdx].response.sql_sqlite,
      previous_question: messages.slice(0, lastSqlIdx).findLast((m) => m.role === "user")?.content,
    };
    const userMsg = { id: crypto.randomUUID(), role: "user", content: message };
    updateSession(sessionId, (s) => ({
      ...s,
      title: s.messages.length ? s.title : message.slice(0, 48),
      messages: [...s.messages, userMsg],
    }));

    abortRef.current = new AbortController();
    try {
      const response = await sendMessage(
        { session_id: sessionId, message, dialect, execute, ...context },
        {
          onStep: (s) => setSteps((prev) => [...prev, s]),
          onToken: (t) => setStreamText((prev) => prev + t),
          signal: abortRef.current.signal,
        },
      );
      const botMsg = { id: crypto.randomUUID(), role: "assistant", content: response.message, response, question: message };
      updateSession(sessionId, (s) => ({ ...s, messages: [...s.messages, botMsg] }));
      if (response.type === "sql") {
        setSelectedId(botMsg.id);
        if (isMobile()) setDetailsOpen(true);
      }
    } catch (e) {
      handleError(e);
    } finally {
      setLoading(false);
      setStreamText("");
      inputRef.current?.focus();
    }
  }

  function stopGenerating() {
    abortRef.current?.abort();
    setNotice("Stopped. Edit your question or ask again.");
  }

  function giveFeedback(msg, rating) {
    updateMessage(msg.id, () => ({ rating }));
    sendFeedback({ session_id: active.id, question: msg.question || "", sql: msg.response?.sql_sqlite || "", rating });
  }

  async function runEdited(sql) {
    const msg = selectedMsg;
    try {
      const out = await runSql({ sql, dialect: msg.response.dialect, question: msg.question, session_id: active.id });
      if (out.ok) {
        updateMessage(msg.id, (m) => ({
          content: out.explanation.summary,
          response: { ...m.response, ...out, edited: true, retries: 0 },
        }));
      }
      return out;
    } catch (e) {
      handleError(e);
      return { ok: false, errors: [e.message] };
    }
  }

  // --- conversations -------------------------------------------------------------------------
  function startNewChat() {
    abortRef.current?.abort();
    const s = newSession();
    setSessions((all) => [s, ...all]);
    setActiveId(s.id);
    setSelectedId(null);
    setError("");
    setNotice("");
    setDetailsOpen(false);
    setSidebarOpen(false);
  }

  function selectSession(id) {
    abortRef.current?.abort();
    setActiveId(id);
    setSelectedId(null);
    setError("");
    setNotice("");
    setDetailsOpen(false);
    setSidebarOpen(false);
  }

  function deleteSession(id) {
    if (auth) deleteConversation(id).catch(handleError);
    else deleteHistory(id);
    synced.current.delete(id);
    setSessions((all) => {
      const rest = all.filter((s) => s.id !== id);
      return rest.length ? rest : [newSession()];
    });
  }

  function insertText(text) {
    setInput((v) => (v ? `${v} ${text}` : text));
    setSidebarOpen(false);
    inputRef.current?.focus();
  }

  function onSignedIn(a) {
    saveAuth(a);
    setAuth(a);
    setAuthOpen(false);
    setError("");
  }

  function onSignOut() {
    signOut();
    // Don't leave this account's chats on a shared device.
    const s = newSession();
    setSessions([s]);
    setActiveId(s.id);
    setSelectedId(null);
  }

  return (
    <div className="flex h-full">
      <Sidebar
        open={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
        sessions={sessions}
        activeId={active.id}
        onSelect={selectSession}
        onNew={startNewChat}
        onDelete={deleteSession}
        onRename={(id, title) => updateSession(id, (s) => ({ ...s, title }))}
        schema={schema}
        schemaError={schemaError}
        onInsert={insertText}
      />
      <div className="flex min-w-0 flex-1 flex-col">
        <Header
          dialect={dialect}
          onDialect={setDialect}
          execute={execute}
          onExecute={setExecute}
          dark={dark}
          onToggleDark={() => setDark(!dark)}
          onMenu={() => setSidebarOpen(true)}
          auth={auth}
          syncing={syncing}
          onSignIn={() => setAuthOpen(true)}
          onSignOut={onSignOut}
        />
        {/* Mobile: switch between chat and details. Desktop: side by side. */}
        <div className="flex border-b border-slate-200 text-sm md:hidden dark:border-slate-800" role="tablist">
          {["Chat", "Details"].map((tab, i) => (
            <button
              key={tab}
              role="tab"
              aria-selected={detailsOpen === (i === 1)}
              onClick={() => setDetailsOpen(i === 1)}
              className={`flex-1 py-2 ${detailsOpen === (i === 1) ? "border-b-2 border-indigo-600 font-medium text-indigo-600" : "text-slate-500"}`}
            >
              {tab}
            </button>
          ))}
        </div>
        <main className="flex min-h-0 flex-1">
          <div className={`min-h-0 flex-col md:flex md:w-[45%] md:border-r md:border-slate-200 dark:md:border-slate-800 ${detailsOpen ? "hidden" : "flex w-full"}`}>
            <ChatPanel
              messages={messages}
              loading={loading}
              steps={steps}
              streamText={streamText}
              error={error}
              notice={notice}
              waking={waking}
              input={input}
              onInput={setInput}
              onSend={send}
              onStop={stopGenerating}
              examples={schema?.examples || FALLBACK_EXAMPLES}
              selectedId={selectedMsg?.id}
              onSelect={(id) => { setSelectedId(id); setDetailsOpen(true); }}
              onRetry={(msg) => send(msg.question)}
              onFeedback={giveFeedback}
              inputRef={inputRef}
            />
          </div>
          <div className={`min-h-0 overflow-y-auto scrollbar-thin md:block md:flex-1 ${detailsOpen ? "block w-full" : "hidden"}`}>
            <ResultPanel key={selectedMsg?.id} response={selectedMsg?.response} dark={dark} onRun={runEdited} />
          </div>
        </main>
      </div>
      <AuthDialog open={authOpen} onClose={() => setAuthOpen(false)} onSignedIn={onSignedIn} />
    </div>
  );
}
