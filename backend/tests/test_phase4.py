"""Phase 4 tests: planner, automatic workflow, plan approval, history, regeneration at every level,
approvals / export safeguards and failure paths."""
import asyncio
import json
import time

import pytest
from fastapi.testclient import TestClient

import agent_extras
import agent_guard as guard
import agent_planner
import agent_service
import image_providers as ip
import llm
from agent_schemas import ASSETS, PLATFORM_DEFAULTS
from config import get_settings
from main import app
from tests.test_phase1 import VALID

RUN = {**VALID, "variations": 2, "concepts": 2}
def _camp(platform, objective):
    return {"product_name": "EcoSip Bottle", "target_audience": "students", "platform": platform,
            "objective": objective, "tone": "Friendly", "language": "English"}


INSTAGRAM_KEYS = ["instagram_post", "instagram_story", "instagram_reel", "promo_caption"]


@pytest.fixture(autouse=True)
def _restore():
    yield
    get_settings.cache_clear()


def wait(c, run_id, timeout=40):
    end = time.time() + timeout
    while time.time() < end:
        r = c.get(f"/api/agent/runs/{run_id}").json()
        if r["status"] not in ("queued", "running"):
            return r
        time.sleep(0.05)
    raise AssertionError("run did not finish: " + json.dumps(c.get(f"/api/agent/runs/{run_id}").json()))


def full_run(c, **extra):
    r = c.post("/api/agent/runs", json={**RUN, **extra})
    assert r.status_code == 201, r.text
    return wait(c, r.json()["id"])


def ws(c, cid):
    return c.get(f"/api/agent/campaigns/{cid}/workspace").json()


def item(w, key):
    return next(i for i in w["items"] if i["key"] == key)


def regen(c, cid, **body):
    r = c.post(f"/api/agent/campaigns/{cid}/regenerate", json=body)
    assert r.status_code == 202, r.text
    return wait(c, r.json()["id"])


# ---------- Step 7: planner ----------
def test_catalog_and_safeguards_endpoints():
    with TestClient(app) as c:
        cat = c.get("/api/agent/assets").json()
        assert {a["key"] for a in cat["assets"]} == set(ASSETS) and cat["max_assets"] == 6
        sg = c.get("/api/agent/safeguards").json()
        assert sg["external_publishing"] == "disabled" and len(sg["safeguards"]) >= 5


def test_default_plan_for_instagram_matches_the_brief_example():
    keys = agent_planner.default_keys({"platform": "Instagram", "objective": "Sales / Conversions"})
    assert keys == ["instagram_post", "instagram_story", "instagram_reel", "promo_caption"]
    for platform, defaults in PLATFORM_DEFAULTS.items():
        assert defaults and all(k in ASSETS for k in defaults)
    assert agent_planner.default_keys({"platform": "LinkedIn", "objective": "Brand Awareness"})[0] == "linkedin_post"


def test_parse_plan_rejects_garbage_and_unknown_keys():
    assert agent_planner.parse_plan("nope")[1] == []
    s, items, problems = agent_planner.parse_plan(json.dumps({"summary": "x", "assets": [
        {"key": "instagram_post", "reason": "r"}, {"key": "tiktok_dance"}, {"key": "instagram_post"}, "promo_caption"]}))
    assert [i["key"] for i in items] == ["instagram_post", "promo_caption"] and len(problems) == 1


def test_planner_falls_back_when_ai_plan_is_unusable(monkeypatch):
    async def bad(system, user, max_tokens):
        return "I think you should post a lot!"
    monkeypatch.setattr(llm, "PROVIDERS", {"fake": bad})
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    get_settings.cache_clear()
    plan = asyncio.run(agent_planner.plan_campaign(_camp("Facebook", "Engagement"), {}))
    assert plan["source"] == "fallback" and plan["warning"] and [i["key"] for i in plan["items"]] == ["facebook_ad", "promo_caption"]


