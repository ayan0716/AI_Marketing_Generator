"""Phase 4 - the campaign agent.

One run = an ordered list of stages executed in the background while the UI polls its progress:

    strategy -> plan -> [approval] -> copy -> image_prompts -> visuals -> save

Nothing here is new generation logic: the stages call the Phase 1 strategy generator, the Phase 2 copy
generator and the Phase 3 prompt writer / image renderer, then store the results in the same collections the
manual studios use (so everything stays editable there). New in Phase 4: the planner (agent_planner), reel and
promo assets (agent_extras), run tracking, partial regeneration, approvals and export.

Failure model: only a failing strategy stops a run. A failing asset is recorded in `item_errors` and the other
assets continue; the run then ends as `completed_with_warnings` (or `failed` if nothing at all was produced).
"""
import asyncio
import json
import logging
from datetime import datetime, timezone

from bson import ObjectId
from fastapi import HTTPException
from pydantic import ValidationError

import agent_extras
import agent_guard as guard
import agent_planner
import content_routes as cr
import database
import image_routes as ir
import image_service as svc
import llm
from agent_schemas import (ASSETS, EXTRA_FIELDS, AgentRegenerateRequest, AgentRunRequest, Scope, asset_meta)
from content_schemas import ContentPlatform, GenerateContentRequest, RegenerateRequest
from image_schemas import CreativeFormat
from schemas import CampaignInput, Objective, Platform, Tone

log = logging.getLogger("agent")

ACTIVE = ("queued", "running", "awaiting_approval")
TERMINAL = ("completed", "completed_with_warnings", "failed", "cancelled")

LABELS = {
    "strategy": "Creating the marketing strategy",
    "plan": "Planning which assets to create",
    "approval": "Waiting for your approval",
    "copy": "Writing platform-specific copy",
    "image_prompts": "Writing image prompts",
    "visuals": "Generating visual creatives",
    "save": "Saving the campaign",
}
FULL_STAGES = ["copy", "image_prompts", "visuals", "save"]

_tasks: set[asyncio.Task] = set()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(v):
    return v.isoformat() if isinstance(v, datetime) else v


class StageFailed(Exception):
    """A stage that cannot continue (the run stops)."""


# ---------------------------------------------------------------- run tracking
class RunCtx:
    """In-memory view of one run document; `save()` persists progress for the polling UI."""

    def __init__(self, db, doc: dict):
        self.db, self.doc = db, doc
        self.mem: dict = {}          # prompts / product shared between stages of ONE execution
        self.ok_keys: set[str] = set()

    async def save(self):
        d = self.doc
        d["updated_at"] = _now()
        await self.db.agent_runs.update_one({"_id": d["_id"]}, {"$set": {
            k: d[k] for k in ("status", "steps", "item_errors", "warnings", "image_prompts", "error",
                              "campaign_id", "items", "updated_at")}})

    def _step(self, key):
        return next(s for s in self.doc["steps"] if s["key"] == key)

    async def start(self, key):
        s = self._step(key)
        s.update(status="running", started_at=_now())
        await self.save()

    async def finish(self, key, status="done", detail=None):
        s = self._step(key)
        s.update(status=status, detail=detail, finished_at=_now())
        await self.save()

    def warn(self, msg):
        if msg and msg not in self.doc["warnings"]:
            self.doc["warnings"].append(msg)

    def item_error(self, key, msg):
        label = ASSETS[key]["label"]
        prev = self.doc["item_errors"].get(key)
        text = f"{label}: {msg}"
        self.doc["item_errors"][key] = f"{prev} | {text}" if prev else text

    async def cancel_requested(self) -> bool:
        d = await self.db.agent_runs.find_one({"_id": self.doc["_id"]}, {"cancel_requested": 1})
        return bool(d and d.get("cancel_requested"))

    def skip_rest(self):
        for s in self.doc["steps"]:
            if s["status"] == "pending":
                s["status"] = "skipped"


def _launch(coro):
    t = asyncio.create_task(coro)
    _tasks.add(t)
    t.add_done_callback(_tasks.discard)


