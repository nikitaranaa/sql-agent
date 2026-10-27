import { useEffect, useRef } from "react";
import { IconRefresh, IconSend, IconStop, IconThumbDown, IconThumbUp } from "./Icons.jsx";

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

const stop = (fn) => (e) => {
  e.stopPropagation();
  fn();
};

function ResultPreview({ results }) {
  if (!results?.row_count) return null;
  const cols = results.columns.slice(0, 4);
  return (
    <div className="mt-2 overflow-hidden rounded-lg border border-slate-200 dark:border-slate-700">
      <table className="w-full table-fixed text-left text-[11px]">
        <thead className="bg-slate-50 text-slate-500 dark:bg-slate-800 dark:text-slate-400">
          <tr>{cols.map((c, i) => <th key={i} className="truncate px-2 py-1 font-medium">{c}</th>)}</tr>
        </thead>
        <tbody>
          {results.rows.slice(0, 3).map((row, i) => (
            <tr key={i} className="border-t border-slate-100 dark:border-slate-800">
              {cols.map((_, j) => (
                <td key={j} className="truncate px-2 py-1 font-mono">
                  {row[j] === null ? <span className="italic text-slate-400">NULL</span> : String(row[j])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {(results.row_count > 3 || results.columns.length > 4) && (
        <div className="border-t border-slate-100 px-2 py-0.5 text-[10px] text-slate-400 dark:border-slate-800">
          {results.row_count > 3 && `+${results.row_count - 3}${results.truncated ? "+" : ""} more rows`}
          {results.columns.length > 4 && ` · ${results.columns.length - 4} more columns`}
        </div>
      )}
    </div>
  );
}

function Chips({ items, onPick, disabled, label }) {
  if (!items?.length) return null;
  return (
    <div className="mt-2 flex flex-wrap gap-1.5" aria-label={label}>
      {items.map((t) => (
        <button key={t} className="chip py-1" disabled={disabled} onClick={stop(() => onPick(t))}>{t}</button>
      ))}
    </div>
  );
}

function AssistantMessage({ msg, selected, isLast, loading, onSelect, onSend, onRetry, onFeedback }) {
  const r = msg.response || { type: "error" };
  const clickable = r.type === "sql";
  return (
    <div className="max-w-[90%]">
      <div
        role={clickable ? "button" : undefined}
        tabIndex={clickable ? 0 : undefined}
        onClick={clickable ? onSelect : undefined}
        onKeyDown={clickable ? (e) => e.key === "Enter" && e.target === e.currentTarget && onSelect() : undefined}
        className={`rounded-2xl rounded-tl-sm border px-3.5 py-2.5 text-sm shadow-sm transition ${TYPE_STYLES[r.type] || TYPE_STYLES.error}
          ${clickable ? "cursor-pointer hover:border-indigo-300" : ""} ${selected ? "ring-2 ring-indigo-500/60" : ""}`}
      >
        {TYPE_LABELS[r.type] && (
          <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide opacity-70">{TYPE_LABELS[r.type]}</div>
        )}
        {r.type === "sql" && (
          <div className="mb-1 flex flex-wrap items-center gap-1.5 text-[11px]">
            <span className="rounded bg-indigo-100 px-1.5 py-0.5 font-medium text-indigo-700 dark:bg-indigo-500/20 dark:text-indigo-300">
              {r.edited ? "Edited" : INTENT_LABELS[r.intent] || "SQL"}
            </span>
            {r.results && <span className="text-slate-500">{r.results.row_count}{r.results.truncated ? "+" : ""} rows</span>}
            {r.retries > 0 && <span className="text-slate-500">· self-corrected {r.retries}×</span>}
            {r.warnings?.length > 0 && <span className="text-amber-600">· {r.warnings.length} warning(s)</span>}
          </div>
        )}
        {r.based_on && (
          <p className="mb-1 truncate text-[11px] text-slate-500 dark:text-slate-400" title={r.based_on}>
            Modifying: “{r.based_on}”
          </p>
        )}
        <p className="whitespace-pre-wrap">{msg.content || "Done."}</p>
        {r.type === "sql" && r.sql && (
          <pre className="mt-2 max-h-28 overflow-hidden rounded-lg bg-slate-100 p-2 font-mono text-xs text-slate-700 dark:bg-slate-800 dark:text-slate-200">
            {r.sql}
          </pre>
        )}
        {r.type === "sql" && <ResultPreview results={r.results} />}
        {r.type === "error" && r.errors?.length > 0 && (
          <ul className="mt-1 list-disc pl-5 text-xs opacity-80">
            {r.errors.slice(0, 4).map((e, i) => <li key={i}>{e}</li>)}
          </ul>
        )}
        <Chips items={r.options} onPick={onSend} disabled={loading} label="Pick one" />
        {clickable && <div className="mt-1.5 text-[11px] text-indigo-600 dark:text-indigo-400">View details →</div>}
      </div>

      <div className="mt-1 flex items-center gap-0.5 pl-1">
        {(r.type === "error" || r.type === "sql") && msg.question && (
          <button className="btn-ghost px-1.5 py-1 text-[11px]" disabled={loading} onClick={() => onRetry(msg)}
            title={r.type === "error" ? "Try again" : "Generate a new answer to the same question"}>
            <IconRefresh className="h-3 w-3" /> {r.type === "error" ? "Retry" : "Regenerate"}
          </button>
        )}
        {r.type === "sql" && (
          <>
            <button
              className={`btn-ghost px-1.5 py-1 ${msg.rating === "up" ? "text-emerald-600 dark:text-emerald-400" : ""}`}
              onClick={() => onFeedback(msg, "up")} aria-label="Good answer" aria-pressed={msg.rating === "up"}
            >
              <IconThumbUp className="h-3 w-3" />
            </button>
            <button
              className={`btn-ghost px-1.5 py-1 ${msg.rating === "down" ? "text-rose-600 dark:text-rose-400" : ""}`}
              onClick={() => onFeedback(msg, "down")} aria-label="Bad answer" aria-pressed={msg.rating === "down"}
            >
              <IconThumbDown className="h-3 w-3" />
            </button>
          </>
        )}
      </div>
      {isLast && r.type === "sql" && (
        <Chips items={r.follow_ups} onPick={onSend} disabled={loading} label="Suggested follow-ups" />
      )}
    </div>
  );
}

function LoadingCard({ steps, streamText }) {
  return (
    <div className="max-w-[90%] rounded-2xl rounded-tl-sm border border-slate-200 bg-white px-3.5 py-2.5 text-sm shadow-sm dark:border-slate-800 dark:bg-slate-900" aria-live="polite">
      <div className="flex items-start gap-3">
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
      {streamText && <p className="mt-2 whitespace-pre-wrap border-t border-slate-100 pt-2 dark:border-slate-800">{streamText}<span className="animate-pulse">▍</span></p>}
    </div>
  );
}

export default function ChatPanel({
  messages, loading, steps, streamText, error, notice, waking, input, onInput, onSend, onStop,
  examples, selectedId, onSelect, onRetry, onFeedback, inputRef,
}) {
  const bottom = useRef(null);
  // Block body on purpose: newer Chrome returns a Promise from scrollIntoView, and an
  // effect must not return anything but a clean-up function.
  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length, loading, steps.length, streamText]);

  const submit = (e) => {
    e.preventDefault();
    if (!loading) onSend(input);
  };
  const lastAssistant = [...messages].reverse().find((m) => m.role === "assistant")?.id;

  return (
    <section className="flex min-h-0 flex-1 flex-col">
      {waking && (
        <div role="status" className="border-b border-amber-200 bg-amber-50 px-4 py-2 text-xs text-amber-800 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-300">
          Waking up the server… Free hosting sleeps when idle, so the first request can take up to a minute.
        </div>
      )}
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
                <button key={ex} className="chip" onClick={() => onSend(ex)} disabled={loading}>{ex}</button>
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
              <AssistantMessage
                msg={m}
                selected={m.id === selectedId}
                isLast={m.id === lastAssistant && !loading}
                loading={loading}
                onSelect={() => onSelect(m.id)}
                onSend={onSend}
                onRetry={onRetry}
                onFeedback={onFeedback}
              />
            </div>
          ),
        )}
        {loading && <LoadingCard steps={steps} streamText={streamText} />}
        {notice && <p className="text-center text-xs text-slate-500 dark:text-slate-400">{notice}</p>}
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
          {loading ? (
            <button type="button" className="btn-primary bg-slate-700 hover:bg-slate-600" onClick={onStop} aria-label="Stop generating">
              <IconStop />
            </button>
          ) : (
            <button type="submit" className="btn-primary" disabled={!input.trim()} aria-label="Send">
              <IconSend />
            </button>
          )}
        </div>
        <p className="mt-1.5 text-center text-[11px] text-slate-400">
          Enter to send · Shift+Enter for a new line · queries are validated and run read-only
        </p>
      </form>
    </section>
  );
}
