"""Phase 3 API: product image upload, creative generation, preview data, revision, selection."""

import asyncio
import base64
import binascii
import io
import re
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from PIL import Image

import database
import image_providers as ip
import image_service as svc
import storage
from config import get_settings
from content_routes import _load, _oid
from image_schemas import (
    FORMAT_SPECS, CreativeFormat, GenerateCreativesRequest, ProductImageUpload, ReviseRequest,
    SelectCreativeRequest, VersionRequest, format_meta,
)
from image_prompts import STYLES

router = APIRouter(prefix="/api", tags=["creatives"])

# ---------------- helpers ----------------
def _http_error(e: ip.ImageError) -> HTTPException:
    code = {"rate_limit": 429, "safety": 422}.get(e.kind, 502)
    headers = {"Retry-After": str(int(e.retry_after))} if e.kind == "rate_limit" and e.retry_after else None
    return HTTPException(status_code=code, detail=e.message, headers=headers)

def _version_public(v: dict) -> dict:
    return {"id": v["id"], "url": storage.url_for(v["file"]), "width": v["width"], "height": v["height"],
            "instruction": v.get("instruction"), "provider": v["provider"], "model": v["model"],
            "used_product": v.get("used_product", False),
            "created_at": v["created_at"].isoformat() if isinstance(v.get("created_at"), datetime) else None}

_CONCEPT_KEYS = ("id", "name", "style_label", "concept_summary", "visual_style", "composition", "background", "lighting",
                 "color_palette", "product_placement", "mood", "text_overlay", "status", "error", "current_version")

def _concept_public(c: dict) -> dict:
    out = {k: c.get(k) for k in _CONCEPT_KEYS}
    versions = [_version_public(v) for v in c.get("versions", [])]
    cur = next((v for v in c.get("versions", []) if v["id"] == c.get("current_version")), None)
    out["versions"] = versions
    out["image"] = {**_version_public(cur), "prompt": cur["prompt"]} if cur else None
    return out

def _public(doc: dict) -> dict:
    fmt = CreativeFormat(doc["format"])
    return {
        "id": str(doc["_id"]), "campaign_id": str(doc["campaign_id"]), "format": fmt.value,
        "label": FORMAT_SPECS[fmt]["label"], "spec": format_meta(fmt),
        "concepts": [_concept_public(c) for c in doc["concepts"]],
        "selected_concept_id": doc.get("selected_concept_id"),
        "warnings": doc.get("warnings", []),
        "updated_at": doc["updated_at"].isoformat() if isinstance(doc.get("updated_at"), datetime) else None,
    }

async def _load_product(campaign: dict) -> ip.ProductRef | None:
    meta = campaign.get("product_image")
    if not meta:
        return None
    data = storage.read_bytes(meta["file"])
    return ip.ProductRef(data, "image/png") if data else None

async def _content_hint(db, oid, fmt: CreativeFormat) -> dict | None:
    """Selected Phase 2 copy for the matching platform keeps the visual consistent with the text."""
    doc = await db.contents.find_one({"campaign_id": oid, "platform": FORMAT_SPECS[fmt]["content_platform"]})
    if not doc or not doc.get("variations"):
        return None
    v = doc["variations"][min(doc.get("selected_index", 0), len(doc["variations"]) - 1)]
    keys = ("hook", "headline", "video_title", "main_message", "primary_text", "thumbnail_concept", "call_to_action")
    hint = {k: v[k][:200] for k in keys if isinstance(v.get(k), str) and v[k]}
    if fmt == CreativeFormat.instagram_story and v.get("frames"):
        hint["story_frames"] = [f["visual"][:120] for f in v["frames"]]
    return hint or None

def _purge(doc: dict | None) -> None:
    for c in (doc or {}).get("concepts", []):
        for v in c.get("versions", []):
            storage.delete_file(v.get("file"))

def _provider_warnings(product) -> list[str]:
    s = get_settings()
    if product and s.image_provider not in ip.PRODUCT_CAPABLE:
        return [f"The '{s.image_provider}' image provider cannot use a product photo; images were generated without it."]
    return []

async def _get_doc(db, oid, fmt: CreativeFormat):
    doc = await db.creatives.find_one({"campaign_id": oid, "format": fmt.value})
    if not doc:
        raise HTTPException(status_code=404, detail="No creatives generated for this format yet.")
    return doc

def _find_concept(doc: dict, concept_id: str) -> dict:
    c = next((c for c in doc["concepts"] if c["id"] == concept_id), None)
    if not c:
        raise HTTPException(status_code=404, detail="That concept does not exist.")
    return c

# ---------------- metadata ----------------
@router.get("/creatives/formats")
async def creative_formats():
    return {"formats": [format_meta(f) for f in CreativeFormat], **ip.provider_status()}