async def create_run(db, *, campaign_id, kind, scope, stages, items, options, target=None) -> dict:
    now = _now()
    doc = {
        "campaign_id": campaign_id, "kind": kind, "scope": scope, "target": target, "status": "queued",
        "steps": [{"key": k, "label": LABELS[k], "status": "pending", "detail": None,
                   "started_at": None, "finished_at": None} for k in stages],
        "items": items, "options": options, "item_errors": {}, "warnings": [], "image_prompts": {},
        "error": None, "cancel_requested": False, "created_at": now, "updated_at": now,
    }
    doc["_id"] = (await db.agent_runs.insert_one(doc)).inserted_id
    return doc


def run_public(d: dict) -> dict:
    return {
        "id": str(d["_id"]), "campaign_id": str(d["campaign_id"]) if d.get("campaign_id") else None,
        "kind": d["kind"], "scope": d["scope"], "target": d.get("target"), "status": d["status"],
        "steps": [{**s, "started_at": _iso(s.get("started_at")), "finished_at": _iso(s.get("finished_at"))}
                  for s in d["steps"]],
        "items": d.get("items", []), "item_errors": d.get("item_errors", {}), "warnings": d.get("warnings", []),
        "image_prompts": d.get("image_prompts", {}), "error": d.get("error"),
        "options": {k: v for k, v in d.get("options", {}).items() if k != "assets"},
        "created_at": _iso(d["created_at"]), "updated_at": _iso(d["updated_at"]),
    }


async def get_run(db, run_id: ObjectId) -> dict:
    d = await db.agent_runs.find_one({"_id": run_id})
    if not d:
        raise HTTPException(status_code=404, detail="Run not found.")
    return d


async def active_run(db, campaign_id: ObjectId) -> dict | None:
    return await db.agent_runs.find_one({"campaign_id": campaign_id, "status": {"$in": list(ACTIVE)}})


async def recover_interrupted(db) -> int:
    """After a server restart, runs that were 'running' can never finish: mark them failed."""
    n = 0
    async for d in db.agent_runs.find({"status": {"$in": ["queued", "running"]}}):
        for s in d["steps"]:
            if s["status"] == "running":
                s["status"] = "failed"
            elif s["status"] == "pending":
                s["status"] = "skipped"
        await db.agent_runs.update_one({"_id": d["_id"]}, {"$set": {
            "status": "failed", "steps": d["steps"], "updated_at": _now(),
            "error": "The server restarted while this run was in progress. Start it again."}})
        n += 1
    return n


# ---------------------------------------------------------------- helpers
async def _load(ctx: RunCtx):
    db, oid = ctx.db, ctx.doc["campaign_id"]
    campaign = await db.campaigns.find_one({"_id": oid})
    strategy = await db.strategies.find_one({"campaign_id": oid})
    if not campaign or not strategy:
        raise StageFailed("The campaign or its strategy no longer exists.")
    return campaign, strategy["data"]


async def _set_approval(db, oid, key, status="pending"):
    await db.campaigns.update_one({"_id": oid}, {"$set": {f"approvals.{key}": status}})


def _tally(ok: int, failed: int, what: str) -> tuple[str, str]:
    total = ok + failed
    if total == 0:
        return "skipped", f"Nothing to do for {what}."
    if ok == 0:
        return "failed", f"All {total} failed - see the details below."
    if failed:
        return "warning", f"{ok} of {total} succeeded."
    return "done", f"{ok} of {total} done."


