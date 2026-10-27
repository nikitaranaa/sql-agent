import { useState } from "react";
import { PrismLight as SyntaxHighlighter } from "react-syntax-highlighter";
import sql from "react-syntax-highlighter/dist/esm/languages/prism/sql";
import { oneDark, oneLight } from "react-syntax-highlighter/dist/esm/styles/prism";
import { exportCsv } from "../lib/api.js";
import { diffLines } from "../lib/diff.js";
import { downloadFile, toCSV } from "../lib/download.js";
import BarChart, { chartSpec } from "./Chart.jsx";
import { IconCheck, IconCopy, IconDownload, IconPencil, IconPlay } from "./Icons.jsx";

SyntaxHighlighter.registerLanguage("sql", sql);

function SqlCode({ code, dark, maxHeight = "18rem" }) {
  return (
    <SyntaxHighlighter
      language="sql"
      style={dark ? oneDark : oneLight}
      customStyle={{ margin: 0, borderRadius: "0.5rem", fontSize: "0.8rem", maxHeight, background: dark ? "#0f172a" : "#f8fafc" }}
      codeTagProps={{ style: { background: "transparent" } }}
      wrapLongLines
    >
      {code || ""}
    </SyntaxHighlighter>
  );
}

function CopyButton({ text, label = "Copy" }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch { /* clipboard blocked */ }
  };
  return (
    <button className="btn-ghost" onClick={copy} aria-label="Copy SQL">
      {copied ? <IconCheck className="text-emerald-500" /> : <IconCopy />} {copied ? "Copied" : label}
    </button>
  );
}

const LEVEL_STYLES = {
  low: "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300",
  medium: "bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300",
  high: "bg-rose-100 text-rose-700 dark:bg-rose-500/15 dark:text-rose-300",
};

function Section({ title, right, children }) {
  return (
    <section className="panel p-4">
      <div className="mb-2 flex items-center gap-2">
        <h3 className="panel-title">{title}</h3>
        <div className="ml-auto flex items-center gap-1">{right}</div>
      </div>
      {children}
    </section>
  );
}

