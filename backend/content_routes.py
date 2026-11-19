"""Phase 2 API: generate / list / regenerate / select platform content."""

import asyncio
import json
from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, HTTPException

import database
from content_llm import ContentError, generate_variations
from content_prompts import ANGLES
from content_schemas import (
    PLATFORM_META,
    ContentPlatform,
    GenerateContentRequest,
    RegenerateRequest,
    SelectRequest,
)

router = APIRouter(prefix="/api", tags=["content"])
_gate = asyncio.Semaphore(2)  # be gentle with provider rate limits


def _oid(value: str) -> ObjectId:
    try:
        return ObjectId(value)
    except (InvalidId, TypeError):
        raise HTTPException(status_code=404, detail="Campaign not found.")


def _public(doc: dict) -> dict:
    return {
        "id": str(doc["_id"]),
        "campaign_id": str(doc["campaign_id"]),
        "platform": doc["platform"],
        "label": PLATFORM_META[ContentPlatform(doc["platform"])]["label"],
        "variations": doc["variations"],
        "selected_index": doc.get("selected_index", 0),
        "provider": doc.get("provider"),
        "model": doc.get("model"),
        "warnings": doc.get("warnings", []),
        "updated_at": doc["updated_at"].isoformat() if isinstance(doc.get("updated_at"), datetime) else None,
    }


async def _load(campaign_id: str):
    db = database.get_db()
    oid = _oid(campaign_id)
    campaign = await db.campaigns.find_one({"_id": oid})
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found.")
    strategy = await db.strategies.find_one({"campaign_id": oid})
    if not strategy:
        raise HTTPException(status_code=409, detail="Generate a marketing strategy first (Phase 1).")
    return db, oid, campaign, strategy["data"]


def _free_angle(existing: list[dict]) -> int:
    """Index of the first writing angle not used by the existing variations."""
    used = {v.get("angle") for v in existing}
    return next((i for i, a in enumerate(ANGLES) if a not in used), len(existing))


def _flat(v: dict) -> str:
    return json.dumps({k: x for k, x in v.items() if k in ("hook", "headline", "video_title", "introduction")}, ensure_ascii=False)


@router.get("/content/platforms")
async def content_platforms():
    return [{"key": p.value, **m} for p, m in PLATFORM_META.items()]


@router.get("/campaigns/{campaign_id}/content")
async def list_content(campaign_id: str):
    db = database.get_db()
    oid = _oid(campaign_id)
    docs = [d async for d in db.contents.find({"campaign_id": oid})]
    return {"items": [_public(d) for d in docs]}


@router.post("/campaigns/{campaign_id}/content", status_code=201)
async def generate_content(campaign_id: str, body: GenerateContentRequest):
    """Strategy -> platform-specific content, one structured result per platform.

    One platform failing never blocks the others: each result is {content} or {error}.
    """
    db, oid, campaign, strategy = await _load(campaign_id)
    platforms = list(dict.fromkeys(body.platforms))

    async def one(platform: ContentPlatform):
        try:
            async with _gate:
                variations, provider, model, warnings = await generate_variations(
                    platform, campaign, strategy, body.variations
                )
        except ContentError as e:
            return platform.value, {"error": str(e)}
        now = datetime.now(timezone.utc)
        await db.contents.update_one(
            {"campaign_id": oid, "platform": platform.value},
            {
                "$set": {
                    "variations": variations, "selected_index": 0, "provider": provider,
                    "model": model, "warnings": warnings, "updated_at": now,
                },
                "$setOnInsert": {"created_at": now},
            },
            upsert=True,
        )
        doc = await db.contents.find_one({"campaign_id": oid, "platform": platform.value})
        return platform.value, {"content": _public(doc)}

    results = dict(await asyncio.gather(*(one(p) for p in platforms)))
    if any("content" in r for r in results.values()):
        await db.campaigns.update_one({"_id": oid}, {"$set": {"status": "content_ready"}})
    elif all("error" in r for r in results.values()):
        raise HTTPException(status_code=502, detail=next(iter(results.values()))["error"])
    return {"results": results}


@router.post("/campaigns/{campaign_id}/content/{platform}/regenerate")
async def regenerate_content(campaign_id: str, platform: ContentPlatform, body: RegenerateRequest):
    """Regenerate every variation of a platform, or just one (body.index)."""
    db, oid, campaign, strategy = await _load(campaign_id)
    doc = await db.contents.find_one({"campaign_id": oid, "platform": platform.value})
    existing = doc["variations"] if doc else []
    single = body.index is not None and doc is not None
    if single and body.index >= len(existing):
        raise HTTPException(status_code=422, detail="That variation does not exist.")
    try:
        async with _gate:
            if single:
                avoid = [_flat(v) for v in existing]
                new, provider, model, warnings = await generate_variations(
                    platform, campaign, strategy, 1, avoid=avoid, angle_offset=_free_angle([v for i, v in enumerate(existing) if i != body.index])
                )
                variations = list(existing)
                variations[body.index] = new[0]
            else:
                variations, provider, model, warnings = await generate_variations(
                    platform, campaign, strategy, body.variations,
                    avoid=[_flat(v) for v in existing], angle_offset=_free_angle(existing),
                )
    except ContentError as e:
        raise HTTPException(status_code=502, detail=str(e))
    now = datetime.now(timezone.utc)
    selected = doc.get("selected_index", 0) if (doc and single) else 0
    await db.contents.update_one(
        {"campaign_id": oid, "platform": platform.value},
        {
            "$set": {"variations": variations, "selected_index": selected, "provider": provider, "model": model,
                     "warnings": warnings, "updated_at": now},
            "$setOnInsert": {"created_at": now},
        },
        upsert=True,
    )
    await db.campaigns.update_one({"_id": oid}, {"$set": {"status": "content_ready"}})
    return _public(await db.contents.find_one({"campaign_id": oid, "platform": platform.value}))


@router.put("/campaigns/{campaign_id}/content/{platform}/select")
async def select_variation(campaign_id: str, platform: ContentPlatform, body: SelectRequest):
    db = database.get_db()
    oid = _oid(campaign_id)
    doc = await db.contents.find_one({"campaign_id": oid, "platform": platform.value})
    if not doc:
        raise HTTPException(status_code=404, detail="No content generated for this platform yet.")
    if body.index >= len(doc["variations"]):
        raise HTTPException(status_code=422, detail="That variation does not exist.")
    await db.contents.update_one({"_id": doc["_id"]}, {"$set": {"selected_index": body.index}})
    doc["selected_index"] = body.index
    return _public(doc)