# ---------------------------------------------------------------- stages
async def stage_strategy(ctx: RunCtx, brief):
    db = ctx.db
    guard.require("llm.generate")
    new = ctx.doc["campaign_id"] is None
    try:
        if new:
            data = CampaignInput.model_validate(brief)
        else:
            c = await db.campaigns.find_one({"_id": ctx.doc["campaign_id"]})
            if not c:
                raise StageFailed("The campaign no longer exists.")
            data = CampaignInput(
                product_name=c["product_name"], product_description=c.get("product_description", ""),
                target_audience=c["target_audience"], platform=Platform(c["platform"]),
                objective=Objective(c["objective"]), tone=Tone(c["tone"]), language=c.get("language", "English"))
    except ValidationError as e:
        raise StageFailed("The saved brief is no longer valid: " + str(e.errors()[0]["msg"]))
    try:
        strategy, provider, model = await llm.generate_strategy(data)
    except llm.LLMError as e:
        raise StageFailed(str(e))
    except Exception as e:
        raise StageFailed(f"Strategy generation failed: {e}")
    guard.require("db.write")
    now = _now()
    if new:
        product = await db.products.insert_one(
            {"name": data.product_name, "description": data.product_description, "created_at": now})
        campaign = await db.campaigns.insert_one({
            "product_id": product.inserted_id, "product_name": data.product_name,
            "product_description": data.product_description, "target_audience": data.target_audience,
            "platform": data.platform.value, "objective": data.objective.value, "tone": data.tone.value,
            "language": data.language, "status": "strategy_ready", "source": "agent", "created_at": now})
        await db.strategies.insert_one({"campaign_id": campaign.inserted_id, "data": strategy.model_dump(),
                                        "provider": provider, "model": model, "created_at": now})
        ctx.doc["campaign_id"] = campaign.inserted_id
    else:
        await db.strategies.update_one(
            {"campaign_id": ctx.doc["campaign_id"]},
            {"$set": {"data": strategy.model_dump(), "provider": provider, "model": model, "created_at": now}},
            upsert=True)
    await ctx.save()  # the UI can now load the campaign while later stages run
    return "done", strategy.campaign_idea.title


async def stage_plan(ctx: RunCtx, brief):
    campaign, strategy = await _load(ctx)
    plan = await agent_planner.plan_campaign(campaign, strategy, ctx.doc["options"].get("assets"))
    keys = [i["key"] for i in plan["items"]]
    ctx.doc["items"] = keys
    guard.require("db.write")
    await ctx.db.campaigns.update_one({"_id": campaign["_id"]}, {"$set": {
        "plan": {"summary": plan["summary"], "items": plan["items"], "source": plan["source"],
                 "warning": plan["warning"], "created_at": _now()},
        "approvals": {k: "pending" for k in keys}, "stale": False}})
    ctx.warn(plan["warning"])
    return "done", f"{len(keys)} assets: " + ", ".join(ASSETS[k]["label"] for k in keys)


async def stage_copy(ctx: RunCtx, brief):
    db = ctx.db
    campaign, strategy = await _load(ctx)
    oid, cid, n = campaign["_id"], str(campaign["_id"]), ctx.doc["options"]["variations"]
    ok = failed = 0
    for key in ctx.doc["items"]:  # sequential on purpose: gentle on provider rate limits
        a = ASSETS[key]
        try:
            guard.require("llm.generate")
            if a["kind"] == "content":
                platform = ContentPlatform(a["content_platform"])
                if await db.contents.find_one({"campaign_id": oid, "platform": platform.value}):
                    await cr.regenerate_content(cid, platform, RegenerateRequest(variations=n))
                else:
                    await cr.generate_content(cid, GenerateContentRequest(platforms=[platform], variations=n))
            else:
                data, provider, model = await agent_extras.generate_extra(key, campaign, strategy)
                guard.require("db.write")
                await db.agent_assets.update_one(
                    {"campaign_id": oid, "key": key},
                    {"$set": {"kind": a["kind"], "data": data, "provider": provider, "model": model,
                              "updated_at": _now()}, "$setOnInsert": {"created_at": _now()}}, upsert=True)
            await _set_approval(db, oid, key)
            ctx.ok_keys.add(key)
            ok += 1
        except guard.ExternalActionBlocked:
            raise
        except HTTPException as e:
            ctx.item_error(key, str(e.detail))
            failed += 1
        except agent_extras.ExtraError as e:
            ctx.item_error(key, str(e))
            failed += 1
        except Exception as e:
            log.exception("copy for %s failed", key)
            ctx.item_error(key, f"Unexpected error ({e.__class__.__name__}).")
            failed += 1
    return _tally(ok, failed, "copy")


def _format_items(ctx: RunCtx):
    return [(k, CreativeFormat(ASSETS[k]["creative_format"])) for k in ctx.doc["items"] if ASSETS[k]["creative_format"]]


