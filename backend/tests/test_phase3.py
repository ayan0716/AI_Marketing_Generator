"""Phase 3 tests: prompts, mock end-to-end flow, product image, regeneration, and every failure path (Step 9)."""

import base64
import io
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

import image_prompts
import image_providers as ip
import llm
from config import get_settings
from image_schemas import FORMAT_SPECS, CreativeFormat
from main import app
from tests.test_phase1 import VALID

FORMATS = [f.value for f in CreativeFormat]

def _png(w=600, h=800, color=(200, 40, 40, 255)) -> bytes:
    b = io.BytesIO()
    Image.new("RGBA", (w, h), color).save(b, "PNG")
    return b.getvalue()

def _data_url(data: bytes, mime="image/png") -> str:
    return f"data:{mime};base64," + base64.b64encode(data).decode()

def _campaign(c):
    return c.post("/api/strategies", json=VALID).json()["campaign"]["id"]

@pytest.fixture(autouse=True)
def _restore():
    yield
    get_settings.cache_clear()

def _use_provider(monkeypatch, fn):
    monkeypatch.setitem(ip.IMAGE_PROVIDERS, "fake", fn)
    monkeypatch.setenv("IMAGE_PROVIDER", "fake")
    get_settings.cache_clear()

def _ok_image(spec):
    return ip.finalize_image(_png(spec["width"], spec["height"]), spec, "fake", "fake-1")

# ---------- Steps 1-2: prompts are platform specific ----------
def test_prompt_is_platform_specific():
    campaign = {"product_name": "EcoSip", "product_description": "bottle", "objective": "Sales", "tone": "Friendly"}
    strategy = {"campaign_idea": {"hook": "Sip smart"}, "key_selling_points": []}
    story = image_prompts.build_concept_prompt(CreativeFormat.instagram_story, campaign, strategy, 3, True)
    thumb = image_prompts.build_concept_prompt(CreativeFormat.youtube_thumbnail, campaign, strategy, 3, False)
    assert "9:16" in story and "safe zones" in story and "PRODUCT PHOTO" in story
    assert "16:9" in thumb and "3-5 word title" in thumb and "No product photo" in thumb
    final = image_prompts.build_final_prompt(CreativeFormat.facebook_ad, {"color_palette": ["red", "blue"]}, "A scene.", True)
    assert "4:5" in final and "attached product photo" in final and "Do not add any text" in final

# ---------- Steps 3-5, 7: full workflow with the offline provider ----------
def test_generate_all_formats_multiple_concepts():
    with TestClient(app) as c:
        assert c.get("/api/creatives/formats").json()["provider"] == "mock"
        cid = _campaign(c)
        r = c.post(f"/api/campaigns/{cid}/creatives", json={"concepts": 3})
        assert r.status_code == 201
        res = r.json()["results"]
        assert set(res) == set(FORMATS)
        for f, item in res.items():
            concepts = item["creatives"]["concepts"]
            assert len(concepts) == 3 and len({x["style_label"] for x in concepts}) == 3  # visually different concepts
            assert all(x["status"] == "ready" and x["image"]["url"].startswith("/api/media/") for x in concepts)
            w, h = concepts[0]["image"]["width"], concepts[0]["image"]["height"]
            spec = FORMAT_SPECS[CreativeFormat(f)]
            assert abs(w / h - spec["ratio"]) / spec["ratio"] < 0.02  # correct aspect ratio per platform
            assert item["creatives"]["selected_concept_id"] == concepts[0]["id"]
        url = res["instagram_story"]["creatives"]["concepts"][0]["image"]["url"]
        img = c.get(url)
        assert img.status_code == 200 and img.headers["content-type"] == "image/jpeg"
        assert Image.open(io.BytesIO(img.content)).height > Image.open(io.BytesIO(img.content)).width
        assert len(c.get(f"/api/campaigns/{cid}/creatives").json()["items"]) == 5
        assert c.get(f"/api/campaigns/{cid}").json()["campaign"]["status"] == "creatives_ready"

