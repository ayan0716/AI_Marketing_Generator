<<<<<<< HEAD
# MarketMind AI - AI Marketing Content Generator (Phase 1)

Full-stack GenAI app with a modern landing page, 4 switchable themes (Blue, Green, Orange, Midnight) and a dashboard UI: **React (Vite)** frontend, **FastAPI** backend, **MongoDB** database, pluggable **LLM** (Claude / OpenAI / Gemini / mock).

Phase 1 turns a product + campaign brief into a **structured marketing strategy** (campaign idea, target audience,
key selling points, content tone, call-to-action, suggested content types, success metrics) that later phases use to generate content.

## Structure
```
backend/    FastAPI app
  main.py      REST endpoints + validation error handler
  schemas.py   Pydantic input validation + strategy schema
  prompts.py   Structured strategy prompt
  llm.py       LLM client (anthropic | openai | gemini | mock), JSON parsing + retry
  database.py  MongoDB (Motor) + indexes
  test_api.py  Pytest tests
frontend/   React UI (form, validation, strategy view, history)
docker-compose.yml   Optional local MongoDB
```

## Run it
### 1. Backend
```bash
cd backend
python -m venv venv && source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # then edit .env (see below)
uvicorn main:app --reload --port 8000
```
Edit `.env`:
- **Database:** set `MONGODB_URI` (MongoDB Atlas string, or `mongodb://localhost:27017` after `docker compose up -d`).
  No MongoDB yet? Set `USE_MOCK_DB=true` for an in-memory database.
- **LLM:** set `LLM_PROVIDER` (`anthropic`, `openai`, `gemini`) and the matching `*_API_KEY`.
  Gemini has a free tier. `LLM_PROVIDER=mock` works with no key.

### 2. Frontend
```bash
cd frontend
npm install
npm run dev        # http://localhost:5173
```

### 3. Verify
- Click **Test LLM connection** in the sidebar (calls `GET /api/llm/test`) - this is the "first API request" check.
- Fill the form (or **Fill sample**) and generate a strategy.
- Tests: `cd backend && pytest`
- API docs: http://localhost:8000/docs

## API
| Method | Path | Purpose |
|---|---|---|
| GET | /api/health | DB + provider status |
| GET | /api/llm/test | Verify LLM API works |
| GET | /api/options | Form options |
| POST | /api/strategies | Brief -> strategy (saved) |
| GET | /api/campaigns | History |
| GET/DELETE | /api/campaigns/{id} | Open / delete |

## MongoDB collections
`users`, `products`, `campaigns`, `strategies` (JSON strategy + provider/model), `contents` (reserved for Phase 2).
=======
# ayan-khuram-084bb8-generative-ai-dev

Welcome, Ayan Khuram! 👋

This is your private repository for **Generative AI** at Big Brains Learning.

## What to do with this repo

- Clone this repository to your local machine and use it to manage and submit your codebase for this project.
- Commit your work regularly as you progress — this repo is where the Big Brains team reviews your code.
- Push your changes here so your mentors can track your progress and give feedback.

```bash
git clone https://github.com/Big-Brains-Learning/ayan-khuram-084bb8-generative-ai-dev.git
```

## Branches

A `dev` branch has already been created for you — please do your day-to-day development work there (or in your own feature branches off of it) rather than committing straight to `main`.

## Code review

The Big Brains team will review your code directly in this repository. Make sure your commits are pushed here so your submissions and progress are visible.

Good luck, and happy coding!
>>>>>>> f9b5946c781a65e47305ea17a6061f8d6d399ed6