def test_planner_uses_valid_ai_plan(monkeypatch):
    async def good(system, user, max_tokens):
        return json.dumps({"summary": "Video first.", "assets": [{"key": "youtube_video", "reason": "Search traffic."}]})
    monkeypatch.setattr(llm, "PROVIDERS", {"fake": good})
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    get_settings.cache_clear()
    plan = asyncio.run(agent_planner.plan_campaign(_camp("YouTube", "Brand Awareness"), {}))
    assert plan["source"] == "ai" and plan["items"][0]["reason"] == "Search traffic." and plan["summary"] == "Video first."


# ---------- Steps 1-6: the automatic workflow ----------
def test_full_workflow_runs_every_step_automatically():
    with TestClient(app) as c:
        run = full_run(c)
        assert run["status"] == "completed", run
        assert [s["key"] for s in run["steps"]] == ["strategy", "plan", "copy", "image_prompts", "visuals", "save"]
        assert all(s["status"] == "done" for s in run["steps"])
        cid = run["campaign_id"]
        w = ws(c, cid)
        assert [i["key"] for i in w["items"]] == INSTAGRAM_KEYS
        assert w["plan"]["source"] == "rules" and w["strategy"]["data"]["campaign_idea"]["title"]
        post, story, reel, promo = (item(w, k) for k in INSTAGRAM_KEYS)
        assert len(post["content"]["variations"]) == 2 and len(story["content"]["variations"][0]["frames"]) >= 3
        assert reel["extra"]["data"]["scenes"] and promo["extra"]["data"]["headline"]
        assert post["creative"]["concepts"][0]["image"]["url"].startswith("/api/media/creatives/")
        assert story["creative"]["spec"]["aspect"] == "9:16"
        assert reel["creative"] is None and promo["creative"] is None  # text-only assets
        assert set(run["image_prompts"]) == {"instagram_post", "instagram_story"}
        assert len(run["image_prompts"]["instagram_post"]) == 2
        assert all(i["approval"] == "pending" for i in w["items"]) and w["approved_count"] == 0
        assert w["campaign"]["status"] == "campaign_ready" and w["active_run"] is None
        # the existing Phase 2 / 3 studios see the very same data
        assert len(c.get(f"/api/campaigns/{cid}/content").json()["items"]) == 2
        assert len(c.get(f"/api/campaigns/{cid}/creatives").json()["items"]) == 2


def test_manual_asset_override_and_images_off():
    with TestClient(app) as c:
        run = full_run(c, assets=["linkedin_post", "promo_caption"], generate_images=False)
        assert run["status"] == "completed"
        steps = {s["key"]: s for s in run["steps"]}
        assert steps["image_prompts"]["status"] == "skipped" and steps["visuals"]["status"] == "skipped"
        w = ws(c, run["campaign_id"])
        assert [i["key"] for i in w["items"]] == ["linkedin_post", "promo_caption"] and w["plan"]["source"] == "user"
        assert item(w, "linkedin_post")["creative"] is None


def test_run_validation():
    with TestClient(app) as c:
        r = c.post("/api/agent/runs", json={**RUN, "product_name": "", "variations": 9, "assets": ["tiktok_dance"]})
        assert r.status_code == 422
        errs = r.json()["errors"]
        assert {"product_name", "variations", "assets"} <= set(errs)
        assert c.post("/api/agent/runs", json={**RUN, "assets": []}).status_code == 422
        assert c.post("/api/agent/runs", json={**RUN, "assets": list(ASSETS) + ["x"]}).status_code == 422
        assert c.get("/api/agent/runs/zzz").status_code == 404
        assert c.get(f"/api/agent/runs/{'a' * 24}").status_code == 404
        assert c.get("/api/agent/campaigns/zzz/workspace").status_code == 404