def test_phase1_and_phase2_still_work_alongside():
    with TestClient(app) as c:
        cid = _campaign(c)
        assert c.post(f"/api/campaigns/{cid}/content", json={"variations": 2}).status_code == 201
        r = c.post(f"/api/campaigns/{cid}/creatives", json={"formats": ["youtube_thumbnail"], "concepts": 2})
        assert r.status_code == 201
        assert len(c.get(f"/api/campaigns/{cid}/content").json()["items"]) == 5

def test_validation_and_ids():
    with TestClient(app) as c:
        assert c.post("/api/campaigns/zzz/creatives", json={}).status_code == 404
        cid = _campaign(c)
        assert c.post(f"/api/campaigns/{cid}/creatives", json={"formats": ["tiktok"]}).status_code == 422
        assert c.post(f"/api/campaigns/{cid}/creatives", json={"concepts": 9}).status_code == 422
        assert c.put(f"/api/campaigns/{cid}/creatives/facebook_ad/select", json={"concept_id": "x"}).status_code == 404

# ---------- Step 6: product image ----------
def test_product_image_upload_validation_and_use():
    with TestClient(app) as c:
        cid = _campaign(c)
        assert c.get(f"/api/campaigns/{cid}/product-image").json()["product_image"] is None
        assert c.put(f"/api/campaigns/{cid}/product-image", json={"data_url": "data:text/plain;base64," + "A" * 60}).status_code == 422
        assert c.put(f"/api/campaigns/{cid}/product-image", json={"data_url": _data_url(b"not an image at all" * 4)}).status_code == 422
        assert c.put(f"/api/campaigns/{cid}/product-image", json={"data_url": _data_url(_png(40, 40))}).status_code == 422
        r = c.put(f"/api/campaigns/{cid}/product-image", json={"data_url": _data_url(_png())})
        assert r.status_code == 200 and r.json()["product_image"]["url"].startswith("/api/media/products/")
        r = c.post(f"/api/campaigns/{cid}/creatives", json={"formats": ["instagram_post"], "concepts": 1})
        v = r.json()["results"]["instagram_post"]["creatives"]["concepts"][0]
        assert v["image"] and "attached product photo" in v["image"]["prompt"]
        assert c.delete(f"/api/campaigns/{cid}/product-image").json()["product_image"] is None

def test_product_photo_reaches_the_provider(monkeypatch):
    seen = {}

    async def fake(prompt, spec, product):
        seen["product"] = product
        return _ok_image(spec)

    with TestClient(app) as c:
        cid = _campaign(c)
        c.put(f"/api/campaigns/{cid}/product-image", json={"data_url": _data_url(_png())})
        _use_provider(monkeypatch, fake)
        monkeypatch.setattr(ip, "PRODUCT_CAPABLE", ip.PRODUCT_CAPABLE | {"fake"})
        c.post(f"/api/campaigns/{cid}/creatives", json={"formats": ["facebook_ad"], "concepts": 1})
        assert seen["product"] is not None and seen["product"].data[:4] == b"\x89PNG"
        seen.clear()
        c.post(f"/api/campaigns/{cid}/creatives", json={"formats": ["facebook_ad"], "concepts": 1, "use_product_image": False})
        assert seen["product"] is None

def test_unsupported_provider_warns_and_skips_product(monkeypatch):
    async def fake(prompt, spec, product):
        assert product is None
        return _ok_image(spec)

    with TestClient(app) as c:
        cid = _campaign(c)
        c.put(f"/api/campaigns/{cid}/product-image", json={"data_url": _data_url(_png())})
        _use_provider(monkeypatch, fake)
        r = c.post(f"/api/campaigns/{cid}/creatives", json={"formats": ["facebook_ad"], "concepts": 1}).json()
        assert "cannot use a product photo" in r["results"]["facebook_ad"]["creatives"]["warnings"][0]

