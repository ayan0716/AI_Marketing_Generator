"""Phase 4 API: campaign agent runs, workspace, partial regeneration, approvals, export, history."""
from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, HTTPException

import agent_guard
import agent_service as svc
import database
from agent_schemas import (ASSET_KEYS, AgentRegenerateRequest, AgentRunRequest, ApprovalRequest, ContinueRequest,
                           ExportRequest, asset_meta)

router = APIRouter(prefix="/api/agent", tags=["agent"])


def _oid(value: str, what: str = "Campaign") -> ObjectId:
    try:
        return ObjectId(value)
    except (InvalidId, TypeError):
        raise HTTPException(status_code=404, detail=f"{what} not found.")


@router.get("/assets")
async def asset_catalog():
    """Everything the planner can choose from (used by the plan review screen)."""
    return {"assets": [asset_meta(k) for k in ASSET_KEYS], "max_assets": agent_guard.MAX_ASSETS_PER_RUN}


@router.get("/safeguards")
async def safeguards():
    return {"safeguards": agent_guard.SAFEGUARDS, "external_publishing": "disabled"}


@router.get("/history")
async def history(q: str | None = None):
    return {"items": await svc.build_history(database.get_db(), q)}


# ---------------------------------------------------------------- runs
@router.post("/runs", status_code=201)
async def start_run(body: AgentRunRequest):
    """Brief in -> a background run that creates strategy, plan, copy, image prompts and visuals."""
    return svc.run_public(await svc.start_full_run(database.get_db(), body))


@router.get("/runs/{run_id}")
async def get_run(run_id: str):
    return svc.run_public(await svc.get_run(database.get_db(), _oid(run_id, "Run")))


@router.post("/runs/{run_id}/continue")
async def continue_run(run_id: str, body: ContinueRequest):
    """Approve the plan (optionally with an edited asset list) so the paused run can generate."""
    return svc.run_public(await svc.continue_run(database.get_db(), _oid(run_id, "Run"), body.assets))


@router.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: str):
    return svc.run_public(await svc.cancel_run(database.get_db(), _oid(run_id, "Run")))


# ---------------------------------------------------------------- campaign workspace
@router.get("/campaigns/{campaign_id}/workspace")
async def workspace(campaign_id: str):
    return await svc.build_workspace(database.get_db(), _oid(campaign_id))


@router.post("/campaigns/{campaign_id}/regenerate", status_code=202)
async def regenerate(campaign_id: str, body: AgentRegenerateRequest):
    """Step 9: regenerate only the strategy, one caption, one image, or the complete campaign."""
    return svc.run_public(await svc.start_regenerate(database.get_db(), _oid(campaign_id), body))


@router.put("/campaigns/{campaign_id}/approvals")
async def approvals(campaign_id: str, body: ApprovalRequest):
    return await svc.set_approvals(database.get_db(), _oid(campaign_id), body.approvals)


@router.post("/campaigns/{campaign_id}/export")
async def export(campaign_id: str, body: ExportRequest):
    """The ONLY way content leaves the app: approved assets, explicit confirmation, written to the audit log."""
    if not body.confirm:
        raise HTTPException(status_code=422, detail="Please confirm the export. Nothing is published automatically.")
    return await svc.export_campaign(database.get_db(), _oid(campaign_id), body.assets, body.format)


@router.get("/campaigns/{campaign_id}/audit")
async def audit(campaign_id: str):
    db, oid = database.get_db(), _oid(campaign_id)
    rows = [d async for d in db.agent_audit.find({"campaign_id": oid}).sort("at", -1).limit(50)]
    return {"items": [{"action": r["action"], "detail": r["detail"], "at": r["at"].isoformat()} for r in rows]}