async def stage_image_prompts(ctx: RunCtx, brief):
    opts = ctx.doc["options"]
    if not opts.get("generate_images", True):
        return "skipped", "Image generation was turned off for this run."
    fmts = _format_items(ctx)
    if not fmts:
        return "skipped", "None of the selected assets needs an image."
    db = ctx.db
    campaign, strategy = await _load(ctx)
    oid = campaign["_id"]
    product = await ir._load_product(campaign) if opts.get("use_product_image", True) else None
    pw = ir._provider_warnings(product)
    if pw:
        product = None
        for w in pw:
            ctx.warn(w)
    ctx.mem["product"], ctx.mem["concepts"] = product, {}
    ok = failed = 0
    for key, fmt in fmts:
        try:
            guard.require("llm.generate")
            hint = await ir._content_hint(db, oid, fmt)  # keeps the visual consistent with the written copy
            concepts, warns = await svc.generate_concepts(fmt, campaign, strategy, opts["concepts"],
                                                           product is not None, hint)
        except guard.ExternalActionBlocked:
            raise
        except svc.PromptError as e:
            ctx.item_error(key, str(e))
            failed += 1
            continue
        except Exception as e:
            log.exception("image prompts for %s failed", key)
            ctx.item_error(key, f"Could not write image prompts ({e.__class__.__name__}).")
            failed += 1
            continue
        ctx.mem["concepts"][key] = (fmt, concepts, warns)
        ctx.doc["image_prompts"][key] = [
            {"name": c["name"], "style_label": c["style_label"], "image_prompt": c["image_prompt"][:1200]}
            for c in concepts]
        ok += 1
        await ctx.save()
    return _tally(ok, failed, "image prompts")


async def stage_visuals(ctx: RunCtx, brief):
    pending = ctx.mem.get("concepts") or {}
    if not pending:
        return "skipped", "No image prompts to render."
    guard.require("image.generate")
    db = ctx.db
    oid, cid = ctx.doc["campaign_id"], str(ctx.doc["campaign_id"])
    product, state = ctx.mem.get("product"), svc.RunState()
    ok = failed = 0
    for key, (fmt, concepts, warns) in pending.items():
        rendered = await asyncio.gather(*(svc.render_concept(fmt, cid, c, product, state) for c in concepts))
        ready = [c for c in rendered if c["status"] == "ready"]
        if not ready:
            old = await db.creatives.find_one({"campaign_id": oid, "format": fmt.value})
            ctx.item_error(key, rendered[0]["error"]["message"] + (" The previous images were kept." if old else ""))
            failed += 1
            continue
        warnings = list(warns)
        if len(ready) < len(rendered):
            warnings.append(f"{len(rendered) - len(ready)} of {len(rendered)} images failed - "
                            "open the Visual Studio and use Retry on the failed card.")
        guard.require("db.write")
        old = await db.creatives.find_one({"campaign_id": oid, "format": fmt.value})
        now = _now()
        await db.creatives.update_one(
            {"campaign_id": oid, "format": fmt.value},
            {"$set": {"concepts": rendered, "selected_concept_id": ready[0]["id"], "warnings": warnings,
                      "updated_at": now}, "$setOnInsert": {"created_at": now}}, upsert=True)
        ir._purge(old)
        await db.campaigns.update_one({"_id": oid}, {"$set": {"status": "creatives_ready"}})
        await _set_approval(db, oid, key)
        ctx.ok_keys.add(key)
        ok += 1
        await ctx.save()
    return _tally(ok, failed, "visuals")


