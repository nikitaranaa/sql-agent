# Deployment

Target setup: **backend on Render** (Docker, free tier) and **frontend on Vercel**.
Railway works the same way for the backend (it also builds from `backend/Dockerfile`).

## 0. Before you start
- The repo is pushed to GitHub (public).
- `backend/.env` is **not** committed (it's in `.gitignore`). Never push an API key.
- Locally, `cd backend && pytest` passes and `cd frontend && npm run build` succeeds.

## 1. Backend on Render

**Option A, blueprint (uses [`render.yaml`](../render.yaml)):**
1. Render dashboard → **New → Blueprint** → select the repo.
2. When prompted, enter `GROQ_API_KEY` (and `CORS_ORIGINS`, which you can fill in after step 2).
3. Deploy. Health check: `https://<service>.onrender.com/health` → `{"status":"ok"}`.

**Option B, manual:**
1. **New → Web Service** → connect the repo.
2. Root directory `backend`, runtime **Docker**.
3. Environment variables:
   | Key | Value |
   |---|---|
   | `LLM_PROVIDER` | `groq` (or `openai` / `anthropic`) |
   | `GROQ_API_KEY` | your key (or `OPENAI_API_KEY` / `ANTHROPIC_API_KEY`) |
   | `LLM_FAST_MODEL` / `LLM_STRONG_MODEL` | see `.env.example` |
   | `CORS_ORIGINS` | `https://<your-app>.vercel.app` |
4. Health check path: `/health`.

The Dockerfile installs dependencies, **bakes the sample SQLite database into the image**
(`python -m app.db.seed --force`), runs as a non-root user and starts
`uvicorn app.main:app --host 0.0.0.0 --port $PORT`.

## 2. Frontend on Vercel
1. Vercel → **Add New → Project** → import the repo.
2. **Root Directory:** `frontend`. The framework preset is detected as Vite.
3. Environment variable: `VITE_API_URL = https://<service>.onrender.com` (no trailing slash).
4. Deploy. `vercel.json` rewrites all paths to `index.html` (SPA).

## 3. Connect them
- Put the Vercel URL in the backend's `CORS_ORIGINS` and redeploy. (`https://*.vercel.app` is also allowed by a regex, so preview deployments work.)
- If you change `VITE_API_URL`, redeploy the frontend: Vite bakes env vars in at build time.

## 4. Verify
Open the Vercel URL in an **incognito window** and check:
- the schema sidebar loads (proves CORS + backend are working)
- `Show all employees hired after January 2024` returns SQL, an explanation and results
- `Who won the FIFA World Cup?` is refused
- the follow-up chain works

## Free-tier notes
- **Groq free tier** has per-minute and per-day token limits. Each question uses about 3–4 model calls, so heavy testing can hit the daily cap; the app then shows a clear error. Check your limits at console.groq.com.
- Render's free tier **sleeps after ~15 minutes without traffic** and needs up to a minute to wake. The UI's error message mentions this. Open the app a minute before a demo.
- Conversation memory is in RAM by default and resets when the service sleeps or restarts. The browser still keeps the visible history. To persist server-side memory, attach a disk and set `CHECKPOINT_DB=/data/checkpoints.db`.

## Docker locally
```bash
cp backend/.env.example backend/.env    # add your key
docker compose up --build
# frontend: http://localhost:5173   backend: http://localhost:8000/docs
```

## Troubleshooting
| Symptom | Fix |
|---|---|
| "Can't reach the API" in the UI | Wrong `VITE_API_URL`, the backend is asleep, or CORS: check that `CORS_ORIGINS` contains the exact frontend origin |
| `The language model is not configured` | API key missing or wrong `LLM_PROVIDER` / model name |
| 422 from `/chat` | Message empty or over 4,000 characters, or `session_id` malformed |
| Results empty but SQL looks right | The sample data may not contain matching rows. Check in the schema sidebar |
