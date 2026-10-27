import { useState } from "react";
import { IconChevron, IconKey, IconLink, IconPencil, IconPlus, IconSearch, IconTrash, IconX } from "./Icons.jsx";

function SchemaTable({ table, onInsert }) {
  const [open, setOpen] = useState(false);
  return (
    <li>
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-1 rounded-md px-2 py-1 text-left text-sm hover:bg-slate-100 dark:hover:bg-slate-800"
        aria-expanded={open}
      >
        <IconChevron className={`h-3.5 w-3.5 shrink-0 transition ${open ? "rotate-90" : ""}`} />
        <span className="truncate font-medium">{table.name}</span>
        <span className="ml-auto text-xs text-slate-400">{table.row_count}</span>
      </button>
      {open && (
        <ul className="mb-1 ml-5 border-l border-slate-200 pl-2 dark:border-slate-800">
          {table.columns.map((c) => (
            <li key={c.name}>
              <button
                onClick={() => onInsert(`${table.name}.${c.name}`)}
                className="flex w-full items-center gap-1.5 rounded px-1 py-0.5 text-left text-xs text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
                title={c.fk ? `References ${c.fk}` : "Insert into message"}
              >
                {c.pk ? <IconKey className="h-3 w-3 text-amber-500" /> : c.fk ? <IconLink className="h-3 w-3 text-sky-500" /> : <span className="w-3" />}
                <span className="font-mono">{c.name}</span>
                <span className="ml-auto text-[10px] uppercase text-slate-400">{c.type}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}

export default function Sidebar({
  open, onClose, sessions, activeId, onSelect, onNew, onDelete, onRename, schema, schemaError, onInsert,
}) {
  const [query, setQuery] = useState("");
  const [editing, setEditing] = useState(null);   // {id, title}
  const q = query.trim().toLowerCase();
  // Search titles and the questions inside each conversation.
  const shown = q
    ? sessions.filter((s) => s.title.toLowerCase().includes(q)
        || s.messages.some((m) => m.role === "user" && m.content.toLowerCase().includes(q)))
    : sessions;
  const commitRename = () => {
    if (editing?.title.trim()) onRename(editing.id, editing.title.trim().slice(0, 80));
    setEditing(null);
  };

  return (
    <>
      {open && <div className="fixed inset-0 z-30 bg-black/40 lg:hidden" onClick={onClose} />}
      <aside
        className={`fixed inset-y-0 left-0 z-40 flex w-72 flex-col border-r border-slate-200 bg-white transition-transform dark:border-slate-800 dark:bg-slate-900
          lg:static lg:z-auto lg:translate-x-0 ${open ? "translate-x-0" : "-translate-x-full"}`}
      >
        <div className="flex items-center gap-2 p-3">
          <button className="btn-primary flex-1 justify-center" onClick={onNew}>
            <IconPlus /> New chat
          </button>
          <button className="btn-ghost lg:hidden" onClick={onClose} aria-label="Close sidebar">
            <IconX />
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-3 pb-3 scrollbar-thin">
          <h2 className="panel-title px-2 pb-1">Conversations</h2>
          {sessions.length > 3 && (
            <label className="mb-1.5 flex items-center gap-1.5 rounded-md border border-slate-200 px-2 py-1 dark:border-slate-700">
              <IconSearch className="h-3.5 w-3.5 text-slate-400" />
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search conversations"
                className="w-full bg-transparent text-xs outline-none placeholder:text-slate-400"
                aria-label="Search conversations"
              />
            </label>
          )}
          <ul className="mb-4 space-y-0.5">
            {shown.map((s) => (
              <li key={s.id} className="group flex items-center">
                {editing?.id === s.id ? (
                  <input
                    autoFocus
                    value={editing.title}
                    onChange={(e) => setEditing({ ...editing, title: e.target.value })}
                    onBlur={commitRename}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") commitRename();
                      if (e.key === "Escape") setEditing(null);
                    }}
                    className="flex-1 rounded-md border border-indigo-400 bg-white px-2 py-1 text-sm dark:bg-slate-800"
                    aria-label="Conversation name"
                    maxLength={80}
                  />
                ) : (
                  <button
                    onClick={() => onSelect(s.id)}
                    onDoubleClick={() => setEditing({ id: s.id, title: s.title })}
                    className={`flex-1 truncate rounded-md px-2 py-1.5 text-left text-sm ${
                      s.id === activeId
                        ? "bg-indigo-50 font-medium text-indigo-700 dark:bg-indigo-500/10 dark:text-indigo-300"
                        : "hover:bg-slate-100 dark:hover:bg-slate-800"
                    }`}
                    title="Double-click to rename"
                  >
                    {s.title}
                  </button>
                )}
                <button
                  onClick={() => setEditing({ id: s.id, title: s.title })}
                  className="btn-ghost px-1.5 opacity-0 group-hover:opacity-100 focus:opacity-100"
                  aria-label={`Rename ${s.title}`}
                >
                  <IconPencil className="h-3.5 w-3.5" />
                </button>
                <button
                  onClick={() => onDelete(s.id)}
                  className="btn-ghost px-1.5 opacity-0 group-hover:opacity-100 focus:opacity-100"
                  aria-label={`Delete ${s.title}`}
                >
                  <IconTrash className="h-3.5 w-3.5" />
                </button>
              </li>
            ))}
            {shown.length === 0 && <li className="px-2 text-xs text-slate-400">No matches.</li>}
          </ul>

          <h2 className="panel-title px-2 pb-1">Database schema</h2>
          {schemaError && <p className="px-2 text-xs text-rose-500">{schemaError}</p>}
          {!schema && !schemaError && <p className="px-2 text-xs text-slate-400">Loading…</p>}
          {schema && (
            <ul className="space-y-0.5">
              {schema.tables.map((t) => (
                <SchemaTable key={t.name} table={t} onInsert={onInsert} />
              ))}
            </ul>
          )}
          <p className="mt-3 px-2 text-[11px] text-slate-400">
            <IconKey className="inline h-3 w-3 text-amber-500" /> primary key ·{" "}
            <IconLink className="inline h-3 w-3 text-sky-500" /> foreign key · click a column to insert it
          </p>
        </div>
      </aside>
    </>
  );
}