async def stage_save(ctx: RunCtx, brief):
    db, oid = ctx.db, ctx.doc["campaign_id"]
    keys, errs = ctx.doc["items"], ctx.doc["item_errors"]
    campaign = await db.campaigns.find_one({"_id": oid}) or {}
    plan_keys = [i["key"] for i in (campaign.get("plan") or {}).get("items", [])]
    stage_keys = [s["key"] for s in ctx.doc["steps"]]
    update = {"last_run_id": ctx.doc["_id"]}
    if ctx.ok_keys:
        update["status"] = "campaign_ready"
    if "copy" in stage_keys and plan_keys and set(keys) >= set(plan_keys):
        update["stale"] = False
    elif stage_keys == ["strategy", "save"] and plan_keys:
        update["stale"] = True  # copy and images were written for the previous strategy
    await db.campaigns.update_one({"_id": oid}, {"$set": update})
    if keys and not ctx.ok_keys:
        ctx.doc["status"] = "failed"
        ctx.doc["error"] = "No asset could be generated. See the details for each asset below."
    elif errs or ctx.doc["warnings"]:
        ctx.doc["status"] = "completed_with_warnings"
    else:
        ctx.doc["status"] = "completed"
    return "done", "Campaign saved to your history. Nothing was published."


HANDLERS = {"strategy": stage_strategy, "plan": stage_plan, "copy": stage_copy,
            "image_prompts": stage_image_prompts, "visuals": stage_visuals, "save": stage_save}


# ---------------------------------------------------------------- executor
async def execute(run_id: ObjectId, brief: dict | None = None):
    db = database.get_db()
    doc = await db.agent_runs.find_one({"_id": run_id})
    if not doc:
        return
    ctx = RunCtx(db, doc)
    try:
        doc["status"] = "running"
        await ctx.save()
        for step in doc["steps"]:
            if step["status"] != "pending":
                continue
            key = step["key"]
            if await ctx.cancel_requested():
                ctx.skip_rest()
                doc["status"] = "cancelled"
                return
            if key == "approval":
                step.update(status="waiting", detail="Review the plan below, then approve to continue.")
                doc["status"] = "awaiting_approval"
                return
            await ctx.start(key)
            try:
                status, detail = await HANDLERS[key](ctx, brief)
            except StageFailed as e:
                await ctx.finish(key, "failed", str(e))
                ctx.skip_rest()
                doc["status"], doc["error"] = "failed", str(e)
                return
            await ctx.finish(key, status, detail)
    except guard.ExternalActionBlocked as e:
        ctx.skip_rest()
        doc["status"], doc["error"] = "failed", str(e)
    except Exception as e:
        log.exception("agent run crashed")
        ctx.skip_rest()
        for s in doc["steps"]:
            if s["status"] == "running":
                s["status"] = "failed"
        doc["status"], doc["error"] = "failed", f"Unexpected error ({e.__class__.__name__}). Please try again."
    finally:
        await ctx.save()


# ---------------------------------------------------------------- starting runs
async def start_full_run(db, data: AgentRunRequest) -> dict:
    options = {"variations": data.variations, "concepts": data.concepts, "generate_images": data.generate_images,
               "use_product_image": True, "assets": data.assets, "require_plan_approval": data.require_plan_approval}
    stages = ["strategy", "plan"] + (["approval"] if data.require_plan_approval else []) + FULL_STAGES
    doc = await create_run(db, campaign_id=None, kind="full", scope="campaign", stages=stages, items=[], options=options)
    brief = data.model_dump(mode="json", include=set(CampaignInput.model_fields))
    _launch(execute(doc["_id"], brief))
    return doc


