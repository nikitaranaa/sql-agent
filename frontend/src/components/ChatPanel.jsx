import { useEffect, useRef } from "react";
import { IconSend } from "./Icons.jsx";

const TYPE_STYLES = {
  sql: "border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900",
  refusal: "border-amber-200 bg-amber-50 dark:border-amber-500/30 dark:bg-amber-500/10",
  clarification: "border-sky-200 bg-sky-50 dark:border-sky-500/30 dark:bg-sky-500/10",
  error: "border-rose-200 bg-rose-50 dark:border-rose-500/30 dark:bg-rose-500/10",
};
const TYPE_LABELS = {
  sql: null,
  refusal: "Declined",
  clarification: "Needs clarification",
  error: "Error",
};
const INTENT_LABELS = {
  generate: "Generated",
  followup: "Follow-up",
  optimize: "Optimized",
  debug: "Debugged",
  explain: "Explained",
};

function AssistantMessage({ msg, selected, onSelect }) {
  const r = msg.response || { type: "error" };
  const clickable = r.type === "sql";
  return (
    <div
      role={clickable ? "button" : undefined}
      tabIndex={clickable ? 0 : undefined}
      onClick={clickable ? onSelect : undefined}
      onKeyDown={clickable ? (e) => e.key === "Enter" && onSelect() : undefined}
      className={`max-w-[90%] rounded-2xl rounded-tl-sm border px-3.5 py-2.5 text-sm shadow-sm transition ${TYPE_STYLES[r.type] || TYPE_STYLES.error}
        ${clickable ? "cursor-pointer hover:border-indigo-300" : ""} ${selected ? "ring-2 ring-indigo-500/60" : ""}`}
    >
      {TYPE_LABELS[r.type] && (
        <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide opacity-70">{TYPE_LABELS[r.type]}</div>
      )}
      {r.type === "sql" && (
        <div className="mb-1 flex flex-wrap items-center gap-1.5 text-[11px]">
          <span className="rounded bg-indigo-100 px-1.5 py-0.5 font-medium text-indigo-700 dark:bg-indigo-500/20 dark:text-indigo-300">
            {INTENT_LABELS[r.intent] || "SQL"}
          </span>
          {r.results && <span className="text-slate-500">{r.results.row_count}{r.results.truncated ? "+" : ""} rows</span>}
          {r.retries > 0 && <span className="text-slate-500">· self-corrected {r.retries}×</span>}
          {r.warnings?.length > 0 && <span className="text-amber-600">· {r.warnings.length} warning(s)</span>}
        </div>
      )}
      <p className="whitespace-pre-wrap">{msg.content || "Done."}</p>
      {r.type === "sql" && r.sql && (
        <pre className="mt-2 max-h-28 overflow-hidden rounded-lg bg-slate-100 p-2 font-mono text-xs text-slate-700 dark:bg-slate-800 dark:text-slate-200">
          {r.sql}
        </pre>
      )}
      {r.type === "error" && r.errors?.length > 0 && (
        <ul className="mt-1 list-disc pl-5 text-xs opacity-80">
          {r.errors.slice(0, 4).map((e, i) => <li key={i}>{e}</li>)}
        </ul>
      )}
      {clickable && <div className="mt-1.5 text-[11px] text-indigo-600 dark:text-indigo-400">View details →</div>}
    </div>
  );
}

function LoadingSteps({ steps }) {
  return (
    <div className="flex max-w-[90%] items-start gap-3 rounded-2xl rounded-tl-sm border border-slate-200 bg-white px-3.5 py-2.5 text-sm shadow-sm dark:border-slate-800 dark:bg-slate-900" aria-live="polite">
      <span className="mt-1 flex gap-1">
        {[0, 1, 2].map((i) => (
          <span key={i} className="h-1.5 w-1.5 animate-bounce rounded-full bg-indigo-500" style={{ animationDelay: `${i * 120}ms` }} />
        ))}
      </span>
      <ol className="space-y-0.5 text-xs text-slate-500 dark:text-slate-400">
        {steps.length === 0 && <li>Thinking…</li>}
        {steps.map((s, i) => (
          <li key={i} className={i === steps.length - 1 ? "font-medium text-slate-700 dark:text-slate-200" : ""}>
            {i === steps.length - 1 ? "▸" : "✓"} {s.label}
          </li>
        ))}
      </ol>
    </div>
  );
}

export default function ChatPanel({
  messages, loading, steps, error, input, onInput, onSend, examples, selectedId, onSelect, inputRef,
}) {
  const bottom = useRef(null);
  useEffect(() => bottom.current?.scrollIntoView({ behavior: "smooth" }), [messages.length, loading, steps.length]);

  const submit = (e) => {
    e.preventDefault();
    onSend(input);
  };

  return (
    <section className="flex min-h-0 flex-1 flex-col">
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-4 scrollbar-thin">
        {messages.length === 0 && (
          <div className="mx-auto mt-6 max-w-lg text-center">
            <h2 className="text-lg font-semibold">What would you like to know?</h2>
            <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
              Ask a question about the data, or paste SQL to explain, optimize or debug.
              Follow-ups like “only those from California” refine the last query.
            </p>
            <div className="mt-5 flex flex-wrap justify-center gap-2">
              {examples.map((ex) => (
                <button key={ex} className="chip" onClick={() => onSend(ex)}>{ex}</button>
              ))}
            </div>
          </div>
        )}

        {messages.map((m) =>
          m.role === "user" ? (
            <div key={m.id} className="flex justify-end">
              <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-tr-sm bg-indigo-600 px-3.5 py-2 text-sm text-white shadow-sm">
                {m.content}
              </div>
            </div>
          ) : (
            <div key={m.id} className="flex">
              <AssistantMessage msg={m} selected={m.id === selectedId} onSelect={() => onSelect(m.id)} />
            </div>
          ),
        )}
        {loading && <LoadingSteps steps={steps} />}
        {error && (
          <div role="alert" className="rounded-xl border border-rose-200 bg-rose-50 px-3.5 py-2.5 text-sm text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-300">
            {error}
          </div>
        )}
        <div ref={bottom} />
      </div>

      <form onSubmit={submit} className="border-t border-slate-200 p-3 dark:border-slate-800">
        <div className="flex items-end gap-2 rounded-xl border border-slate-200 bg-white p-2 focus-within:border-indigo-400 dark:border-slate-700 dark:bg-slate-900">
          <textarea
            ref={inputRef}
            rows={Math.min(6, Math.max(1, input.split("\n").length))}
            value={input}
            onChange={(e) => onInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) submit(e);
            }}
            placeholder="e.g. Top 5 customers by revenue — or paste a SQL query"
            className="max-h-40 flex-1 resize-none bg-transparent px-1.5 py-1 text-sm outline-none placeholder:text-slate-400"
            maxLength={4000}
            aria-label="Message"
          />
          <button type="submit" className="btn-primary" disabled={loading || !input.trim()} aria-label="Send">
            <IconSend />
          </button>
        </div>
        <p className="mt-1.5 text-center text-[11px] text-slate-400">
          Enter to send · Shift+Enter for a new line · queries are validated and run read-only
        </p>
      </form>
    </section>
  );
}