# ---------- Steps 7-8: select, regenerate with new instructions, versions ----------
def test_select_regenerate_versions_and_cleanup():
    with TestClient(app) as c:
        cid = _campaign(c)
        doc = c.post(f"/api/campaigns/{cid}/creatives", json={"formats": ["instagram_post"], "concepts": 3}).json()["results"]["instagram_post"]["creatives"]
        ids = [x["id"] for x in doc["concepts"]]
        r = c.put(f"/api/campaigns/{cid}/creatives/instagram_post/select", json={"concept_id": ids[2]}).json()
        assert r["selected_concept_id"] == ids[2]
        before = doc["concepts"][1]["image"]
        r = c.post(f"/api/campaigns/{cid}/creatives/instagram_post/{ids[1]}/regenerate",
                   json={"instructions": "Make the background dark and moody", "category": "background"})
        assert r.status_code == 200
        cc = r.json()["concepts"][1]
        assert cc["image"]["url"] != before["url"] and len(cc["versions"]) == 2
        assert "REVISION (background)" in cc["image"]["prompt"] and "dark and moody" in cc["image"]["prompt"]
        assert cc["versions"][-1]["instruction"] == "Make the background dark and moody"
        other = r.json()["concepts"][0]["image"]["url"]
        assert other == doc["concepts"][0]["image"]["url"]  # other concepts untouched
        r = c.put(f"/api/campaigns/{cid}/creatives/instagram_post/{ids[1]}/version", json={"version_id": before["id"]}).json()
        assert r["concepts"][1]["image"]["url"] == before["url"]
        assert c.put(f"/api/campaigns/{cid}/creatives/instagram_post/{ids[1]}/version", json={"version_id": "nope"}).status_code == 404
        assert c.post(f"/api/campaigns/{cid}/creatives/instagram_post/{ids[1]}/regenerate", json={"instructions": "x"}).status_code == 422
        assert c.delete(f"/api/campaigns/{cid}").status_code == 204
        assert c.get(before["url"]).status_code == 404  # files removed with the campaign

def test_llm_prompt_rewrite_is_used_for_revision(monkeypatch):
    async def fake_llm(system, user, max_tokens):
        return json.dumps({"image_prompt": "A bright beach scene with the bottle in the sand, golden hour light. " * 2})

    with TestClient(app) as c:
        cid = _campaign(c)
        doc = c.post(f"/api/campaigns/{cid}/creatives", json={"formats": ["linkedin_creative"], "concepts": 1}).json()["results"]["linkedin_creative"]["creatives"]
        monkeypatch.setitem(llm.PROVIDERS, "fake", fake_llm)
        monkeypatch.setenv("LLM_PROVIDER", "fake")
        get_settings.cache_clear()
        r = c.post(f"/api/campaigns/{cid}/creatives/linkedin_creative/{doc['concepts'][0]['id']}/regenerate",
                   json={"instructions": "beach background"}).json()
        assert "beach scene" in r["concepts"][0]["image"]["prompt"]

# ---------- LLM concept validation (invalid prompt-writer output) ----------
def test_invalid_concept_json_is_retried(monkeypatch):
    good = {"name": "Studio hero", "style_label": "Studio hero", "concept_summary": "Clean studio shot of the bottle.",
            "visual_style": "studio photo", "composition": "centered, negative space", "background": "white seamless",
            "lighting": "soft", "color_palette": "white, blue", "product_placement": "centered hero",
            "mood": "clean", "text_overlay": "Sip smart", "image_prompt": "A clean studio photograph of a steel water bottle " * 3}
    replies = ["Sorry, no JSON here", {"concepts": [good, {"name": "bad"}]}, {"concepts": [good]}]
    calls = []

    async def fake_llm(system, user, max_tokens):
        calls.append(user)
        r = replies[min(len(calls) - 1, 2)]
        return r if isinstance(r, str) else json.dumps(r)

    with TestClient(app) as c:
        cid = _campaign(c)
        monkeypatch.setitem(llm.PROVIDERS, "fake", fake_llm)
        monkeypatch.setenv("LLM_PROVIDER", "fake")
        get_settings.cache_clear()
        r = c.post(f"/api/campaigns/{cid}/creatives", json={"formats": ["instagram_post"], "concepts": 2}).json()
        cs = r["results"]["instagram_post"]["creatives"]["concepts"]
        assert len(cs) == 2 and "REJECTED" in calls[1] and "exactly 1 item" in calls[2]
        assert cs[0]["color_palette"] == ["white", "blue"]

def test_concept_prompt_total_failure(monkeypatch):
    async def fake_llm(system, user, max_tokens):
        return "garbage"

    with TestClient(app) as c:
        cid = _campaign(c)
        monkeypatch.setitem(llm.PROVIDERS, "fake", fake_llm)
        monkeypatch.setenv("LLM_PROVIDER", "fake")
        get_settings.cache_clear()
        r = c.post(f"/api/campaigns/{cid}/creatives", json={"formats": ["instagram_post"], "concepts": 1})
        assert r.status_code == 502 and "invalid image prompts" in r.json()["detail"]

