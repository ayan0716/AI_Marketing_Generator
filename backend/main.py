from contextlib import asynccontextmanager
from datetime import datetime, timezone
from bson import ObjectId
from bson.errors import InvalidId
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import database
import llm
from config import get_settings
from content_routes import router as content_router
from fastapi.staticfiles import StaticFiles
import image_providers
import storage
from image_routes import router as image_router
import agent_service
from agent_routes import router as agent_router
from schemas import LANGUAGES, CampaignInput, Objective, Platform, Tone
@asynccontextmanager
async def lifespan(app: FastAPI):
    db = await database.connect()
    await agent_service.recover_interrupted(db)  # Phase 4: runs cut off by a restart are marked failed
    yield
    await database.disconnect()
app = FastAPI(title="AI Marketing Content Generator", version="4.0.0-phase4", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_list,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(content_router)  # Phase 2
app.include_router(image_router)  # Phase 3
app.include_router(agent_router)  # Phase 4: campaign agent
app.mount("/api/media", StaticFiles(directory=str(storage.root())), name="media")  # generated images
# ---------- helpers ----------
def _oid(value: str) -> ObjectId:
    try:
        return ObjectId(value)
    except (InvalidId, TypeError):
        raise HTTPException(status_code=404, detail="Campaign not found.")
def _ser(doc: dict) -> dict:
    out = {}
    for k, v in doc.items():
        key = "id" if k == "_id" else k
        out[key] = str(v) if isinstance(v, ObjectId) else (v.isoformat() if isinstance(v, datetime) else v)
    return out
@app.exception_handler(RequestValidationError)
async def validation_handler(_: Request, exc: RequestValidationError):
    errors = {}
    for e in exc.errors():
        field = str(e["loc"][-1]) if e["loc"] else "body"
        msg = e["msg"].removeprefix("Value error, ")
        errors.setdefault(field, msg)
    return JSONResponse(status_code=422, content={"detail": "Please fix the highlighted fields.", "errors": errors})
# ---------- routes ----------
@app.get("/api/health")
async def health():
    s = get_settings()
    await database.get_db().command("ping")
    return {"status": "ok", "database": "mongodb (mock)" if s.use_mock_db else "mongodb", "llm_provider": s.llm_provider,
            "image_provider": image_providers.provider_status()}
@app.get("/api/llm/test")
async def llm_test():
    """Verifies the first LLM API request works (Phase 1, Step 6)."""
    try:
        return await llm.ping()
    except llm.LLMError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM connection failed: {e}")
@app.get("/api/options")
async def options():
    return {
        "platforms": [p.value for p in Platform],
        "objectives": [o.value for o in Objective],
        "tones": [t.value for t in Tone],
        "languages": LANGUAGES,
    }
@app.post("/api/strategies", status_code=201)
async def create_strategy(data: CampaignInput):
    """Brief in -> structured marketing strategy out (saved to MongoDB)."""
    try:
        strategy, provider, model = await llm.generate_strategy(data)
    except llm.LLMError as e:
        raise HTTPException(status_code=502, detail=str(e))
    db = database.get_db()
    now = datetime.now(timezone.utc)
    product = await db.products.insert_one(
        {"name": data.product_name, "description": data.product_description, "created_at": now}
    )
    campaign_doc = {
        "product_id": product.inserted_id,
        "product_name": data.product_name,
        "product_description": data.product_description,
        "target_audience": data.target_audience,
        "platform": data.platform.value,
        "objective": data.objective.value,
        "tone": data.tone.value,
        "language": data.language,
        "status": "strategy_ready",
        "created_at": now,
    }
    campaign = await db.campaigns.insert_one(campaign_doc)
    strategy_doc = {
        "campaign_id": campaign.inserted_id,
        "data": strategy.model_dump(),
        "provider": provider,
        "model": model,
        "created_at": now,
    }
    sres = await db.strategies.insert_one(strategy_doc)
    return {
        "campaign": _ser({**campaign_doc, "_id": campaign.inserted_id, "product_id": product.inserted_id}),
        "strategy": _ser({**strategy_doc, "_id": sres.inserted_id, "campaign_id": campaign.inserted_id}),
    }
@app.get("/api/campaigns")
async def list_campaigns(limit: int = 50):
    db = database.get_db()
    cursor = db.campaigns.find({}, {"product_description": 0}).sort("created_at", -1).limit(min(limit, 100))
    return [_ser(c) async for c in cursor]
@app.get("/api/campaigns/{campaign_id}")
async def get_campaign(campaign_id: str):
    db = database.get_db()
    oid = _oid(campaign_id)
    campaign = await db.campaigns.find_one({"_id": oid})
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found.")
    strategy = await db.strategies.find_one({"campaign_id": oid})
    return {"campaign": _ser(campaign), "strategy": _ser(strategy) if strategy else None}
@app.delete("/api/campaigns/{campaign_id}", status_code=204)
async def delete_campaign(campaign_id: str):
    db = database.get_db()
    oid = _oid(campaign_id)
    res = await db.campaigns.delete_one({"_id": oid})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Campaign not found.")
    await db.strategies.delete_many({"campaign_id": oid})
    await db.contents.delete_many({"campaign_id": oid})
    await db.creatives.delete_many({"campaign_id": oid})  # Phase 3
    for name in ("agent_runs", "agent_assets", "agent_audit"):  # Phase 4
        await db[name].delete_many({"campaign_id": oid})
    storage.delete_campaign_files(campaign_id)