function ResultsTable({ results, error }) {
  if (error) return <p className="text-sm text-rose-600 dark:text-rose-400">{error}</p>;
  if (!results) return <p className="text-sm text-slate-500">Query was not executed (turn on “Run query” to see results).</p>;
  if (results.row_count === 0) return <p className="text-sm text-slate-500">The query ran successfully and returned no rows.</p>;
  return (
    <div className="max-h-96 overflow-auto rounded-lg border border-slate-200 scrollbar-thin dark:border-slate-800">
      <table className="min-w-full text-left text-xs">
        <thead className="sticky top-0 bg-slate-100 dark:bg-slate-800">
          <tr>
            {results.columns.map((c, i) => (
              <th key={i} className="whitespace-nowrap px-3 py-2 font-semibold">{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {results.rows.map((row, i) => (
            <tr key={i} className="border-t border-slate-100 odd:bg-white even:bg-slate-50 dark:border-slate-800 dark:odd:bg-slate-900 dark:even:bg-slate-900/60">
              {row.map((v, j) => (
                <td key={j} className="whitespace-nowrap px-3 py-1.5 font-mono">
                  {v === null ? <span className="italic text-slate-400">NULL</span> : String(v)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Diff({ before, after }) {
  const lines = diffLines(before, after);
  const changed = lines.filter((l) => l.type !== "same").length;
  return (
    <details className="mt-2 text-xs" open>
      <summary className="cursor-pointer text-slate-500">Before → after ({changed} line{changed === 1 ? "" : "s"} changed)</summary>
      <pre className="mt-1 max-h-72 overflow-auto rounded-lg bg-slate-50 py-2 font-mono text-[11px] leading-5 dark:bg-slate-800/60" aria-label="Diff of original and new query">
        {lines.map((l, i) => (
          <div
            key={i}
            className={`px-2 ${l.type === "add" ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-500/15 dark:text-emerald-300"
              : l.type === "del" ? "bg-rose-100 text-rose-800 line-through decoration-rose-400/60 dark:bg-rose-500/15 dark:text-rose-300" : ""}`}
          >
            <span className="mr-2 select-none opacity-60">{l.type === "add" ? "+" : l.type === "del" ? "−" : " "}</span>{l.text || " "}
          </div>
        ))}
      </pre>
    </details>
  );
}

function CsvButton({ response }) {
  const [state, setState] = useState("");
  const { results } = response;
  // The preview holds at most 100 rows; when it was cut off, fetch everything from the server.
  const download = async () => {
    if (!results.truncated) {
      downloadFile("results.csv", toCSV(results.columns, results.rows), "text/csv");
      return;
    }
    setState("Exporting…");
    try {
      const { blob, truncated } = await exportCsv(response.sql_sqlite);
      downloadFile("results.csv", blob, "text/csv");
      setState(truncated ? "Exported the first 50,000 rows" : "");
    } catch (e) {
      setState(e.message);
    }
  };
  return (
    <span className="flex items-center gap-1">
      {state && <span className="text-[11px] text-slate-500">{state}</span>}
      <button className="btn-ghost" onClick={download} title={results.truncated ? "Download every row, not just the preview" : "Download as CSV"}>
        <IconDownload /> {results.truncated ? "Full CSV" : "CSV"}
      </button>
    </span>
  );
}

function ResultsView({ results, error }) {
  const spec = chartSpec(results);
  const [view, setView] = useState(spec ? "chart" : "table");
  if (!spec || error) return <ResultsTable results={results} error={error} />;
  return (
    <>
      <div className="mb-2 inline-flex rounded-lg border border-slate-200 p-0.5 text-xs dark:border-slate-700" role="tablist">
        {["chart", "table"].map((v) => (
          <button
            key={v}
            role="tab"
            aria-selected={view === v}
            onClick={() => setView(v)}
            className={`rounded-md px-2.5 py-1 capitalize ${view === v ? "bg-indigo-600 text-white" : "text-slate-600 dark:text-slate-300"}`}
          >
            {v}
          </button>
        ))}
      </div>
      {view === "chart" ? <BarChart results={results} spec={spec} /> : <ResultsTable results={results} error={error} />}
    </>
  );
}

export default function ResultPanel({ response, dark, onRun }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [running, setRunning] = useState(false);
  const [runErrors, setRunErrors] = useState([]);
  if (!response) {
    return (
      <div className="grid h-full place-items-center p-8 text-center text-sm text-slate-400">
        <div>
          <p className="font-medium text-slate-500 dark:text-slate-300">No query selected</p>
          <p className="mt-1">The SQL, its explanation and the results appear here.</p>
        </div>
      </div>
    );
  }
  const r = response;
  const startEdit = () => {
    setDraft(r.sql);
    setRunErrors([]);
    setEditing(true);
  };
  const run = async () => {
    setRunning(true);
    setRunErrors([]);
    try {
      const out = await onRun(draft);
      if (out.ok) setEditing(false);
      else setRunErrors(out.errors);
    } catch (e) {
      setRunErrors([e.message]);
    } finally {
      setRunning(false);
    }
  };
  const ext = r.dialect === "sqlite" ? "sqlite" : r.dialect;
  const cost = r.cost;
  const indexRecs = [
    ...(r.optimization?.index_recommendations || []).map((i) => ({ statement: i.statement, reason: i.reason })),
    ...(cost?.index_recommendations || []).map((i) => ({ statement: i.statement, reason: i.reason })),
  ].filter((rec, i, all) => all.findIndex((x) => x.statement.toLowerCase() === rec.statement.toLowerCase()) === i);

  return (
    <div className="space-y-3 p-4">
      <Section
        title={`SQL · ${r.dialect}`}
        right={
          <>
            {!editing && (
              <button className="btn-ghost" onClick={startEdit} title="Edit this query and run it">
                <IconPencil /> Edit
              </button>
            )}
            <CopyButton text={r.sql} />
            <button className="btn-ghost" onClick={() => downloadFile(`query.${ext}.sql`, r.sql + "\n", "application/sql")}>
              <IconDownload /> .sql
            </button>
          </>
        }
      >
        {editing ? (
          <div>
            <textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) run(); }}
              rows={Math.min(16, draft.split("\n").length + 1)}
              spellCheck={false}
              className="w-full rounded-lg border border-indigo-300 bg-slate-50 p-2 font-mono text-xs dark:border-indigo-500/40 dark:bg-slate-950"
              aria-label="Edit SQL"
            />
            {runErrors.length > 0 && (
              <ul role="alert" className="mt-1 list-disc pl-5 text-xs text-rose-600 dark:text-rose-400">
                {runErrors.map((e, i) => <li key={i}>{e}</li>)}
              </ul>
            )}
            <div className="mt-2 flex items-center gap-2">
              <button className="btn-primary" onClick={run} disabled={running || !draft.trim()}>
                <IconPlay className="h-3.5 w-3.5" /> {running ? "Running…" : "Validate & run"}
              </button>
              <button className="btn-ghost" onClick={() => setEditing(false)} disabled={running}>Cancel</button>
              <span className="ml-auto text-[11px] text-slate-400">⌘/Ctrl+Enter · same read-only checks as generated SQL</span>
            </div>
          </div>
        ) : (
          <SqlCode code={r.sql} dark={dark} />
        )}
        {r.edited && !editing && <p className="mt-1.5 text-[11px] text-slate-500">Edited by you and re-validated.</p>}
        {r.dialect !== "sqlite" && (
          <p className="mt-1.5 text-[11px] text-slate-500">
            Transpiled from the validated SQLite query (which is what ran against the sample database).
          </p>
        )}
      </Section>

      <Section title="Explanation">
        <p className="text-sm">{r.explanation?.summary || r.message}</p>
        {r.explanation?.details?.length > 0 && (
          <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-slate-600 dark:text-slate-300">
            {r.explanation.details.map((d, i) => <li key={i}>{d}</li>)}
          </ul>
        )}
        {r.notes && <p className="mt-2 text-xs text-slate-500">Note: {r.notes}</p>}
      </Section>

      {r.debug && (
        <Section title="Debugging">
          {r.debug.issues?.length ? (
            <ol className="space-y-2 text-sm">
              {r.debug.issues.map((iss, i) => (
                <li key={i} className="rounded-lg bg-slate-50 p-2.5 dark:bg-slate-800/60">
                  <p className="font-medium text-rose-600 dark:text-rose-400">{iss.problem}</p>
                  <p className="mt-0.5 text-slate-600 dark:text-slate-300"><span className="font-medium">Why:</span> {iss.why}</p>
                  <p className="mt-0.5 text-slate-600 dark:text-slate-300"><span className="font-medium">Fix:</span> {iss.fix}</p>
                </li>
              ))}
            </ol>
          ) : (
            <p className="text-sm text-slate-500">No issues found.</p>
          )}
          <Diff before={r.debug.original_formatted || r.debug.original_sql} after={r.sql} />
        </Section>
      )}

      {r.optimization && (
        <Section title="Optimization">
          <ul className="list-disc space-y-1 pl-5 text-sm">
            {r.optimization.changes?.map((c, i) => <li key={i}>{c}</li>)}
            {r.optimization.removed_joins?.map((c, i) => <li key={`j${i}`}>Removed join: {c}</li>)}
          </ul>
          <Diff before={r.optimization.original_formatted || r.optimization.original_sql} after={r.sql} />
        </Section>
      )}

      {(r.warnings?.length > 0 || cost || indexRecs.length > 0) && (
        <Section
          title="Validation & cost"
          right={cost?.level && (
            <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${LEVEL_STYLES[cost.level]}`}>
              {cost.level} cost
            </span>
          )}
        >
          <p className="text-sm text-emerald-700 dark:text-emerald-400">
            ✓ Read-only · tables & columns verified · compiled by SQLite
            {r.retries > 0 && ` · self-corrected after ${r.retries} failed attempt${r.retries > 1 ? "s" : ""}`}
          </p>
          {r.warnings?.map((w, i) => (
            <p key={i} className="mt-1.5 text-sm text-amber-700 dark:text-amber-400">⚠ {w}</p>
          ))}
          {cost?.summary && <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">{cost.summary}</p>}
          {cost?.plan?.length > 0 && (
            <details className="mt-1 text-xs">
              <summary className="cursor-pointer text-slate-500">Query plan (EXPLAIN QUERY PLAN)</summary>
              <pre className="mt-1 overflow-x-auto rounded-lg bg-slate-50 p-2 font-mono dark:bg-slate-800/60">{cost.plan.join("\n")}</pre>
            </details>
          )}
          {indexRecs.length > 0 && (
            <div className="mt-3">
              <p className="text-xs font-semibold text-slate-500">Recommended indexes (not applied — the database is read-only)</p>
              <ul className="mt-1 space-y-1.5">
                {indexRecs.map((rec, i) => (
                  <li key={i} className="text-xs">
                    <code className="block rounded bg-slate-100 px-2 py-1 font-mono dark:bg-slate-800">{rec.statement}</code>
                    <span className="text-slate-500">{rec.reason}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </Section>
      )}

      <Section
        title={r.results ? `Results · ${r.results.row_count}${r.results.truncated ? "+ (first rows)" : ""} rows · ${r.results.elapsed_ms} ms` : "Results"}
        right={r.results?.row_count > 0 && <CsvButton response={r} />}
      >
        <ResultsView key={r.sql_sqlite} results={r.results} error={r.execution_error} />
      </Section>
    </div>
  );
}
