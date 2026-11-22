# AI Marketing Content Generator

> Enter a short campaign brief and an AI agent plans the campaign, writes platform-specific copy and generates the visual creatives, all saved in a searchable history.

**Live demo:** `https://<your-app>.onrender.com` · **Demo video:** `<link>` · **Architecture:** [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

![Workflow](docs/screenshots/01-brief.png)

## Features

| Phase | What it does |
|---|---|
| 1 Strategy | Brief -> validated, structured marketing strategy (campaign idea, audience, selling points, tone, CTA, content types, KPIs) |
| 2 Content | Platform-specific copy for Instagram, Facebook, LinkedIn, X, TikTok, YouTube, Email, Google Ads, Blog; several variations, regenerate or pick one |
| 3 Creatives | LLM writes image prompts, image model renders them; product-photo upload, revisions with version history |
| 4 Agent | One brief runs the whole workflow automatically: plan -> (optional approval) -> copy -> images -> reel concept + promo caption; partial regeneration, approvals, audited export, history |
| 5 Production | Quality gate + industry-aware prompts, reuse of existing results, rate limiting, secret masking, request ids, metrics, Docker deployment, CI |

## Architecture

![Architecture](docs/architecture.png)

React (Vite) -> FastAPI -> LLM (Gemini / Claude / OpenAI) and image model (Gemini Image / gpt-image-1) -> MongoDB Atlas + file storage. Details and data flow: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Tech stack

Frontend: React 18, Vite, lucide-react. Backend: Python 3.12, FastAPI, Pydantic v2, Motor (async MongoDB), httpx. AI: Gemini / Anthropic / OpenAI LLMs with structured JSON output, Gemini Image / gpt-image-1, Pillow (offline mock renderer). Data: MongoDB Atlas. Ops: Docker, Render blueprint, GitHub Actions CI, pytest (100+ offline tests).

## Quick start (local)

```bash
# 1. backend
cd backend
python -m venv .venv && source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                      # then edit .env (see below)
uvicorn main:app --reload --port 8000

# 2. frontend (second terminal)
cd frontend
npm install
npm run dev                                               # http://localhost:5173 (proxies /api to :8000)
```

No keys yet? Set `USE_MOCK_DB=true`, `LLM_PROVIDER=mock`, `IMAGE_PROVIDER=mock` and the entire workflow runs offline.

Run the tests: `cd backend && python -m pytest -q` (offline, no secrets). Evaluate quality: `python scripts/evaluate.py` (add `--live` for real providers).

## Environment variables

Full commented list in [`backend/.env.example`](backend/.env.example). The important ones:

| Variable | Purpose |
|---|---|
| `MONGODB_URI`, `MONGODB_DB`, `USE_MOCK_DB` | Database (Atlas URI, or in-memory mock) |
| `LLM_PROVIDER` + `GEMINI_API_KEY` / `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` | Text generation |
| `IMAGE_PROVIDER`, `GEMINI_IMAGE_MODEL`, `OPENAI_IMAGE_MODEL` | Image generation (`mock` = placeholders) |
| `CORS_ORIGINS` | Allowed browser origins |
| `ENVIRONMENT=production` | HSTS on, `/docs` off, `/api/metrics` needs a token |
| `ADMIN_TOKEN` | Header `X-Admin-Token` to read `/api/metrics` |
| `RATE_LIMIT_PER_MINUTE` | Per-IP limit on AI endpoints (0 = off) |
| `STRATEGY_CACHE_HOURS` | Identical brief inside the window reuses the saved campaign |
| `LOG_LEVEL`, `LOG_JSON`, `LOG_FILE` | Logging |

API keys live **only** in backend environment variables. The frontend never receives them, `.env` is git-ignored and secrets are masked in logs and error messages.

## Production hardening (Phase 5)

- **Quality gate** ([strategy_quality.py](backend/strategy_quality.py)): detects repeated points, contradictory word lists, invented statistics, buzzwords, ungrounded output and weak CTAs, then retries once with the exact problems fed back to the model.
- **Prompt improvements**: industry playbooks (e-commerce, education, restaurant, software, fashion, real estate), objective and platform guidance, hard rules against invented facts.
- **Fewer paid calls**: identical briefs reuse the saved campaign (`?fresh=true` forces a new one), the frontend caches static lists and shares identical in-flight reads, provider calls are limited to 2 in flight, retries are capped.
- **Security**: keys server-side only, secret masking, per-IP rate limit on AI routes, body-size limit, security headers, strict CORS, no API docs in production, path-traversal-safe static serving.
- **Observability**: request ids in every log line and error body, JSON logs, `/api/metrics` (requests, p95 latency, AI calls / errors per provider, recent failures), health endpoint with version.
- **UX**: progress + step status for the agent run, per-asset errors that never stop other assets, readable messages for rate limits, timeouts, offline and server errors.

## Deployment

One Docker image serves API + frontend. See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) (Render blueprint included in [render.yaml](render.yaml)).

## Project structure

```
backend/   main.py, observability.py, strategy_quality.py, llm.py, prompts.py, content_*.py, image_*.py, agent_*.py, tests/, scripts/
frontend/  React app (src/api.js, components/)
docs/      ARCHITECTURE, DEPLOYMENT, EVALUATION, LINKEDIN_POST, DEMO_SCRIPT, screenshots/
```

## Screenshots

| | |
|---|---|
| ![Strategy](docs/screenshots/02-strategy.png) | ![Content](docs/screenshots/03-content.png) |
| ![Creatives](docs/screenshots/04-creatives.png) | ![Agent](docs/screenshots/05-agent-workspace.png) |

## Known limitations

Free hosting sleeps when idle and local image storage is not persistent (use a disk or object storage). There is no user authentication yet (the `users` collection is reserved). Rate limiting is in-memory, per instance.

## License
Image generation is built for Gemini and OpenAI image models. Because paid image-API access wasn't available, the demo uses the built-in placeholder renderer. Switching is one setting: IMAGE_PROVIDER=gemini or openai.
MIT