async def start_regenerate(db, oid: ObjectId, body: AgentRegenerateRequest) -> dict:
    campaign = await db.campaigns.find_one({"_id": oid})
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found.")
    if await active_run(db, oid):
        raise HTTPException(status_code=409, detail="This campaign already has a run in progress. Wait for it or cancel it.")
    plan_keys = [i["key"] for i in (campaign.get("plan") or {}).get("items", [])]
    scope = body.scope
    if scope in (Scope.caption, Scope.image):
        if not body.target or body.target not in plan_keys:
            raise HTTPException(status_code=422, detail="Choose one of this campaign's planned assets.")
        if scope == Scope.image and not ASSETS[body.target]["creative_format"]:
            raise HTTPException(status_code=422, detail=f"{ASSETS[body.target]['label']} has no image to regenerate.")
    if scope != Scope.strategy and scope not in (Scope.plan, Scope.campaign) and not plan_keys:
        raise HTTPException(status_code=409, detail="This campaign has no asset plan yet. Use 'Plan assets' first.")

    if scope == Scope.caption:
        stages, items = ["copy", "save"], [body.target]
    elif scope == Scope.image:
        stages, items = ["image_prompts", "visuals", "save"], [body.target]
    elif scope == Scope.plan:
        stages, items = ["plan"] + FULL_STAGES, []
    elif scope == Scope.strategy and not body.cascade:
        stages, items = ["strategy", "save"], []
    else:  # whole campaign, or strategy + cascade
        if not plan_keys:
            stages, items = ["strategy", "plan"] + FULL_STAGES, []
        else:
            stages, items = ["strategy"] + FULL_STAGES, plan_keys
    options = {"variations": body.variations, "concepts": body.concepts, "generate_images": True,
               "use_product_image": True}
    doc = await create_run(db, campaign_id=oid, kind="regenerate", scope=scope.value, stages=stages, items=items,
                           options=options, target=body.target)
    _launch(execute(doc["_id"], None))
    return doc


async def continue_run(db, run_id: ObjectId, assets: list[str] | None) -> dict:
    doc = await get_run(db, run_id)
    if doc["status"] != "awaiting_approval":
        raise HTTPException(status_code=409, detail="This run is not waiting for approval.")
    oid = doc["campaign_id"]
    campaign = await db.campaigns.find_one({"_id": oid})
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found.")
    plan = campaign.get("plan") or {}
    keys = doc["items"]
    if assets is not None:  # the user edited the asset list while reviewing the plan
        existing = {i["key"]: i for i in plan.get("items", [])}
        items = []
        for k in assets:
            items.append(existing.get(k) or {**asset_meta(k), "reason": agent_planner._REASONS[k]})
        keys = [i["key"] for i in items]
        await db.campaigns.update_one({"_id": oid}, {"$set": {
            "plan.items": items, "plan.source": "user" if set(keys) != set(existing) else plan.get("source", "ai"),
            "approvals": {k: "pending" for k in keys}}})
    step = next(s for s in doc["steps"] if s["key"] == "approval")
    step.update(status="done", detail="Plan approved by you.", finished_at=_now())
    await db.agent_runs.update_one({"_id": run_id}, {"$set": {
        "steps": doc["steps"], "items": keys, "status": "running", "updated_at": _now()}})
    _launch(execute(run_id, None))
    return await get_run(db, run_id)


async def cancel_run(db, run_id: ObjectId) -> dict:
    doc = await get_run(db, run_id)
    if doc["status"] == "awaiting_approval":
        for s in doc["steps"]:
            if s["status"] in ("pending", "waiting"):
                s["status"] = "skipped"
        await db.agent_runs.update_one({"_id": run_id}, {"$set": {
            "status": "cancelled", "steps": doc["steps"], "updated_at": _now()}})
    elif doc["status"] in ("queued", "running"):
        await db.agent_runs.update_one({"_id": run_id}, {"$set": {"cancel_requested": True}})
    else:
        raise HTTPException(status_code=409, detail="This run has already finished.")
    return await get_run(db, run_id)


# ---------------------------------------------------------------- reading: workspace, history
def _campaign_public(c: dict) -> dict:
    return {"id": str(c["_id"]), "product_name": c["product_name"], "product_description": c.get("product_description", ""),
            "target_audience": c.get("target_audience"), "platform": c["platform"], "objective": c["objective"],
            "tone": c["tone"], "language": c.get("language", "English"), "status": c.get("status"),
            "stale": bool(c.get("stale")), "created_at": _iso(c.get("created_at")),
            "has_product_image": bool(c.get("product_image"))}


def _extra_public(d: dict) -> dict:
    return {"data": d["data"], "provider": d.get("provider"), "model": d.get("model"),
            "updated_at": _iso(d.get("updated_at"))}


