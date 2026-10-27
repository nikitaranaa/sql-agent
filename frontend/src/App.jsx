import { useEffect, useMemo, useRef, useState } from "react";
import ChatPanel from "./components/ChatPanel.jsx";
import Header from "./components/Header.jsx";
import ResultPanel from "./components/ResultPanel.jsx";
import Sidebar from "./components/Sidebar.jsx";
import { deleteHistory, fetchSchema, sendMessage } from "./lib/api.js";
import { loadPref, loadSessions, newSession, savePref, saveSessions } from "./lib/storage.js";

const FALLBACK_EXAMPLES = [
  "Show all employees hired after January 2024",
  "Top 5 customers by total revenue",
  "Which products have never been ordered?",
];

export default function App() {
  const [sessions, setSessions] = useState(loadSessions);
  const [activeId, setActiveId] = useState(() => sessions[0].id);
  const [selectedId, setSelectedId] = useState(null);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [steps, setSteps] = useState([]);
  const [error, setError] = useState("");
  const [schema, setSchema] = useState(null);
  const [schemaError, setSchemaError] = useState("");
  const [dialect, setDialect] = useState(() => loadPref("dialect", "sqlite"));
  const [execute, setExecute] = useState(() => loadPref("execute", true));
  const [dark, setDark] = useState(() => document.documentElement.classList.contains("dark"));
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [detailsOpen, setDetailsOpen] = useState(false); // mobile: show details instead of chat
  const inputRef = useRef(null);
  const abortRef = useRef(null);

  const active = sessions.find((s) => s.id === activeId) || sessions[0];
  const messages = active.messages;

  useEffect(() => { saveSessions(sessions); }, [sessions]);
  useEffect(() => { savePref("dialect", dialect); }, [dialect]);
  useEffect(() => { savePref("execute", execute); }, [execute]);
  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    try { localStorage.setItem("theme", dark ? "dark" : "light"); } catch { /* ignore */ }
  }, [dark]);
  useEffect(() => {
    fetchSchema().then(setSchema).catch((e) => setSchemaError(`Couldn't load schema: ${e.message}`));
  }, []);

  // Show the latest SQL answer of the active conversation by default.
  const selectedResponse = useMemo(() => {
    const pick = messages.find((m) => m.id === selectedId) ||
      [...messages].reverse().find((m) => m.role === "assistant" && m.response?.type === "sql");
    return pick?.response?.type === "sql" ? pick.response : null;
  }, [messages, selectedId]);

  const updateActive = (fn) =>
    setSessions((all) => all.map((s) => (s.id === activeId ? fn(s) : s)));

  async function send(text) {
    const message = text.trim();
    if (!message || loading) return;
    setInput("");
    setError("");
    setSteps([]);
    setLoading(true);
    const userMsg = { id: crypto.randomUUID(), role: "user", content: message };
    updateActive((s) => ({
      ...s,
      title: s.messages.length ? s.title : message.slice(0, 48),
      messages: [...s.messages, userMsg],
    }));

    abortRef.current = new AbortController();
    try {
      const response = await sendMessage(
        { session_id: active.id, message, dialect, execute },
        { onStep: (s) => setSteps((prev) => [...prev, s]), signal: abortRef.current.signal },
      );
      const botMsg = { id: crypto.randomUUID(), role: "assistant", content: response.message, response };
      updateActive((s) => ({ ...s, messages: [...s.messages, botMsg] }));
      if (response.type === "sql") setSelectedId(botMsg.id);
    } catch (e) {
      if (e.name !== "AbortError") setError(e.message || "Request failed.");
    } finally {
      setLoading(false);
      inputRef.current?.focus();
    }
  }

  function startNewChat() {
    abortRef.current?.abort();
    const s = newSession();
    setSessions((all) => [s, ...all]);
    setActiveId(s.id);
    setSelectedId(null);
    setError("");
    setSidebarOpen(false);
  }

  function selectSession(id) {
    abortRef.current?.abort();
    setActiveId(id);
    setSelectedId(null);
    setError("");
    setSidebarOpen(false);
  }

  function deleteSession(id) {
    deleteHistory(id);
    setSessions((all) => {
      const rest = all.filter((s) => s.id !== id);
      const next = rest.length ? rest : [newSession()];
      if (id === activeId) setActiveId(next[0].id);
      return next;
    });
  }

  function insertText(text) {
    setInput((v) => (v ? `${v} ${text}` : text));
    setSidebarOpen(false);
    inputRef.current?.focus();
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
        />
        {/* Mobile: switch between chat and details. Desktop: side by side. */}
        <div className="flex border-b border-slate-200 text-sm md:hidden dark:border-slate-800">
          {["Chat", "Details"].map((tab, i) => (
            <button
              key={tab}
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
              error={error}
              input={input}
              onInput={setInput}
              onSend={send}
              examples={schema?.examples || FALLBACK_EXAMPLES}
              selectedId={selectedId}
              onSelect={(id) => { setSelectedId(id); setDetailsOpen(true); }}
              inputRef={inputRef}
            />
          </div>
          <div className={`min-h-0 overflow-y-auto scrollbar-thin md:block md:flex-1 ${detailsOpen ? "block w-full" : "hidden"}`}>
            <ResultPanel response={selectedResponse} dark={dark} />
          </div>
        </main>
      </div>
    </div>
  );
}
