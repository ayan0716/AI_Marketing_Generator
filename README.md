# MarketMind AI - Phase 3: AI Image Generation & Creative Generation

Phases 1 (strategy) and 2 (platform content) are unchanged. Phase 3 adds a visual-creative workflow.

## Run
```
cd backend && pip install -r requirements.txt && uvicorn main:app --reload      # http://127.0.0.1:8000
cd frontend && npm install && npm run dev                                        # http://localhost:5173
```
Keep your existing `backend/.env`. Add (optional - default is offline `mock`):
```
IMAGE_PROVIDER=gemini        # or openai / mock
GEMINI_IMAGE_MODEL=gemini-2.5-flash-image
```
Restart the backend after editing `.env`. Tests: `cd backend && pytest` (50 tests).

## Phase 3 step -> code
| Step | Where |
|---|---|
| 1-2 Strategy -> platform-specific image prompts | `image_prompts.py` (art-director prompt + `build_final_prompt`), `image_schemas.py` (`FORMAT_SPECS`: aspect, size, audience, composition rules) |
| 3 Image API integration | `image_providers.py` (Gemini, OpenAI, offline mock) |
| 4 Multiple concepts per campaign | `image_service.generate_concepts` - 1-4 concepts, each a different style direction |
| 5 Formats | Instagram Post 1:1, Story 9:16, LinkedIn 1.91:1, Facebook Ad 4:5, YouTube Thumbnail 16:9 |
| 6 Product image | `PUT /api/campaigns/{id}/product-image`; sent as reference image to Gemini / OpenAI edits; composited by mock |
| 7 Preview + select | `CreativeStudio.jsx`, `CreativeCard.jsx` (grid, lightbox, select, download) |
| 8 Regenerate with changes | "Edit & regenerate" (background / style / composition / tone + free text); every version is kept |
| 9 Errors | `ImageError` kinds: rate_limit, quota, auth, config, safety, invalid_response, timeout, network, server, bad_request. Retries with backoff, per-image Retry, previous image kept on failed revision |

## New API
`GET /api/creatives/formats` · `GET|POST /api/campaigns/{id}/creatives` · `POST .../creatives/{format}/{concept}/regenerate` ·
`POST .../retry` · `PUT .../creatives/{format}/select` · `PUT .../{concept}/version` · `GET|PUT|DELETE /api/campaigns/{id}/product-image`

Images are stored on disk in `backend/storage/` (served at `/api/media/...`); MongoDB keeps metadata in the new `creatives` collection.