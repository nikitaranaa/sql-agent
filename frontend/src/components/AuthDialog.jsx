import { useEffect, useRef, useState } from "react";
import { login, register } from "../lib/api.js";
import { IconX } from "./Icons.jsx";

export default function AuthDialog({ open, onClose, onSignedIn }) {
  const [mode, setMode] = useState("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const first = useRef(null);

  useEffect(() => {
    if (open) {
      setError("");
      setPassword("");
      setTimeout(() => first.current?.focus(), 0);
    }
  }, [open]);

  if (!open) return null;

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const auth = await (mode === "login" ? login : register)(username.trim(), password);
      onSignedIn(auth);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/50 p-4" onMouseDown={onClose}>
      <form
        onSubmit={submit}
        onMouseDown={(e) => e.stopPropagation()}
        onKeyDown={(e) => e.key === "Escape" && onClose()}
        className="panel w-full max-w-sm p-5"
        role="dialog"
        aria-modal="true"
        aria-labelledby="auth-title"
      >
        <div className="mb-3 flex items-center">
          <h2 id="auth-title" className="text-base font-semibold">
            {mode === "login" ? "Sign in" : "Create an account"}
          </h2>
          <button type="button" className="btn-ghost ml-auto" onClick={onClose} aria-label="Close">
            <IconX />
          </button>
        </div>
        <p className="mb-4 text-xs text-slate-500 dark:text-slate-400">
          Optional. Signing in keeps your conversations on the server, so they follow you to other
          devices and survive clearing the browser.
        </p>
        <label className="mb-3 block text-xs font-medium">
          Username
          <input
            ref={first}
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
            required
            minLength={3}
            maxLength={32}
            className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-800"
          />
        </label>
        <label className="mb-3 block text-xs font-medium">
          Password
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete={mode === "login" ? "current-password" : "new-password"}
            required
            minLength={mode === "login" ? 1 : 8}
            maxLength={128}
            className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-800"
          />
          {mode === "register" && <span className="mt-1 block font-normal text-slate-400">At least 8 characters.</span>}
        </label>
        {error && <p role="alert" className="mb-3 text-sm text-rose-600 dark:text-rose-400">{error}</p>}
        <button type="submit" className="btn-primary w-full justify-center py-2 text-sm" disabled={busy}>
          {busy ? "Please wait…" : mode === "login" ? "Sign in" : "Create account"}
        </button>
        <p className="mt-3 text-center text-xs text-slate-500">
          {mode === "login" ? "No account yet? " : "Already have one? "}
          <button
            type="button"
            className="font-medium text-indigo-600 hover:underline dark:text-indigo-400"
            onClick={() => { setMode(mode === "login" ? "register" : "login"); setError(""); }}
          >
            {mode === "login" ? "Create one" : "Sign in"}
          </button>
        </p>
      </form>
    </div>
  );
}
