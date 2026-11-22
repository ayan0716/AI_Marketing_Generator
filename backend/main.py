import hashlib
import logging
import re
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import agent_service
import database
import image_providers
import llm
import observability as obs
import storage
from agent_routes import router as agent_router
from config import get_settings
from content_routes import router as content_router
from image_routes import router as image_router
from schemas import LANGUAGES, CampaignInput, Objective, Platform, Tone

VERSION = "5.0.0-phase5"

# ---------- Phase 5: logging + AI-call monitoring (Step 8) ----------
_boot = get_settings()
obs.setup_logging(_boot.log_level, _boot.log_json, _boot.log_file)
obs.instrument_providers(llm.PROVIDERS, image_providers.IMAGE_PROVIDERS, llm.active_model, image_providers.active_model)
log = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db = await database.connect()
    await db.campaigns.create_index("brief_hash")  # Phase 5: fast lookup for "same brief -> reuse the saved strategy"
    await agent_service.recover_interrupted(db)  # Phase 4: runs cut off by a restart are marked failed
    s = get_settings()
    log.info("started version=%s env=%s llm=%s image=%s db=%s", VERSION, s.environment, s.llm_provider,
             s.image_provider, "mock" if s.use_mock_db else s.mongodb_db)
    yield
    await database.disconnect()


app = FastAPI(
    title="AI Marketing Content Generator",
    version=VERSION,
    lifespan=lifespan,
    docs_url=None if _boot.is_production else "/docs",  # no public API explorer in production
    redoc_url=None,
    openapi_url=None if _boot.is_production else "/openapi.json",
)

_limiters: dict[int, obs.RateLimiter] = {}
_MAX_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")  # set by Render / Railway / nginx
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _is_free_mode() -> bool:
    s = get_settings()
    return s.llm_provider == "mock" and s.image_provider == "mock"  # nothing paid to protect


@app.middleware("http")
async def guard_and_observe(request: Request, call_next):
    """Request id, body-size limit, rate limit on AI endpoints, security headers, timing, crash capture."""
    s = get_settings()
    rid = request.headers.get("x-request-id", "")
    rid = rid if _MAX_ID.match(rid) else uuid.uuid4().hex[:12]
    token = obs.request_id_var.set(rid)
    path, method = request.url.path, request.method
    t0 = time.perf_counter()
    try:
        cl = request.headers.get("content-length", "")
        if cl.isdigit() and int(cl) > s.max_body_mb * 1024 * 1024:
            response = JSONResponse(status_code=413, content={
                "detail": f"The upload is too large (limit {s.max_body_mb} MB).", "request_id": rid})
        elif method == "POST" and s.rate_limit_per_minute > 0 and not _is_free_mode() and obs.EXPENSIVE.match(path):
            limiter = _limiters.setdefault(s.rate_limit_per_minute, obs.RateLimiter(s.rate_limit_per_minute))
            allowed, wait = limiter.check(_client_ip(request))
            if allowed:
                response = await call_next(request)
            else:
                log.warning("rate limit hit ip=%s path=%s", _client_ip(request), path)
                response = JSONResponse(
                    status_code=429, headers={"Retry-After": str(wait)},
                    content={"detail": f"Too many AI requests. Please wait {wait}s and try again.", "request_id": rid})
        else:
            try:
                response = await call_next(request)
            except Exception:  # a bug: log the stack trace, show the user a clean message
                log.exception("unhandled error on %s %s", method, path)
                response = JSONResponse(status_code=500, content={
                    "detail": "Something went wrong on our side. Please try again; if it keeps happening, "
                              f"quote reference {rid}.", "request_id": rid})
        ms = (time.perf_counter() - t0) * 1000
        if path.startswith("/api"):
            obs.metrics.record_request(method, path, response.status_code, ms)
            noisy = path.startswith(("/api/media", "/api/health"))
            level = logging.DEBUG if noisy else (logging.WARNING if response.status_code >= 400 else logging.INFO)
            log.log(level, "%s %s -> %s in %.0fms", method, path, response.status_code, ms)
        response.headers["X-Request-ID"] = rid
        for k, v in obs.SECURITY_HEADERS.items():
            response.headers.setdefault(k, v)
        if s.is_production:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response
    finally:
        obs.request_id_var.reset(token)