def test_strategy_failure_stops_the_run_cleanly(monkeypatch):
    async def boom(data):
        raise llm.LLMError("Gemini rejected the API key (401/403).")
    monkeypatch.setattr(llm, "generate_strategy", boom)
    with TestClient(app) as c:
        run = full_run(c)
        assert run["status"] == "failed" and "rejected the API key" in run["error"]
        st = {s["key"]: s["status"] for s in run["steps"]}
        assert st["strategy"] == "failed" and st["plan"] == "skipped" and st["visuals"] == "skipped"
        assert run["campaign_id"] is None and c.get("/api/agent/history").json()["items"] == []


def test_one_failing_asset_does_not_stop_the_others(monkeypatch):
    real = agent_extras.generate_extra

    async def flaky(key, campaign, strategy):
        if key == "instagram_reel":
            raise agent_extras.ExtraError("The AI returned an invalid reel.")
        return await real(key, campaign, strategy)
    monkeypatch.setattr(agent_extras, "generate_extra", flaky)
    with TestClient(app) as c:
        run = full_run(c)
        assert run["status"] == "completed_with_warnings"
        assert "invalid reel" in run["item_errors"]["instagram_reel"]
        w = ws(c, run["campaign_id"])
        assert item(w, "instagram_reel")["extra"] is None and "invalid reel" in item(w, "instagram_reel")["error"]
        assert item(w, "promo_caption")["extra"] and item(w, "instagram_post")["creative"]
        assert {s["key"]: s["status"] for s in run["steps"]}["copy"] == "warning"


def test_image_provider_failure_is_reported_per_asset(monkeypatch):
    async def down(prompt, spec, product):
        raise ip.ImageError("auth", "fake rejected the API key (401). Check the key.")
    monkeypatch.setitem(ip.IMAGE_PROVIDERS, "fake", down)
    monkeypatch.setenv("IMAGE_PROVIDER", "fake")
    get_settings.cache_clear()
    with TestClient(app) as c:
        run = full_run(c)
        assert run["status"] == "completed_with_warnings"  # all the copy still succeeded
        assert "rejected the API key" in run["item_errors"]["instagram_post"]
        w = ws(c, run["campaign_id"])
        assert item(w, "instagram_post")["creative"] is None and item(w, "instagram_post")["content"]
        assert {s["key"]: s["status"] for s in run["steps"]}["visuals"] == "failed"


# ---------- Step 10: plan approval, cancel, restart recovery ----------
def test_run_pauses_for_plan_approval_and_continues_with_edited_assets():
    with TestClient(app) as c:
        run = full_run(c, require_plan_approval=True)
        assert run["status"] == "awaiting_approval" and run["campaign_id"]
        cid = run["campaign_id"]
        assert {s["key"]: s["status"] for s in run["steps"]}["approval"] == "waiting"
        # the plan exists, but nothing was generated (no copy, no image spend) until the user approves
        w = ws(c, cid)
        assert len(w["items"]) == 4 and all(not (i["content"] or i["extra"] or i["creative"]) for i in w["items"])
        assert c.get(f"/api/campaigns/{cid}/content").json()["items"] == []
        # cannot start a second run on this campaign meanwhile
        assert c.post(f"/api/agent/campaigns/{cid}/regenerate", json={"scope": "campaign"}).status_code == 409
        assert c.post(f"/api/agent/runs/{run['id']}/continue", json={"assets": ["tiktok_dance"]}).status_code == 422
        r = c.post(f"/api/agent/runs/{run['id']}/continue", json={"assets": ["promo_caption", "instagram_post"]})
        assert r.status_code == 200
        done = wait(c, run["id"])
        assert done["status"] == "completed", done
        w = ws(c, cid)
        assert sorted(i["key"] for i in w["items"]) == ["instagram_post", "promo_caption"] and w["plan"]["source"] == "user"
        assert item(w, "instagram_post")["creative"] and item(w, "promo_caption")["extra"]
        assert c.post(f"/api/agent/runs/{run['id']}/continue", json={}).status_code == 409


