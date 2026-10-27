import { IconDb, IconLogout, IconMenu, IconMoon, IconSun, IconUser } from "./Icons.jsx";

const DIALECTS = [
  { value: "sqlite", label: "SQLite" },
  { value: "postgres", label: "PostgreSQL" },
  { value: "mysql", label: "MySQL" },
];

export default function Header({
  dialect, onDialect, execute, onExecute, dark, onToggleDark, onMenu, auth, syncing, onSignIn, onSignOut,
}) {
  return (
    <header className="flex items-center gap-2 border-b border-slate-200 bg-white/80 px-2 py-2.5 backdrop-blur sm:gap-3 sm:px-4 dark:border-slate-800 dark:bg-slate-900/80">
      <button className="btn-ghost lg:hidden" onClick={onMenu} aria-label="Open sidebar">
        <IconMenu />
      </button>
      <div className="flex items-center gap-2">
        <span className="hidden h-8 w-8 place-items-center rounded-lg bg-indigo-600 text-white sm:grid">
          <IconDb />
        </span>
        <div className="leading-tight">
          <h1 className="whitespace-nowrap text-sm font-semibold">
            <span className="sm:hidden">SQL Agent</span>
            <span className="hidden sm:inline">SQL Query AI Agent</span>
          </h1>
          <p className="hidden text-xs text-slate-500 sm:block dark:text-slate-400">
            Ask in plain English. Read-only, validated SQL.
          </p>
        </div>
      </div>

      <div className="ml-auto flex items-center gap-1 sm:gap-2">
        <label className="flex items-center gap-1.5 text-xs text-slate-600 dark:text-slate-300">
          <span className="hidden sm:inline">Dialect</span>
          <select
            value={dialect}
            onChange={(e) => onDialect(e.target.value)}
            className="max-w-[6rem] rounded-lg border border-slate-200 bg-white px-1.5 py-1 text-xs sm:max-w-none sm:px-2 dark:border-slate-700 dark:bg-slate-800"
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
          <span><span className="hidden sm:inline">Run query</span><span className="sm:hidden">Run</span></span>
        </label>
        <button className="btn-ghost" onClick={onToggleDark} aria-label="Toggle dark mode">
          {dark ? <IconSun /> : <IconMoon />}
        </button>
        {auth ? (
          <div className="flex items-center gap-1 sm:border-l sm:border-slate-200 sm:pl-2 sm:dark:border-slate-700">
            <span className="hidden items-center gap-1 text-xs text-slate-600 sm:flex dark:text-slate-300" title={syncing ? "Syncing…" : "Conversations synced to your account"}>
              <IconUser className="h-3.5 w-3.5" /> {auth.username}
              <span className={`h-1.5 w-1.5 rounded-full ${syncing ? "animate-pulse bg-amber-500" : "bg-emerald-500"}`} />
            </span>
            <button className="btn-ghost" onClick={onSignOut} aria-label="Sign out" title={`Signed in as ${auth.username}`}>
              <IconLogout className="h-3.5 w-3.5 sm:hidden" />
              <span className="hidden sm:inline">Sign out</span>
            </button>
          </div>
        ) : (
          <button className="btn-ghost border border-slate-200 dark:border-slate-700" onClick={onSignIn}>
            <IconUser className="h-3.5 w-3.5" /> <span className="hidden sm:inline">Sign in</span>
          </button>
        )}
      </div>
    </header>
  );
}