async def build_workspace(db, oid: ObjectId) -> dict:
    campaign = await db.campaigns.find_one({"_id": oid})
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found.")
    strategy = await db.strategies.find_one({"campaign_id": oid})
    plan = campaign.get("plan")
    approvals = campaign.get("approvals") or {}
    runs = [d async for d in db.agent_runs.find({"campaign_id": oid}).sort("created_at", -1).limit(1)]
    last = runs[0] if runs else None
    errors = (last or {}).get("item_errors", {})
    contents = {d["platform"]: d async for d in db.contents.find({"campaign_id": oid})}
    creatives = {d["format"]: d async for d in db.creatives.find({"campaign_id": oid})}
    extras = {d["key"]: d async for d in db.agent_assets.find({"campaign_id": oid})}
    items = []
    for p in (plan or {}).get("items", []):
        k, a = p["key"], ASSETS[p["key"]]
        items.append({
            **asset_meta(k), "reason": p.get("reason"), "approval": approvals.get(k, "pending"),
            "extra_fields": EXTRA_FIELDS.get(k),
            "content": cr._public(contents[a["content_platform"]]) if a["content_platform"] in contents else None,
            "extra": _extra_public(extras[k]) if k in extras else None,
            "creative": ir._public(creatives[a["creative_format"]]) if a["creative_format"] in creatives else None,
            "error": errors.get(k),
        })
    active = await active_run(db, oid)
    return {
        "campaign": _campaign_public(campaign),
        "strategy": {"data": strategy["data"], "provider": strategy.get("provider"), "model": strategy.get("model")} if strategy else None,
        "plan": {"summary": plan["summary"], "source": plan["source"], "warning": plan.get("warning")} if plan else None,
        "items": items,
        "approved_count": sum(1 for i in items if i["approval"] == "approved"),
        "active_run": run_public(active) if active else None,
        "last_run": run_public(last) if last else None,
    }


def _thumb(doc: dict | None) -> str | None:
    if not doc:
        return None
    pub = ir._public(doc)
    sel = next((c for c in pub["concepts"] if c["id"] == pub["selected_concept_id"]), None)
    return sel["image"]["url"] if sel and sel.get("image") else None


async def build_history(db, q: str | None = None, limit: int = 100) -> list[dict]:
    out = []
    async for c in db.campaigns.find({}).sort("created_at", -1).limit(min(limit, 200)):
        if q:
            hay = " ".join(str(c.get(k, "")) for k in ("product_name", "platform", "objective", "tone")).lower()
            if q.lower() not in hay:
                continue
        oid = c["_id"]
        strat = await db.strategies.find_one({"campaign_id": oid})
        plan_items = (c.get("plan") or {}).get("items", [])
        approvals = c.get("approvals") or {}
        n_copy = await db.contents.count_documents({"campaign_id": oid})
        n_img = await db.creatives.count_documents({"campaign_id": oid})
        n_extra = await db.agent_assets.count_documents({"campaign_id": oid})
        thumb = None
        for p in plan_items:
            fmt = ASSETS[p["key"]]["creative_format"]
            thumb = _thumb(await db.creatives.find_one({"campaign_id": oid, "format": fmt})) if fmt else None
            if thumb:
                break
        if not thumb:
            thumb = _thumb(await db.creatives.find_one({"campaign_id": oid}))
        run = await active_run(db, oid)
        out.append({
            "id": str(oid), "product_name": c["product_name"], "platform": c["platform"], "objective": c["objective"],
            "tone": c["tone"], "language": c.get("language", "English"), "status": c.get("status"),
            "created_at": _iso(c.get("created_at")), "stale": bool(c.get("stale")), "source": c.get("source", "manual"),
            "title": ((strat or {}).get("data", {}).get("campaign_idea", {}) or {}).get("title"),
            "asset_count": len(plan_items), "copy_count": n_copy + n_extra, "image_count": n_img,
            "approved_count": sum(1 for p in plan_items if approvals.get(p["key"]) == "approved"),
            "thumbnail": thumb, "active_run_status": run["status"] if run else None,
        })
    return out