def test_cancel_waiting_run():
    with TestClient(app) as c:
        run = full_run(c, require_plan_approval=True)
        r = c.post(f"/api/agent/runs/{run['id']}/cancel")
        assert r.status_code == 200 and r.json()["status"] == "cancelled"
        assert all(s["status"] in ("done", "skipped") for s in r.json()["steps"])
        assert c.post(f"/api/agent/runs/{run['id']}/cancel").status_code == 409


def test_interrupted_runs_are_marked_failed_on_restart():
    async def go():
        import database
        db = await database.connect()
        run = await agent_service.create_run(db, campaign_id=None, kind="full", scope="campaign",
                                             stages=["strategy", "plan"], items=[], options={})
        await db.agent_runs.update_one({"_id": run["_id"]}, {"$set": {"status": "running"}})
        assert await agent_service.recover_interrupted(db) == 1
        d = await db.agent_runs.find_one({"_id": run["_id"]})
        return d
    d = asyncio.run(go())
    assert d["status"] == "failed" and "restarted" in d["error"]


def test_guard_blocks_external_actions():
    guard.require("llm.generate")
    guard.require("image.generate")
    for action in ("publish_post", "send_email", "launch_ad", "schedule_post", "post_to_social"):
        with pytest.raises(guard.ExternalActionBlocked, match="external action"):
            guard.require(action)
    with pytest.raises(guard.ExternalActionBlocked, match="allow-list"):
        guard.require("delete_everything")


def test_agent_aborts_if_a_stage_attempts_an_external_action(monkeypatch):
    async def sneaky(ctx, brief):
        guard.require("publish_post")
    monkeypatch.setitem(agent_service.HANDLERS, "copy", sneaky)
    with TestClient(app) as c:
        run = full_run(c)
        assert run["status"] == "failed" and "external action" in run["error"]


# ---------- Step 8: history ----------
def test_history_lists_saved_campaigns_with_summaries_and_search():
    with TestClient(app) as c:
        a = full_run(c)["campaign_id"]
        b = full_run(c, product_name="Zen Mug", platform="LinkedIn")["campaign_id"]
        items = c.get("/api/agent/history").json()["items"]
        assert [i["id"] for i in items] == [b, a]  # newest first
        first = next(i for i in items if i["id"] == a)
        assert first["asset_count"] == 4 and first["copy_count"] == 4 and first["image_count"] == 2
        assert first["thumbnail"].startswith("/api/media/") and first["title"] and first["approved_count"] == 0
        assert [i["id"] for i in c.get("/api/agent/history?q=zen").json()["items"]] == [b]
        assert c.get("/api/agent/history?q=nothing-matches").json()["items"] == []
        # the workspace of a saved campaign can be re-opened later
        assert ws(c, a)["campaign"]["product_name"] == "EcoSip Bottle"


def test_campaign_created_in_phases_1_to_3_can_be_planned_later():
    with TestClient(app) as c:
        cid = c.post("/api/strategies", json=VALID).json()["campaign"]["id"]
        assert ws(c, cid)["items"] == [] and ws(c, cid)["plan"] is None
        assert c.post(f"/api/agent/campaigns/{cid}/regenerate", json={"scope": "caption", "target": "instagram_post"}).status_code == 422
        run = regen(c, cid, scope="plan")
        assert run["status"] == "completed" and len(ws(c, cid)["items"]) == 4


def test_deleting_a_campaign_removes_agent_data():
    async def counts(cid):
        import database
        from bson import ObjectId
        db = database.get_db()
        return [await db[n].count_documents({"campaign_id": ObjectId(cid)}) for n in ("agent_runs", "agent_assets", "creatives")]
    with TestClient(app) as c:
        cid = full_run(c)["campaign_id"]
        assert c.delete(f"/api/campaigns/{cid}").status_code == 204
        assert c.get(f"/api/agent/campaigns/{cid}/workspace").status_code == 404
        assert c.get("/api/agent/history").json()["items"] == []


