import { useState } from "react";

const isNum = (v) => typeof v === "number" && Number.isFinite(v);
const fmt = (v) => v.toLocaleString(undefined, { maximumFractionDigits: 2 });

/**
 * Which columns to chart, or null. Only small "label + non-negative number" results get a
 * chart: a horizontal bar per row, which reads well for rankings and per-group totals.
 */
export function chartSpec(results) {
  if (!results || results.row_count < 2 || results.row_count > 30) return null;
  const { columns, rows } = results;
  const numeric = columns.map((_, c) => rows.every((r) => r[c] === null || isNum(r[c])) && rows.some((r) => isNum(r[c])));
  const label = numeric.findIndex((n) => !n);
  const value = numeric.lastIndexOf(true);
  if (label === -1 || value === -1) return null;
  if (rows.some((r) => isNum(r[value]) && r[value] < 0)) return null;
  return { label, value };
}

export default function BarChart({ results, spec }) {
  const [hover, setHover] = useState(null);
  const { columns, rows } = results;
  const max = Math.max(...rows.map((r) => (isNum(r[spec.value]) ? r[spec.value] : 0)), 0) || 1;

  return (
    <figure>
      <figcaption className="mb-2 text-xs text-slate-500 dark:text-slate-400">
        {columns[spec.value]} by {columns[spec.label]}
      </figcaption>
      <div className="space-y-0.5" role="list">
        {rows.map((row, i) => {
          const v = isNum(row[spec.value]) ? row[spec.value] : 0;
          const label = row[spec.label] === null ? "NULL" : String(row[spec.label]);
          return (
            <div
              key={i}
              role="listitem"
              className="relative grid grid-cols-[minmax(0,9rem)_1fr_auto] items-center gap-2 py-px"
              onMouseEnter={() => setHover(i)}
              onMouseLeave={() => setHover(null)}
              aria-label={`${label}: ${fmt(v)}`}
            >
              <span className="truncate text-xs text-slate-600 dark:text-slate-300" title={label}>{label}</span>
              <div className="h-3.5">
                <div
                  className={`h-full rounded-r bg-indigo-600 transition-opacity dark:bg-indigo-400 ${hover !== null && hover !== i ? "opacity-40" : ""}`}
                  style={{ width: `${Math.max((v / max) * 100, 0.5)}%` }}
                />
              </div>
              <span className="text-right font-mono text-[11px] tabular-nums text-slate-500 dark:text-slate-400">{fmt(v)}</span>
              {hover === i && (
                <div className="pointer-events-none absolute -top-7 left-36 z-10 whitespace-nowrap rounded-md border border-slate-200 bg-white px-2 py-1 text-xs shadow-md dark:border-slate-700 dark:bg-slate-800">
                  <span className="font-medium">{label}</span> · {columns[spec.value]}: <span className="font-mono">{fmt(v)}</span>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </figure>
  );
}