# ---------------- product image (Step 6) ----------------
def _decode_upload(data_url: str) -> Image.Image:
    m = re.match(r"^data:(image/(?:png|jpeg|jpg|webp));base64,(.+)$", data_url.strip(), re.S)
    if not m:
        raise HTTPException(status_code=422, detail="Upload a PNG, JPG or WebP image.")
    limit = get_settings().max_upload_mb * 1024 * 1024
    if len(m.group(2)) * 3 // 4 > limit:
        raise HTTPException(status_code=413, detail=f"The image is larger than {get_settings().max_upload_mb} MB.")
    try:
        raw = base64.b64decode(m.group(2), validate=True)
        im = Image.open(io.BytesIO(raw))
        im.load()
    except (binascii.Error, ValueError, OSError, Image.DecompressionBombError):
        raise HTTPException(status_code=422, detail="That file is not a readable image.")
    if min(im.size) < 128:
        raise HTTPException(status_code=422, detail="The image is too small (minimum 128 px on each side).")
    return im

def _product_public(meta: dict | None) -> dict:
    if not meta:
        return {"product_image": None}
    return {"product_image": {"url": storage.url_for(meta["file"]), "width": meta["width"], "height": meta["height"]}}

@router.get("/campaigns/{campaign_id}/product-image")
async def get_product_image(campaign_id: str):
    db = database.get_db()
    c = await db.campaigns.find_one({"_id": _oid(campaign_id)})
    if not c:
        raise HTTPException(status_code=404, detail="Campaign not found.")
    return _product_public(c.get("product_image"))

@router.put("/campaigns/{campaign_id}/product-image")
async def upload_product_image(campaign_id: str, body: ProductImageUpload):
    db = database.get_db()
    oid = _oid(campaign_id)
    c = await db.campaigns.find_one({"_id": oid})
    if not c:
        raise HTTPException(status_code=404, detail="Campaign not found.")
    im = _decode_upload(body.data_url)
    im.thumbnail((1536, 1536))
    buf = io.BytesIO()
    im.convert("RGBA").save(buf, "PNG")
    storage.delete_file((c.get("product_image") or {}).get("file"))
    rel = storage.save_bytes(f"products/{campaign_id}", f"{uuid.uuid4().hex[:8]}.png", buf.getvalue())
    meta = {"file": rel, "width": im.width, "height": im.height}
    await db.campaigns.update_one({"_id": oid}, {"$set": {"product_image": meta}})
    return _product_public(meta)

@router.delete("/campaigns/{campaign_id}/product-image")
async def delete_product_image(campaign_id: str):
    db = database.get_db()
    oid = _oid(campaign_id)
    c = await db.campaigns.find_one({"_id": oid})
    if not c:
        raise HTTPException(status_code=404, detail="Campaign not found.")
    storage.delete_file((c.get("product_image") or {}).get("file"))
    await db.campaigns.update_one({"_id": oid}, {"$unset": {"product_image": ""}})
    return {"product_image": None}

# ---------------- creatives ----------------
@router.get("/campaigns/{campaign_id}/creatives")
async def list_creatives(campaign_id: str):
    db = database.get_db()
    oid = _oid(campaign_id)
    docs = [d async for d in db.creatives.find({"campaign_id": oid})]
    return {"items": [_public(d) for d in docs]}

@router.post("/campaigns/{campaign_id}/creatives", status_code=201)
async def generate_creatives(campaign_id: str, body: GenerateCreativesRequest):
    """Strategy -> image prompts -> image API -> several visual concepts per format.

    One format failing never blocks the others; one concept failing is stored on the concept (Retry in the UI).
    """
    db, oid, campaign, strategy = await _load(campaign_id)
    formats = list(dict.fromkeys(body.formats))
    product = await _load_product(campaign) if body.use_product_image else None
    common_warnings = _provider_warnings(product)
    if common_warnings:
        product = None
    state = svc.RunState()

    async def one(fmt: CreativeFormat):
        try:
            hint = await _content_hint(db, oid, fmt)
            concepts, warnings = await svc.generate_concepts(
                fmt, campaign, strategy, body.concepts, product is not None, hint)
        except svc.PromptError as e:
            return fmt.value, {"error": str(e), "kind": "prompt"}
        rendered = await asyncio.gather(*(svc.render_concept(fmt, campaign_id, c, product, state) for c in concepts))
        ready = [c for c in rendered if c["status"] == "ready"]
        if not ready:
            err = rendered[0]["error"]
            return fmt.value, {"error": err["message"], "kind": err["kind"], "retry_after": err.get("retry_after")}
        failed = len(rendered) - len(ready)
        if failed:
            warnings.append(f"{failed} of {len(rendered)} {FORMAT_SPECS[fmt]['label']} images failed - use Retry on the failed card.")
        old = await db.creatives.find_one({"campaign_id": oid, "format": fmt.value})
        now = datetime.now(timezone.utc)
        await db.creatives.update_one(
            {"campaign_id": oid, "format": fmt.value},
            {"$set": {"concepts": rendered, "selected_concept_id": ready[0]["id"], "warnings": warnings + common_warnings,
                      "updated_at": now}, "$setOnInsert": {"created_at": now}},
            upsert=True)
        _purge(old)
        return fmt.value, {"creatives": _public(await db.creatives.find_one({"campaign_id": oid, "format": fmt.value}))}

    results = dict(await asyncio.gather(*(one(f) for f in formats)))
    if any("creatives" in r for r in results.values()):
        await db.campaigns.update_one({"_id": oid}, {"$set": {"status": "creatives_ready"}})
        return {"results": results}
    kinds = {r["kind"] for r in results.values()}
    first = next(iter(results.values()))
    if kinds == {"rate_limit"}:
        ra = first.get("retry_after")
        raise HTTPException(status_code=429, detail=first["error"], headers={"Retry-After": str(ra)} if ra else None)
    raise HTTPException(status_code=422 if kinds == {"safety"} else 502, detail=first["error"])