# ---------- Step 9: generation failures at API level ----------
def test_partial_failure_is_stored_and_retry_works(monkeypatch):
    state = {"n": 0, "fail": True}

    async def fake(prompt, spec, product):
        state["n"] += 1
        if state["fail"] and state["n"] == 2:
            raise ip.ImageError("invalid_response", "The model returned no image.", retryable=True)
        return _ok_image(spec)

    with TestClient(app) as c:
        cid = _campaign(c)
        _use_provider(monkeypatch, fake)
        r = c.post(f"/api/campaigns/{cid}/creatives", json={"formats": ["facebook_ad"], "concepts": 3})
        assert r.status_code == 201
        doc = r.json()["results"]["facebook_ad"]["creatives"]
        statuses = sorted(x["status"] for x in doc["concepts"])
        assert statuses == ["failed", "ready", "ready"] and "1 of 3" in doc["warnings"][0]
        bad = next(x for x in doc["concepts"] if x["status"] == "failed")
        assert bad["error"]["kind"] == "invalid_response" and bad["image"] is None
        assert c.put(f"/api/campaigns/{cid}/creatives/facebook_ad/select", json={"concept_id": bad["id"]}).status_code == 422
        state["fail"] = False
        r = c.post(f"/api/campaigns/{cid}/creatives/facebook_ad/{bad['id']}/retry")
        assert r.status_code == 200
        assert all(x["status"] == "ready" and x["error"] is None for x in r.json()["concepts"])

@pytest.mark.parametrize("kind,status", [("rate_limit", 429), ("safety", 422), ("auth", 502), ("quota", 502), ("server", 502)])
def test_all_failed_maps_to_http_status(monkeypatch, kind, status):
    async def fake(prompt, spec, product):
        raise ip.ImageError(kind, f"{kind} problem", retry_after=30 if kind == "rate_limit" else None)

    with TestClient(app) as c:
        cid = _campaign(c)
        _use_provider(monkeypatch, fake)
        r = c.post(f"/api/campaigns/{cid}/creatives", json={"formats": ["instagram_post", "youtube_thumbnail"], "concepts": 2})
        assert r.status_code == status and f"{kind} problem" in r.json()["detail"]
        if kind == "rate_limit":
            assert r.headers["retry-after"] == "30"
        assert c.get(f"/api/campaigns/{cid}/creatives").json()["items"] == []  # nothing half-saved

def test_fatal_error_stops_further_api_calls(monkeypatch):
    calls = []

    async def fake(prompt, spec, product):
        calls.append(1)
        raise ip.ImageError("auth", "bad key")

    with TestClient(app) as c:
        cid = _campaign(c)
        _use_provider(monkeypatch, fake)
        c.post(f"/api/campaigns/{cid}/creatives", json={"concepts": 4})
        assert len(calls) <= 2  # concurrency gate lets at most 2 in flight, the rest are skipped

def test_unexpected_provider_crash_is_contained(monkeypatch):
    async def fake(prompt, spec, product):
        raise RuntimeError("boom")

    with TestClient(app) as c:
        cid = _campaign(c)
        _use_provider(monkeypatch, fake)
        r = c.post(f"/api/campaigns/{cid}/creatives", json={"formats": ["instagram_post"], "concepts": 1})
        assert r.status_code == 502 and "Unexpected" in r.json()["detail"]

def test_failed_revision_keeps_previous_image(monkeypatch):
    with TestClient(app) as c:
        cid = _campaign(c)
        doc = c.post(f"/api/campaigns/{cid}/creatives", json={"formats": ["instagram_post"], "concepts": 1}).json()["results"]["instagram_post"]["creatives"]
        keep = doc["concepts"][0]

        async def fake(prompt, spec, product):
            raise ip.ImageError("rate_limit", "slow down", retry_after=12)

        _use_provider(monkeypatch, fake)
        r = c.post(f"/api/campaigns/{cid}/creatives/instagram_post/{keep['id']}/regenerate", json={"instructions": "make it red"})
        assert r.status_code == 429 and r.headers["retry-after"] == "12"
        again = c.get(f"/api/campaigns/{cid}/creatives").json()["items"][0]["concepts"][0]
        assert again["image"]["url"] == keep["image"]["url"] and again["status"] == "ready"