# ---------- Step 9: regeneration at every level ----------
def test_regenerate_only_the_caption():
    with TestClient(app) as c:
        cid = full_run(c)["campaign_id"]
        before = ws(c, cid)
        old_ids = [v["id"] for v in item(before, "instagram_post")["content"]["variations"]]
        old_img = item(before, "instagram_post")["creative"]["concepts"][0]["image"]["url"]
        c.put(f"/api/agent/campaigns/{cid}/approvals", json={"approvals": {"instagram_post": "approved", "promo_caption": "approved"}})
        run = regen(c, cid, scope="caption", target="instagram_post")
        assert run["status"] == "completed" and [s["key"] for s in run["steps"]] == ["copy", "save"]
        after = ws(c, cid)
        assert [v["id"] for v in item(after, "instagram_post")["content"]["variations"]] != old_ids
        assert item(after, "instagram_post")["creative"]["concepts"][0]["image"]["url"] == old_img  # image untouched
        assert item(after, "instagram_post")["approval"] == "pending"   # changed content must be re-approved
        assert item(after, "promo_caption")["approval"] == "approved"   # other assets untouched
        assert item(after, "instagram_story")["content"] == item(before, "instagram_story")["content"]


def test_regenerate_an_extra_asset_caption():
    with TestClient(app) as c:
        cid = full_run(c)["campaign_id"]
        before = item(ws(c, cid), "promo_caption")["extra"]["updated_at"]
        time.sleep(0.01)
        assert regen(c, cid, scope="caption", target="promo_caption")["status"] == "completed"
        assert item(ws(c, cid), "promo_caption")["extra"]["updated_at"] > before


def test_regenerate_only_the_image():
    with TestClient(app) as c:
        cid = full_run(c)["campaign_id"]
        before = ws(c, cid)
        old_urls = {k["id"]: k["image"]["url"] for k in item(before, "instagram_post")["creative"]["concepts"]}
        run = regen(c, cid, scope="image", target="instagram_post")
        assert run["status"] == "completed" and [s["key"] for s in run["steps"]] == ["image_prompts", "visuals", "save"]
        after = ws(c, cid)
        new_urls = {k["id"]: k["image"]["url"] for k in item(after, "instagram_post")["creative"]["concepts"]}
        assert set(new_urls.values()).isdisjoint(old_urls.values())
        assert item(after, "instagram_post")["content"] == item(before, "instagram_post")["content"]  # copy untouched
        assert item(after, "instagram_story")["creative"] == item(before, "instagram_story")["creative"]


def test_regenerate_image_keeps_previous_when_provider_fails(monkeypatch):
    with TestClient(app) as c:
        cid = full_run(c)["campaign_id"]
        before = item(ws(c, cid), "instagram_post")["creative"]

        async def down(prompt, spec, product):
            raise ip.ImageError("quota", "fake image generation has no available quota.")
        monkeypatch.setitem(ip.IMAGE_PROVIDERS, "fake", down)
        monkeypatch.setenv("IMAGE_PROVIDER", "fake")
        get_settings.cache_clear()
        run = regen(c, cid, scope="image", target="instagram_post")
        assert run["status"] == "failed" and "previous images were kept" in run["item_errors"]["instagram_post"]
        assert item(ws(c, cid), "instagram_post")["creative"] == before


def test_regenerate_only_the_strategy_marks_assets_stale_and_cascade_clears_it():
    with TestClient(app) as c:
        cid = full_run(c)["campaign_id"]
        before = ws(c, cid)
        run = regen(c, cid, scope="strategy")
        assert run["status"] == "completed" and [s["key"] for s in run["steps"]] == ["strategy", "save"]
        after = ws(c, cid)
        assert after["campaign"]["stale"] is True
        assert item(after, "instagram_post")["content"] == item(before, "instagram_post")["content"]  # only strategy changed
        assert c.get("/api/agent/history").json()["items"][0]["stale"] is True
        run = regen(c, cid, scope="strategy", cascade=True)
        assert [s["key"] for s in run["steps"]] == ["strategy", "copy", "image_prompts", "visuals", "save"]
        assert ws(c, cid)["campaign"]["stale"] is False