async def _rerender(campaign_id: str, fmt: CreativeFormat, concept_id: str, instructions: str | None, category: str):
    db, oid, campaign, _ = await _load(campaign_id)
    doc = await _get_doc(db, oid, fmt)
    concept = _find_concept(doc, concept_id)
    product = await _load_product(campaign)
    if product and get_settings().image_provider not in ip.PRODUCT_CAPABLE:
        product = None
    prompt = concept["image_prompt"]
    if instructions:
        prompt = await svc.revise_prompt(fmt, prompt, instructions, category)
    try:
        v = await svc.render_version(fmt, campaign_id, concept, prompt, product, svc.RunState(), instructions)
    except ip.ImageError as e:
        if instructions is None:  # a failed retry: record the latest error on the card
            concept["error"] = e.to_dict()
            concept["status"] = "failed" if not concept.get("versions") else concept["status"]
            await db.creatives.update_one({"_id": doc["_id"]}, {"$set": {"concepts": doc["concepts"]}})
        raise _http_error(e)  # on a revision the previous image stays untouched
    concept["image_prompt"] = prompt
    concept["versions"] = (concept.get("versions", []) + [v])
    while len(concept["versions"]) > svc.MAX_VERSIONS:  # drop the oldest version that is not displayed
        drop = next(x for x in concept["versions"] if x["id"] != v["id"])
        concept["versions"].remove(drop)
        storage.delete_file(drop["file"])
    concept.update(current_version=v["id"], status="ready", error=None)
    await db.creatives.update_one({"_id": doc["_id"]}, {"$set": {
        "concepts": doc["concepts"], "updated_at": datetime.now(timezone.utc)}})
    return _public(await db.creatives.find_one({"_id": doc["_id"]}))

@router.post("/campaigns/{campaign_id}/creatives/{fmt}/{concept_id}/regenerate")
async def regenerate_creative(campaign_id: str, fmt: CreativeFormat, concept_id: str, body: ReviseRequest):
    """Step 8: regenerate one visual with modified instructions (background, style, composition, tone ...)."""
    return await _rerender(campaign_id, fmt, concept_id, body.instructions, body.category)

@router.post("/campaigns/{campaign_id}/creatives/{fmt}/{concept_id}/retry")
async def retry_creative(campaign_id: str, fmt: CreativeFormat, concept_id: str):
    """Re-run the same prompt (used after a failed generation)."""
    return await _rerender(campaign_id, fmt, concept_id, None, "other")

@router.put("/campaigns/{campaign_id}/creatives/{fmt}/select")
async def select_creative(campaign_id: str, fmt: CreativeFormat, body: SelectCreativeRequest):
    db = database.get_db()
    oid = _oid(campaign_id)
    doc = await _get_doc(db, oid, fmt)
    c = _find_concept(doc, body.concept_id)
    if c["status"] != "ready":
        raise HTTPException(status_code=422, detail="Only a successfully generated image can be selected.")
    await db.creatives.update_one({"_id": doc["_id"]}, {"$set": {"selected_concept_id": c["id"]}})
    doc["selected_concept_id"] = c["id"]
    return _public(doc)

@router.put("/campaigns/{campaign_id}/creatives/{fmt}/{concept_id}/version")
async def use_version(campaign_id: str, fmt: CreativeFormat, concept_id: str, body: VersionRequest):
    """Go back to an earlier version of a regenerated image."""
    db = database.get_db()
    oid = _oid(campaign_id)
    doc = await _get_doc(db, oid, fmt)
    c = _find_concept(doc, concept_id)
    if not any(v["id"] == body.version_id for v in c.get("versions", [])):
        raise HTTPException(status_code=404, detail="That version does not exist.")
    c["current_version"] = body.version_id
    await db.creatives.update_one({"_id": doc["_id"]}, {"$set": {"concepts": doc["concepts"]}})
    return _public(doc)
