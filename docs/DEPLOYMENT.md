# Deployment (Step 9)

## 0. Before you push to GitHub

```bash
git status                      # backend/.env must NOT be listed
git check-ignore -v backend/.env
```
If a real key was ever committed or pasted somewhere public, **rotate it** (new Gemini key, new Atlas password); deleting the commit is not enough.

## 1. MongoDB Atlas
Create a free cluster, a database user, and under *Network Access* allow `0.0.0.0/0` (hosts have changing IPs). Copy the connection string into `MONGODB_URI`.

## 2. Render (Docker, one service for API + frontend)
1. Push the repo to GitHub.
2. Render -> **New + -> Blueprint** -> choose the repo (it reads `render.yaml`).
3. Fill the secrets: `MONGODB_URI`, `GEMINI_API_KEY`, `CORS_ORIGINS` (your `https://<name>.onrender.com`). `ADMIN_TOKEN` is generated for you.
4. Deploy. The Dockerfile builds the frontend, installs the backend and starts `uvicorn`.

Railway / Fly.io work the same way: build the Dockerfile and set the environment variables; the app reads `$PORT`.

## 3. Verify production (checklist)

| Check | Command / action | Expected |
|---|---|---|
| Health | `curl https://<app>/api/health` | `status: ok`, `environment: production`, database mongodb |
| LLM | open the app, click **Test AI** | provider + model shown |
| Strategy | submit the example brief | structured strategy in a few seconds |
| Reuse | submit the same brief again | instant result (`reused: true`), no new LLM call in the logs |
| Content + images | run the agent for Instagram | steps complete, images load from `/api/media/...` |
| Error path | temporarily set a wrong key | readable message, no key in the response |
| Rate limit | send > `RATE_LIMIT_PER_MINUTE` AI requests | 429 with `Retry-After` |
| Metrics | `curl -H "X-Admin-Token: <token>" https://<app>/api/metrics` | counts, latency, AI errors |
| Docs closed | open `/docs` | 404 in production |
| Security headers | `curl -I https://<app>/api/health` | `X-Content-Type-Options`, `X-Frame-Options`, `Strict-Transport-Security` |

## 4. Images on free hosting
Render's free disk is ephemeral: generated images vanish on redeploy. For the portfolio demo this is fine; for real use attach a persistent disk mounted at `/data` (already the default `STORAGE_DIR` in the Docker image) or move storage to S3 / Cloudinary.

## 5. Logs and monitoring
`LOG_JSON=true` prints one JSON object per line: search the host's log viewer for `"level": "WARNING"`, `AI call failed` or a user's `request_id` (the reference shown in error messages).
