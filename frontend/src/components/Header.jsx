import { IconDb, IconMenu, IconMoon, IconSun } from "./Icons.jsx";

const DIALECTS = [
  { value: "sqlite", label: "SQLite" },
  { value: "postgres", label: "PostgreSQL" },
  { value: "mysql", label: "MySQL" },
];

export default function Header({ dialect, onDialect, execute, onExecute, dark, onToggleDark, onMenu }) {
  return (
    <header className="flex items-center gap-3 border-b border-slate-200 bg-white/80 px-4 py-2.5 backdrop-blur dark:border-slate-800 dark:bg-slate-900/80">
      <button className="btn-ghost lg:hidden" onClick={onMenu} aria-label="Open sidebar">
        <IconMenu />
      </button>
      <div className="flex items-center gap-2">
        <span className="grid h-8 w-8 place-items-center rounded-lg bg-indigo-600 text-white">
          <IconDb />
        </span>
        <div className="leading-tight">
          <h1 className="text-sm font-semibold">SQL Query AI Agent</h1>
          <p className="hidden text-xs text-slate-500 sm:block dark:text-slate-400">
            Ask in plain English. Read-only, validated SQL.
          </p>
        </div>
      </div>

      <div className="ml-auto flex items-center gap-2">
        <label className="flex items-center gap-1.5 text-xs text-slate-600 dark:text-slate-300">
          <span className="hidden sm:inline">Dialect</span>
          <select
            value={dialect}
            onChange={(e) => onDialect(e.target.value)}
            className="rounded-lg border border-slate-200 bg-white px-2 py-1 text-xs dark:border-slate-700 dark:bg-slate-800"
            aria-label="SQL dialect"
          >
            {DIALECTS.map((d) => (
              <option key={d.value} value={d.value}>{d.label}</option>
            ))}
          </select>
        </label>
        <label
          className="flex cursor-pointer items-center gap-1.5 text-xs text-slate-600 dark:text-slate-300"
          title="Run the validated query against the sample database"
        >
          <input
            type="checkbox"
            checked={execute}
            onChange={(e) => onExecute(e.target.checked)}
            className="h-3.5 w-3.5 accent-indigo-600"
          />
          <span>Run query</span>
        </label>
        <button className="btn-ghost" onClick={onToggleDark} aria-label="Toggle dark mode">
          {dark ? <IconSun /> : <IconMoon />}
        </button>
      </div>
    </header>
  );
}
