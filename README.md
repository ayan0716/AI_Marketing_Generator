# Phase 4 - AI Marketing Campaign Agent & Automation

One campaign brief now drives the whole workflow automatically:

```
brief -> strategy -> AI campaign planner -> [your approval, optional] -> platform copy
      -> image prompts -> generated visuals -> saved campaign (history)
```

Phase 4 **reuses** the earlier phases (Phase 1 strategy, Phase 2 copy, Phase 3 prompts + image API) and stores results
in the same collections, so the Content Studio and Visual Studio still open every agent campaign.

## What was added (by step)

| Step | Where |
|---|---|
| 1 Workflow from the brief | `POST /api/agent/runs`, `agent_service.py` (background run, "Campaign agent" page) |
| 2 Strategy first | `strategy` stage (Phase 1 `llm.generate_strategy`) |
| 3 Platform copy from the strategy | `copy` stage (Phase 2 generator) + `agent_extras.py` (reel concept, promo caption) |
| 4 Image prompts per asset | `image_prompts` stage (Phase 3 prompt writer); shown in the run panel |
| 5 Visuals via the image API | `visuals` stage (Phase 3 providers) |
| 6 No manual stepping | one click; live progress timeline (polls `GET /api/agent/runs/{id}`) |
| 7 AI campaign planner | `agent_planner.py`: the LLM picks assets from a catalog, output is validated, rule-based fallback. Instagram -> post, story, reel concept, promo caption |
| 8 Campaign history | `GET /api/agent/history`, `GET /api/agent/campaigns/{id}/workspace`, redesigned History page (thumbnail, counts, search) |
| 9 Regeneration at every level | `POST /api/agent/campaigns/{id}/regenerate` with `scope` = `strategy` / `caption` / `image` / `campaign` (plus `plan` for campaigns made in Phases 1-3) |
| 10 Safeguards | `agent_guard.py` allow-list, plan-approval pause, per-asset approval, confirmed export, audit log |

## Safeguards
- The agent has **no** connection to any social platform, email or ad account. Its actions are an allow-list
  (`llm.generate`, `image.generate`, `db.read/write`, `storage.write`); `publish_post`, `send_email`, `launch_ad`... raise `ExternalActionBlocked`.
- "Pause for my approval after planning" stops the run before any copy or image credits are used.
- Every asset starts as *pending*. Regenerating an asset resets it to *pending*. Only *approved* assets can be exported.
- Export needs `confirm: true`, returns a file for **manual** posting, and is written to the `agent_audit` collection.
- Limits: 6 assets, 3 variations, 3 image concepts per run; one active run per campaign.
- The "Publish to platforms" button is intentionally disabled.

## Failure behaviour
Only a failing strategy stops a run. A failing asset is reported on its own card and the rest continue
(`completed_with_warnings`). A failed image regeneration keeps the previous images. Runs interrupted by a server restart are marked failed.

## Run it
No new environment variables or packages. Same commands as before:
```
cd backend && uvicorn main:app --reload      # http://127.0.0.1:8000
cd frontend && npm run dev                   # http://localhost:5173
cd backend && pytest                         # 78 tests (28 new for Phase 4)
```

## Screenshots to take
1. Campaign agent page (brief + Agent options + safeguard note)
2. Run in progress (timeline with the running step)
3. Plan review (tick "Pause for my approval", then show the asset checklist)
4. Finished workspace (strategy card, plan sentence, asset cards with copy + image)
5. Image prompts panel expanded in the run card
6. Regenerate a single caption / single image, and the strategy-only "strategy changed" banner
7. Approve & export panel with the disabled Publish button
8. History page with thumbnails, counts and search