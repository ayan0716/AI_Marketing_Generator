# Evaluation and improvements (Steps 1-4)

## How to run it
```bash
cd backend
python scripts/evaluate.py            # offline pipeline + automatic quality checks (free)
python scripts/evaluate.py --live     # real LLM from backend/.env (uses API calls)
python scripts/evaluate.py --base-url https://<your-app>.onrender.com   # the deployed app
```
The script covers 12 briefs: e-commerce, education, restaurants, software, clothing and real estate, with different audiences, objectives (sales, leads, launch, engagement, awareness), tones and platforms (Instagram, Facebook, LinkedIn, TikTok, YouTube, Google Ads). It writes `docs/evaluation_report.md` and `docs/evaluation_results.json`.

**Do a `--live` run, then fill in the "Manual review" table in the report** (relevance, specificity, tone, image match, 1-5). Automatic checks find repetition and invented facts; only you can judge creativity. Paste your real scores and 2-3 example outputs into the section below.

## Failure modes to look for, and what was changed

| Problem | How it shows up | Fix in Phase 5 |
|---|---|---|
| Repetitive | Selling points / content types that restate each other; near-identical variations | `strategy_quality` detects word-set similarity; one retry names the exact duplicates. Content variations already use different writing angles + an "avoid" list |
| Generic | "game-changer", "revolutionary", same strategy for a cafe and a SaaS | Banned-filler rule, buzzword check, **industry playbooks** detected from product name + description |
| Irrelevant / ungrounded | Strategy never mentions the real product | Grounding check (product name or real description words must appear) |
| Invented facts | "boost sales by 300%", made-up prices | Prompt rule + check for numbers that are not in the brief |
| Contradictions | Same word in `words_to_use` and `words_to_avoid` | Overlap check |
| Wrong KPIs / formats | Awareness campaign measured by conversions; long text for X | Per-objective and per-platform guidance blocks in the prompt |
| Weak CTA | A sentence instead of an action | CTA length / duplicate check, "2-6 word imperative" rule |
| Invalid JSON | Markdown fences, truncated JSON | Existing: JSON mode, fence stripping, schema validation, one retry |
| Poor images | Text artefacts, product not shown | Existing: product photo reference, per-image revision, retry; check manually in `--live` review |

## Results
Offline run (mock providers, checks the pipeline and the rules, not creativity): see `docs/evaluation_report.md`.

Live run: _paste summary here (success rate, quality-gate pass rate before/after prompt changes, median latency, examples of a weak and an improved output)._