# ---------- Step 9: real provider HTTP behaviour via a mocked transport ----------
SPEC = FORMAT_SPECS[CreativeFormat.instagram_story]

def _gemini_ok(data: bytes | None = None) -> dict:
    return {"candidates": [{"content": {"parts": [{"text": "here"}, {"inlineData": {"mimeType": "image/png", "data": base64.b64encode(data or _png(900, 1600)).decode()}}]}}]}

def _gemini_env(monkeypatch, handler):
    monkeypatch.setenv("GEMINI_API_KEY", "AIzaTEST")
    monkeypatch.setenv("IMAGE_PROVIDER", "gemini")
    get_settings.cache_clear()
    monkeypatch.setattr(ip, "BACKOFF_BASE", 0)
    monkeypatch.setattr(ip, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))

async def _run(product=None):
    return await ip.generate_image("a prompt", SPEC, product)

@pytest.mark.anyio
async def test_gemini_request_shape_and_success(monkeypatch):
    sent = {}

    def handler(req: httpx.Request):
        sent.update(json.loads(req.content), url=str(req.url), key=req.headers["x-goog-api-key"])
        return httpx.Response(200, json=_gemini_ok())

    _gemini_env(monkeypatch, handler)
    g = await _run(ip.ProductRef(_png(), "image/png"))
    assert sent["generationConfig"]["imageConfig"]["aspectRatio"] == "9:16"
    assert "image" in sent["generationConfig"]["responseModalities"] or "IMAGE" in sent["generationConfig"]["responseModalities"]
    parts = sent["contents"][0]["parts"]
    assert "inline_data" in parts[0] and parts[1]["text"] == "a prompt"  # product photo first, then the prompt
    assert sent["key"] == "AIzaTEST" and "gemini-2.5-flash-image" in sent["url"]
    assert (g.width, g.height) == (1080, 1920) or abs(g.width / g.height - 9 / 16) < 0.01

@pytest.mark.anyio
async def test_gemini_rate_limit_is_retried_then_succeeds(monkeypatch):
    n = {"c": 0}

    def handler(req):
        n["c"] += 1
        return httpx.Response(429, json={"error": {"message": "Resource exhausted", "status": "RESOURCE_EXHAUSTED"}}) if n["c"] < 3 else httpx.Response(200, json=_gemini_ok())

    _gemini_env(monkeypatch, handler)
    assert (await _run()).provider == "gemini" and n["c"] == 3

@pytest.mark.anyio
async def test_gemini_long_rate_limit_is_reported_not_waited(monkeypatch):
    n = {"c": 0}

    def handler(req):
        n["c"] += 1
        return httpx.Response(429, json={"error": {"message": "slow", "details": [{"retryDelay": "90s"}]}})

    _gemini_env(monkeypatch, handler)
    with pytest.raises(ip.ImageError) as e:
        await _run()
    assert e.value.kind == "rate_limit" and e.value.retry_after == 90 and "90s" in e.value.message and n["c"] == 1

@pytest.mark.anyio
async def test_gemini_no_quota_is_not_a_rate_limit(monkeypatch):
    _gemini_env(monkeypatch, lambda req: httpx.Response(429, json={"error": {"message": "Quota exceeded ... limit: 0, model: gemini-2.5-flash-image"}}))
    with pytest.raises(ip.ImageError) as e:
        await _run()
    assert e.value.kind == "quota" and "billing" in e.value.message.lower()

