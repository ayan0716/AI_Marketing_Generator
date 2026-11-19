import json

import pytest
from fastapi.testclient import TestClient

import llm
from config import get_settings
from content_schemas import ContentPlatform
from main import app
from tests.test_phase1 import VALID

PLATFORMS = [p.value for p in ContentPlatform]


def _campaign(c):
    return c.post("/api/strategies", json=VALID).json()["campaign"]["id"]


def test_generate_all_platforms_structured():
    with TestClient(app) as c:
        cid = _campaign(c)
        r = c.post(f"/api/campaigns/{cid}/content", json={"variations": 3})
        assert r.status_code == 201
        res = r.json()["results"]
        assert set(res) == set(PLATFORMS)
        for p, item in res.items():
            vs = item["content"]["variations"]
            assert len(vs) == 3 and len({v["id"] for v in vs}) == 3
        ig = res["instagram"]["content"]["variations"][0]
        assert {"hook", "main_message", "call_to_action", "hashtags"} <= set(ig) and ig["hashtags"][0].startswith("#")
        li = res["linkedin"]["content"]["variations"][0]
        assert {"introduction", "value_proposition", "main_content", "call_to_action", "hashtags"} <= set(li)
        fb = res["facebook"]["content"]["variations"][0]
        assert {"headline", "primary_text", "call_to_action", "short_description"} <= set(fb)
        yt = res["youtube"]["content"]["variations"][0]
        assert {"video_title", "description", "hook", "call_to_action", "thumbnail_concept"} <= set(yt)
        assert len(res["instagram_story"]["content"]["variations"][0]["frames"]) >= 3
        # persisted + campaign status updated
        assert len(c.get(f"/api/campaigns/{cid}/content").json()["items"]) == 5
        assert c.get(f"/api/campaigns/{cid}").json()["campaign"]["status"] == "content_ready"


def test_regenerate_and_select():
    with TestClient(app) as c:
        cid = _campaign(c)
        c.post(f"/api/campaigns/{cid}/content", json={"platforms": ["instagram"], "variations": 3})
        before = c.get(f"/api/campaigns/{cid}/content").json()["items"][0]["variations"]
        r = c.post(f"/api/campaigns/{cid}/content/instagram/regenerate", json={"index": 1}).json()
        assert len(r["variations"]) == 3
        assert r["variations"][1]["id"] != before[1]["id"] and r["variations"][0]["id"] == before[0]["id"]
        r = c.post(f"/api/campaigns/{cid}/content/instagram/regenerate", json={"variations": 2}).json()
        assert len(r["variations"]) == 2
        assert c.put(f"/api/campaigns/{cid}/content/instagram/select", json={"index": 1}).json()["selected_index"] == 1
        assert c.put(f"/api/campaigns/{cid}/content/instagram/select", json={"index": 7}).status_code == 422
        assert c.put(f"/api/campaigns/{cid}/content/linkedin/select", json={"index": 0}).status_code == 404


def test_requires_strategy_and_valid_ids():
    with TestClient(app) as c:
        assert c.post("/api/campaigns/zzz/content", json={}).status_code == 404
        assert c.post(f"/api/campaigns/{'a' * 24}/content", json={}).status_code == 404
        cid = _campaign(c)
        assert c.post(f"/api/campaigns/{cid}/content", json={"platforms": ["tiktok"]}).status_code == 422
        assert c.post(f"/api/campaigns/{cid}/content", json={"variations": 9}).status_code == 422


# ---------- Step 8: invalid / incomplete / badly formatted LLM output ----------
GOOD = {
    "angle": "Problem-first", "headline": "Cold drinks all day",
    "primary_text": "Keep every sip ice cold for 24 hours with EcoSip.", "call_to_action": "Shop Now",
    "short_description": "",
}


def _fake_provider(monkeypatch, replies):
    calls = []

    async def fake(system, user, max_tokens):
        calls.append(user)
        r = replies[min(len(calls) - 1, len(replies) - 1)]
        return r if isinstance(r, str) else json.dumps(r)

    monkeypatch.setattr(llm, "PROVIDERS", {"fake": fake})
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    get_settings.cache_clear()
    return calls


@pytest.fixture(autouse=True)
def _restore_settings():
    yield
    get_settings.cache_clear()


def _prepare():
    """Create a campaign using the mock provider, return (client_ctx, cid)."""
    c = TestClient(app).__enter__()
    return c, _campaign(c)


def test_markdown_fenced_json_is_accepted(monkeypatch):
    c, cid = _prepare()
    _fake_provider(monkeypatch, ["```json\n" + json.dumps({"variations": [GOOD] * 3}) + "\n```"])
    r = c.post(f"/api/campaigns/{cid}/content", json={"platforms": ["facebook"], "variations": 3})
    assert len(r.json()["results"]["facebook"]["content"]["variations"]) == 3


def test_garbage_then_valid_is_retried(monkeypatch):
    c, cid = _prepare()
    calls = _fake_provider(monkeypatch, ["Sorry, here are some ideas!", {"variations": [GOOD] * 3}])
    r = c.post(f"/api/campaigns/{cid}/content", json={"platforms": ["facebook"], "variations": 3})
    assert len(r.json()["results"]["facebook"]["content"]["variations"]) == 3
    assert len(calls) == 2 and "REJECTED" in calls[1]


def test_incomplete_variations_are_dropped_and_refilled(monkeypatch):
    c, cid = _prepare()
    bad = {"angle": "x1", "headline": "No body"}  # missing primary_text + call_to_action
    calls = _fake_provider(monkeypatch, [{"variations": [GOOD, bad, GOOD]}, {"variations": [GOOD]}])
    r = c.post(f"/api/campaigns/{cid}/content", json={"platforms": ["facebook"], "variations": 3})
    item = r.json()["results"]["facebook"]["content"]
    assert len(item["variations"]) == 3 and item["warnings"] == []
    assert "exactly 1 item" in calls[1]  # only the missing one was requested


def test_partial_result_returns_warning(monkeypatch):
    c, cid = _prepare()
    _fake_provider(monkeypatch, [{"variations": [GOOD]}, "oops", "oops"])  # only 1 valid ever
    r = c.post(f"/api/campaigns/{cid}/content", json={"platforms": ["facebook"], "variations": 3})
    item = r.json()["results"]["facebook"]["content"]
    assert len(item["variations"]) == 1 and "Only 1 of 3" in item["warnings"][0]


def test_total_failure_gives_clean_error_and_other_platforms_survive(monkeypatch):
    c, cid = _prepare()
    ok_ig = {"angle": "Hook", "hook": "Stay cool", "main_message": "EcoSip keeps drinks cold for 24h.",
             "call_to_action": "Shop now", "hashtags": "#eco #bottle sip"}  # string hashtags get normalised

    async def fake(system, user, max_tokens):
        if "Instagram feed caption" in user:
            return json.dumps({"variations": [ok_ig]})
        return "not json at all"

    monkeypatch.setattr(llm, "PROVIDERS", {"fake": fake})
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    get_settings.cache_clear()
    r = c.post(f"/api/campaigns/{cid}/content", json={"platforms": ["instagram", "youtube"], "variations": 1})
    res = r.json()["results"]
    assert res["instagram"]["content"]["variations"][0]["hashtags"] == ["#eco", "#bottle", "#sip"]
    assert "invalid youtube content" in res["youtube"]["error"]
    # when EVERYTHING fails -> HTTP 502 with a readable message
    r = c.post(f"/api/campaigns/{cid}/content", json={"platforms": ["youtube"], "variations": 1})
    assert r.status_code == 502 and "Regenerate" in r.json()["detail"]