def test_regenerate_complete_campaign():
    with TestClient(app) as c:
        cid = full_run(c)["campaign_id"]
        before = ws(c, cid)
        run = regen(c, cid, scope="campaign")
        assert run["status"] == "completed" and "strategy" in [s["key"] for s in run["steps"]]
        after = ws(c, cid)
        assert [i["key"] for i in after["items"]] == INSTAGRAM_KEYS  # same plan, new content
        assert [v["id"] for v in item(after, "instagram_post")["content"]["variations"]] != \
               [v["id"] for v in item(before, "instagram_post")["content"]["variations"]]
        assert len(c.get("/api/agent/history").json()["items"]) == 1  # same campaign, not a new one


def test_regenerate_validation_and_single_active_run():
    with TestClient(app) as c:
        cid = full_run(c)["campaign_id"]
        post = lambda **b: c.post(f"/api/agent/campaigns/{cid}/regenerate", json=b)
        assert post(scope="caption").status_code == 422                                  # target missing
        assert post(scope="caption", target="linkedin_post").status_code == 422          # not in this plan
        assert post(scope="image", target="promo_caption").status_code == 422            # no image for this asset
        assert post(scope="nonsense").status_code == 422
        assert c.post(f"/api/agent/campaigns/{'b' * 24}/regenerate", json={"scope": "campaign"}).status_code == 404
        waiting = full_run(c, require_plan_approval=True)
        assert c.post(f"/api/agent/campaigns/{waiting['campaign_id']}/regenerate", json={"scope": "strategy"}).status_code == 409


# ---------- Step 10: approval + confirmed export ----------
def test_export_requires_approval_and_confirmation_and_is_audited():
    with TestClient(app) as c:
        cid = full_run(c)["campaign_id"]
        url = f"/api/agent/campaigns/{cid}/export"
        assert c.post(url, json={"confirm": False}).status_code == 422
        assert c.post(url, json={"confirm": True}).status_code == 409  # nothing approved yet
        assert c.put(f"/api/agent/campaigns/{cid}/approvals", json={"approvals": {"linkedin_post": "approved"}}).status_code == 422
        assert c.put(f"/api/agent/campaigns/{cid}/approvals", json={"approvals": {}}).status_code == 422
        r = c.put(f"/api/agent/campaigns/{cid}/approvals", json={"approvals": {"instagram_post": "approved", "instagram_reel": "approved", "promo_caption": "rejected"}})
        assert r.status_code == 200 and r.json()["approved_count"] == 2
        md = c.post(url, json={"confirm": True}).json()
        assert md["format"] == "markdown" and md["filename"].endswith(".md") and md["included"] == ["instagram_post", "instagram_reel"]
        assert "Nothing has been published" in md["content"] and "## Instagram post" in md["content"]
        assert "Promotional caption" not in md["content"] and "instagram_story" not in md["included"]
        js = json.loads(c.post(url, json={"confirm": True, "format": "json", "assets": ["instagram_post"]}).json()["content"])
        assert [a["key"] for a in js["assets"]] == ["instagram_post"] and js["assets"][0]["image"]["url"].startswith("/api/media/")
        actions = [a["action"] for a in c.get(f"/api/agent/campaigns/{cid}/audit").json()["items"]]
        assert actions.count("export") == 2 and "approval" in actions


def test_cannot_approve_an_asset_that_was_not_generated():
    with TestClient(app) as c:
        run = full_run(c, require_plan_approval=True)
        r = c.put(f"/api/agent/campaigns/{run['campaign_id']}/approvals", json={"approvals": {"instagram_post": "approved"}})
        assert r.status_code == 422 and "Only generated assets" in r.json()["detail"]