@pytest.mark.anyio
@pytest.mark.parametrize("response,kind", [
    (httpx.Response(401, json={"error": {"message": "API key not valid"}}), "auth"),
    (httpx.Response(200, json={"promptFeedback": {"blockReason": "SAFETY"}}), "safety"),
    (httpx.Response(200, json={"candidates": [{"finishReason": "IMAGE_SAFETY", "content": {"parts": []}}]}), "safety"),
    (httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "I cannot draw that"}]}}]}), "invalid_response"),
    (httpx.Response(200, json={"candidates": []}), "invalid_response"),
    (httpx.Response(200, content=b"<html>oops</html>"), "invalid_response"),
    (httpx.Response(200, json={"candidates": [{"content": {"parts": [{"inlineData": {"data": base64.b64encode(b"garbage bytes").decode()}}]}}]}), "invalid_response"),
    (httpx.Response(200, json=_gemini_ok(_png(100, 100))), "invalid_response"),  # image far too small
    (httpx.Response(400, json={"error": {"message": "Invalid aspect ratio"}}), "bad_request"),
    (httpx.Response(503, json={"error": {"message": "overloaded"}}), "server"),
])
async def test_gemini_failure_kinds(monkeypatch, response, kind):
    _gemini_env(monkeypatch, lambda req: response)
    with pytest.raises(ip.ImageError) as e:
        await _run()
    assert e.value.kind == kind

@pytest.mark.anyio
async def test_gemini_timeout_and_network_errors(monkeypatch):
    def boom(req):
        raise httpx.ConnectTimeout("slow", request=req)

    _gemini_env(monkeypatch, boom)
    with pytest.raises(ip.ImageError) as e:
        await _run()
    assert e.value.kind == "timeout"

    def down(req):
        raise httpx.ConnectError("down", request=req)

    _gemini_env(monkeypatch, down)
    with pytest.raises(ip.ImageError) as e:
        await _run()
    assert e.value.kind == "network"

@pytest.mark.anyio
async def test_gemini_falls_back_to_second_model(monkeypatch):
    monkeypatch.setenv("GEMINI_IMAGE_FALLBACK_MODELS", "gemini-backup-image")
    urls = []

    def handler(req):
        urls.append(str(req.url))
        return httpx.Response(404, json={"error": {"message": "model not found"}}) if "gemini-2.5-flash-image" in str(req.url) else httpx.Response(200, json=_gemini_ok())

    _gemini_env(monkeypatch, handler)
    assert (await _run()).model == "gemini-backup-image"

@pytest.mark.anyio
async def test_missing_keys_and_unknown_provider(monkeypatch):
    monkeypatch.setenv("IMAGE_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    get_settings.cache_clear()
    with pytest.raises(ip.ImageError) as e:
        await _run()
    assert e.value.kind == "config"
    monkeypatch.setenv("IMAGE_PROVIDER", "nope")
    get_settings.cache_clear()
    with pytest.raises(ip.ImageError) as e:
        await _run()
    assert e.value.kind == "config"

@pytest.mark.anyio
async def test_openai_generation_and_edit(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("IMAGE_PROVIDER", "openai")
    get_settings.cache_clear()
    seen = []

    def handler(req):
        seen.append((req.url.path, req.headers.get("content-type", "")))
        return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(_png(1024, 1536)).decode()}]})

    monkeypatch.setattr(ip, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    await _run()
    await _run(ip.ProductRef(_png(), "image/png"))
    assert seen[0][0] == "/v1/images/generations" and seen[1][0] == "/v1/images/edits" and "multipart" in seen[1][1]

@pytest.mark.anyio
async def test_openai_content_policy_and_rate_limit(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("IMAGE_PROVIDER", "openai")
    get_settings.cache_clear()
    monkeypatch.setattr(ip, "BACKOFF_BASE", 0)
    resp = {"r": httpx.Response(400, json={"error": {"message": "Your request was rejected by the safety system."}})}
    monkeypatch.setattr(ip, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(lambda req: resp["r"])))
    with pytest.raises(ip.ImageError) as e:
        await _run()
    assert e.value.kind == "safety"
    resp["r"] = httpx.Response(429, headers={"retry-after": "45"}, json={"error": {"message": "Rate limit reached"}})
    with pytest.raises(ip.ImageError) as e:
        await _run()
    assert e.value.kind == "rate_limit" and e.value.retry_after == 45

def test_finalize_crops_to_platform_ratio():
    spec = FORMAT_SPECS[CreativeFormat.linkedin_creative]
    g = ip.finalize_image(_png(1920, 1080), spec, "x", "y")  # 16:9 model output -> 1.91:1 LinkedIn
    assert abs(g.width / g.height - spec["ratio"]) < 0.01 and g.width == 1200

@pytest.fixture
def anyio_backend():
    return "asyncio"