# Added AFTER the middleware above so CORS wraps it (429 / 500 answers still carry CORS headers)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_boot.cors_list,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID", "Retry-After"],
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


def brief_hash(data: CampaignInput) -> str:
    """Stable fingerprint of a brief (case / whitespace-insensitive). Same brief -> same hash."""
    parts = [data.product_name, data.product_description, data.target_audience,
             data.platform.value, data.objective.value, data.tone.value, data.language]
    canon = "|".join(" ".join(p.lower().split()) for p in parts)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


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
    return {"status": "ok", "version": VERSION, "environment": s.environment,
            "database": "mongodb (mock)" if s.use_mock_db else "mongodb", "llm_provider": s.llm_provider,
            "image_provider": image_providers.provider_status()}


@app.get("/api/metrics")
async def metrics(request: Request):
    """Basic monitoring: request counts, latency, AI call success/failure per provider, last failures (Step 8)."""
    s = get_settings()
    if s.admin_token:
        if request.headers.get("x-admin-token", "") != s.admin_token:
            raise HTTPException(status_code=403, detail="Admin token required (X-Admin-Token header).")
    elif s.is_production:
        raise HTTPException(status_code=403, detail="Set ADMIN_TOKEN to enable /api/metrics in production.")
    return obs.metrics.snapshot()


@app.get("/api/llm/test")
async def llm_test():
    """Verifies the first LLM API request works (Phase 1, Step 6)."""
    try:
        return await llm.ping()
    except llm.LLMError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM connection failed: {obs.redact(str(e))}")


@app.get("/api/options")
async def options():
    return {
        "platforms": [p.value for p in Platform],
        "objectives": [o.value for o in Objective],
        "tones": [t.value for t in Tone],
        "languages": LANGUAGES,
    }


@app.post("/api/strategies", status_code=201)
async def create_strategy(data: CampaignInput, fresh: bool = False):
    """Brief in -> structured marketing strategy out (saved to MongoDB).

    Phase 5 cost control: an identical brief inside STRATEGY_CACHE_HOURS returns the campaign that already exists
    (with everything generated for it so far) instead of paying for another LLM request. `?fresh=true` forces a new one.
    """
    s = get_settings()
    db = database.get_db()
    h = brief_hash(data)

    if not fresh and s.strategy_cache_hours > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=s.strategy_cache_hours)
        existing = await db.campaigns.find_one({"brief_hash": h}, sort=[("created_at", -1)])
        if existing:
            strategy = await db.strategies.find_one({"campaign_id": existing["_id"]})
            created = existing["created_at"]
            created = created.replace(tzinfo=timezone.utc) if created.tzinfo is None else created
            if strategy and strategy.get("provider") == s.llm_provider and created >= cutoff:
                log.info("strategy reused campaign=%s (no LLM call)", existing["_id"])
                return {"campaign": _ser(existing), "strategy": _ser(strategy), "reused": True}

    try:
        strategy, provider, model = await llm.generate_strategy(data)
    except llm.LLMError as e:
        raise HTTPException(status_code=502, detail=obs.redact(str(e)))
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
        "brief_hash": h,
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
        "reused": False,
    }


@app.get("/api/campaigns")
async def list_campaigns(limit: int = 50):
    db = database.get_db()
    cursor = db.campaigns.find({}, {"product_description": 0, "brief_hash": 0}).sort("created_at", -1).limit(min(limit, 100))
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


# ---------- Phase 5: serve the built frontend from the same service (one deployable unit) ----------
def _frontend_dir() -> Path | None:
    s = get_settings()
    candidates = [Path(s.frontend_dist)] if s.frontend_dist else [Path(__file__).resolve().parent.parent / "frontend" / "dist"]
    return next((p for p in candidates if (p / "index.html").is_file()), None)


_dist = _frontend_dir()
if _dist:
    _dist = _dist.resolve()
    if (_dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=str(_dist / "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found.")
        f = (_dist / full_path).resolve()
        if full_path and f.is_file() and _dist in f.parents:  # never serve anything outside dist/
            return FileResponse(f)
        return FileResponse(_dist / "index.html")  # client-side routing