# ---------------------------------------------------------------- approvals + export
async def set_approvals(db, oid: ObjectId, approvals: dict[str, str]) -> dict:
    campaign = await db.campaigns.find_one({"_id": oid})
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found.")
    keys = {i["key"] for i in (campaign.get("plan") or {}).get("items", [])}
    bad = [k for k in approvals if k not in keys]
    if bad:
        raise HTTPException(status_code=422, detail=f"Not part of this campaign's plan: {', '.join(bad)}")
    ws = await build_workspace(db, oid)
    ready = {i["key"] for i in ws["items"] if i["content"] or i["extra"] or i["creative"]}
    empty = [k for k, v in approvals.items() if v == "approved" and k not in ready]
    if empty:
        raise HTTPException(status_code=422, detail="Only generated assets can be approved: " + ", ".join(ASSETS[k]["label"] for k in empty))
    await db.campaigns.update_one({"_id": oid}, {"$set": {f"approvals.{k}": v for k, v in approvals.items()}})
    await db.agent_audit.insert_one({"campaign_id": oid, "action": "approval", "detail": approvals, "at": _now()})
    return await build_workspace(db, oid)


def _selected_copy(item: dict) -> dict | None:
    c = item["content"]
    if c and c["variations"]:
        v = c["variations"][min(c["selected_index"], len(c["variations"]) - 1)]
        return {k: x for k, x in v.items() if k != "id"}
    return item["extra"]["data"] if item["extra"] else None


def _selected_image(item: dict) -> dict | None:
    cr_ = item["creative"]
    if not cr_:
        return None
    sel = next((c for c in cr_["concepts"] if c["id"] == cr_["selected_concept_id"]), None)
    img = sel and sel.get("image")
    return {"concept": sel["name"], "url": img["url"], "width": img["width"], "height": img["height"],
            "prompt": img["prompt"]} if img else None


def _md_value(v) -> str:
    if isinstance(v, list):
        if v and isinstance(v[0], dict):
            return "\n" + "\n".join(f"  {i + 1}. " + " | ".join(f"{k}: {x}" for k, x in f.items() if x != "") for i, f in enumerate(v))
        return " ".join(map(str, v))
    return str(v)


async def export_campaign(db, oid: ObjectId, keys: list[str] | None, fmt: str) -> dict:
    ws = await build_workspace(db, oid)
    approved = [i for i in ws["items"] if i["approval"] == "approved" and (keys is None or i["key"] in keys)]
    if not approved:
        raise HTTPException(status_code=409, detail="Approve at least one asset before exporting.")
    assets = [{"key": i["key"], "label": i["label"], "copy": _selected_copy(i), "image": _selected_image(i)} for i in approved]
    c, s = ws["campaign"], (ws["strategy"] or {}).get("data", {})
    note = ("Drafts approved by you. Nothing has been published: post these manually on each platform.")
    name = c["product_name"].replace(" ", "-").lower()
    exported_at = _now().isoformat()
    if fmt == "json":
        content = json.dumps({"campaign": {k: c[k] for k in ("product_name", "platform", "objective", "tone", "language")},
                              "strategy": s, "assets": assets, "exported_at": exported_at, "note": note},
                             ensure_ascii=False, indent=2)
        filename = f"{name}-campaign.json"
    else:
        lines = [f"# {c['product_name']} - campaign export", "",
                 f"*{c['platform']} · {c['objective']} · {c['tone']} · {c['language']}*", "", f"> {note}", ""]
        idea = s.get("campaign_idea", {})
        if idea:
            lines += [f"## Campaign idea: {idea.get('title', '')}", idea.get("concept", ""), ""]
        for a in assets:
            lines += [f"## {a['label']}", ""]
            for k, v in (a["copy"] or {}).items():
                if v not in ("", None, []):
                    lines += [f"**{k.replace('_', ' ').title()}:** {_md_value(v)}", ""]
            if a["image"]:
                lines += ["", f"Image ({a['image']['width']}x{a['image']['height']}): {a['image']['url']}",
                          f"Image prompt: {a['image']['prompt']}"]
            lines.append("")
        content = "\n".join(lines)
        filename = f"{name}-campaign.md"
    await db.agent_audit.insert_one({"campaign_id": oid, "action": "export", "detail": {
        "assets": [a["key"] for a in assets], "format": fmt}, "at": _now()})
    return {"format": fmt, "filename": filename, "content": content, "included": [a["key"] for a in assets], "note": note}
