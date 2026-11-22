"""Phase 5 tests: strategy reuse, quality gate, prompts, rate limiting, security headers, logging, monitoring."""
import copy
import json
import logging

import pytest
from fastapi.testclient import TestClient

import llm
import observability as obs
import prompts
from config import get_settings
from main import app, brief_hash
from schemas import CampaignInput, MarketingStrategy
from strategy_quality import quality_issues
from tests.test_phase1 import VALID

SCENARIOS = [  # industry coverage required by Step 1
    ("EcoSip Bottle", "A reusable stainless steel water bottle that keeps drinks cold for 24 hours.", "e-commerce"),
    ("CodeCamp Academy", "An online bootcamp where students learn web development with live tutors and projects.", "education"),
    ("Olive & Thyme", "A family restaurant with a seasonal Mediterranean menu, fresh pasta and a sunny terrace.", "restaurant"),
    ("FlowDesk", "A SaaS platform with a dashboard that automates reporting workflows for small teams.", "software"),
    ("Nomad Denim", "A streetwear clothing brand with a limited fashion collection of recycled-cotton jackets.", "fashion"),
    ("Harbor View Flats", "Modern apartment listings near the waterfront, two bedrooms, balcony, parking included.", "real estate"),
]


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _brief(**kw):
    return CampaignInput(**{**VALID, **kw})


def _good(brief: CampaignInput) -> dict:
    return llm._mock_strategy(brief)


# ------------------------------------------------------------------ prompts (Step 4)
@pytest.mark.parametrize("name,desc,industry", SCENARIOS)
def test_industry_is_detected_and_guidance_is_in_prompt(name, desc, industry):
    b = _brief(product_name=name, product_description=desc)
    assert prompts.detect_industry(b) == industry
    p = prompts.build_user_prompt(b)
    assert "STRATEGIC GUIDANCE" in p and f"Industry ({industry})" in p
    assert f"Objective ({b.objective.value})" in p and f"Platform ({b.platform.value})" in p


def test_unknown_industry_still_builds_prompt():
    b = _brief(product_name="Zork", product_description="Something entirely unclassifiable and unusual here.")
    assert prompts.detect_industry(b) is None
    assert "Industry (" not in prompts.build_user_prompt(b)


def test_every_platform_and_objective_has_guidance():
    from schemas import Objective, Platform
    assert all(p.value in prompts.PLATFORM_GUIDE for p in Platform)
    assert all(o.value in prompts.OBJECTIVE_GUIDE for o in Objective)


# ------------------------------------------------------------------ quality gate (Step 3/4)
def test_mock_strategy_passes_quality_gate_for_all_industries():
    for name, desc, _ in SCENARIOS:
        b = _brief(product_name=name, product_description=desc)
        assert quality_issues(MarketingStrategy(**_good(b)), b) == [], name


def test_quality_gate_detects_each_failure_mode():
    b = _brief()
    bad = _good(b)
    bad["key_selling_points"] = [{"point": "Keeps drinks cold for hours", "benefit": "Cold drinks all day"}] * 3
    bad["content_tone"]["words_to_avoid"] = ["cheap", "simple"]  # clashes with words_to_use
    bad["campaign_idea"]["concept"] = "EcoSip is a revolutionary, cutting-edge bottle that boosts sales by 300%."
    bad["call_to_action"]["primary"] = "Click here right now to discover the full range of our products today"
    text = " | ".join(quality_issues(MarketingStrategy(**bad), b))
    assert "repeat" in text
    assert "share" in text or "buzzwords" in text or "not in the brief" in text


def test_ungrounded_strategy_is_flagged():
    b = _brief(product_name="EcoSip Bottle")
    s = _good(b)
    blob = json.dumps(s).replace("EcoSip Bottle", "X")
    s = json.loads(blob.replace("EcoSip", "X"))
    assert any("never mentions the product" in i for i in quality_issues(MarketingStrategy(**s), b))


@pytest.mark.anyio
async def test_bad_first_answer_triggers_one_targeted_retry(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    get_settings.cache_clear()
    b = _brief()
    bad = _good(b)
    bad["key_selling_points"] = [{"point": "Keeps drinks cold", "benefit": "Cold drinks"}] * 3
    calls = []

    async def fake(system, user, max_tokens):
        calls.append(user)
        return json.dumps(bad if len(calls) == 1 else _good(b))

    monkeypatch.setitem(llm.PROVIDERS, "fake", fake)
    strategy, provider, _ = await llm.generate_strategy(b)
    assert len(calls) == 2 and "rejected" in calls[1] and "repeat" in calls[1]
    assert quality_issues(strategy, b) == []
    get_settings.cache_clear()


@pytest.mark.anyio
async def test_failed_retry_keeps_the_valid_first_answer(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    get_settings.cache_clear()
    b = _brief()
    bad = _good(b)
    bad["key_selling_points"] = [{"point": "Keeps drinks cold", "benefit": "Cold drinks"}] * 3
    n = {"c": 0}

    async def fake(system, user, max_tokens):
        n["c"] += 1
        if n["c"] == 1:
            return json.dumps(bad)
        raise llm.LLMError("provider down")

    monkeypatch.setitem(llm.PROVIDERS, "fake", fake)
    strategy, _, _ = await llm.generate_strategy(b)  # no exception: the user still gets a usable strategy
    assert len(strategy.key_selling_points) == 3
    get_settings.cache_clear()


# ------------------------------------------------------------------ reuse = fewer LLM calls (Step 6)
def test_identical_brief_reuses_campaign_and_skips_the_llm(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "0")
    get_settings.cache_clear()
    n = {"c": 0}

    async def fake(system, user, max_tokens):
        n["c"] += 1
        return json.dumps(_good(_brief()))

    monkeypatch.setitem(llm.PROVIDERS, "fake", fake)
    with TestClient(app) as c:
        a = c.post("/api/strategies", json=VALID).json()
        assert a["reused"] is False and n["c"] == 1
        # same brief, different case / spacing -> reused
        b = c.post("/api/strategies", json={**VALID, "product_name": "  ecosip   bottle "}).json()
        assert b["reused"] is True and n["c"] == 1 and b["campaign"]["id"] == a["campaign"]["id"]
        # ?fresh=true forces a new generation
        d = c.post("/api/strategies?fresh=true", json=VALID).json()
        assert d["reused"] is False and n["c"] == 2 and d["campaign"]["id"] != a["campaign"]["id"]
        # a different brief is never reused
        e = c.post("/api/strategies", json={**VALID, "tone": "Luxury"}).json()
        assert e["reused"] is False and n["c"] == 3
        assert len(c.get("/api/campaigns").json()) == 3
    get_settings.cache_clear()


def test_brief_hash_ignores_case_and_whitespace():
    assert brief_hash(_brief()) == brief_hash(_brief(product_name=" ECOSIP  bottle"))
    assert brief_hash(_brief()) != brief_hash(_brief(language="French"))


# ------------------------------------------------------------------ rate limit (Step 6/7)
def test_rate_limiter_sliding_window():
    r = obs.RateLimiter(2, window=60)
    assert r.check("a")[0] and r.check("a")[0]
    ok, wait = r.check("a")
    assert not ok and 1 <= wait <= 61
    assert r.check("b")[0]  # other clients are unaffected
    assert obs.RateLimiter(0).check("x") == (True, 0)  # 0 = off


def test_expensive_route_pattern():
    for p in ["/api/strategies", "/api/campaigns/abc/content", "/api/campaigns/abc/content/instagram/regenerate",
              "/api/campaigns/abc/creatives", "/api/campaigns/abc/creatives/x/y/retry", "/api/agent/runs",
              "/api/agent/runs/abc/continue", "/api/agent/campaigns/abc/regenerate"]:
        assert obs.EXPENSIVE.match(p), p
    for p in ["/api/health", "/api/campaigns", "/api/agent/runs/abc/cancel", "/api/campaigns/abc/product-image"]:
        assert not obs.EXPENSIVE.match(p), p


def test_ai_endpoints_are_rate_limited_but_free_mode_is_not(monkeypatch):
    import main
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "2")
    get_settings.cache_clear()
    main._limiters.clear()

    async def fake(system, user, max_tokens):
        return json.dumps(_good(_brief()))

    monkeypatch.setitem(llm.PROVIDERS, "fake", fake)
    with TestClient(app) as c:
        codes = [c.post("/api/strategies", json={**VALID, "product_name": f"Bottle {x}"}).status_code
                 for x in ("A", "B", "C")]
        assert codes == [201, 201, 429]
        r = c.post("/api/strategies", json=VALID)
        assert r.status_code == 429 and "Retry-After" in r.headers and "wait" in r.json()["detail"]
        assert c.get("/api/health").status_code == 200  # cheap endpoints are never limited
    get_settings.cache_clear()
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    get_settings.cache_clear()
    main._limiters.clear()
    with TestClient(app) as c:  # mock providers cost nothing -> no limit
        assert all(c.post("/api/strategies?fresh=true", json=VALID).status_code == 201 for _ in range(4))
    get_settings.cache_clear()


# ------------------------------------------------------------------ security (Step 7)
def test_security_headers_request_id_and_cors():
    with TestClient(app) as c:
        r = c.get("/api/health", headers={"X-Request-ID": "abc-123"})
        assert r.headers["X-Request-ID"] == "abc-123"
        assert r.headers["X-Content-Type-Options"] == "nosniff" and r.headers["X-Frame-Options"] == "DENY"
        bad = c.get("/api/health", headers={"X-Request-ID": "x y<script>"})
        assert bad.headers["X-Request-ID"] != "x y<script>"  # malformed ids are replaced, never echoed


def test_oversized_body_is_rejected(monkeypatch):
    monkeypatch.setenv("MAX_BODY_MB", "1")
    get_settings.cache_clear()
    with TestClient(app) as c:
        r = c.post("/api/strategies", content=b"x" * (1024 * 1024 + 10), headers={"Content-Type": "application/json"})
        assert r.status_code == 413 and "too large" in r.json()["detail"]
    get_settings.cache_clear()


def test_secrets_are_masked_in_logs(caplog):
    obs.setup_logging()
    samples = {
        "key AIzaSyA1234567890abcdefghijklmnopqrstu failed": "AIzaSyA1234567890",
        "mongodb+srv://bob:hunter2@cluster0.x.mongodb.net/db": "hunter2",
        "OPENAI key sk-abcdefghijklmnopqrstuvwx": "sk-abcdefghijklmnopqrstuvwx",
        "GEMINI_API_KEY=supersecretvalue123": "supersecretvalue123",
    }
    for text, secret in samples.items():
        assert secret not in obs.redact(text), text
    assert "cluster0" in obs.redact("mongodb+srv://bob:hunter2@cluster0.x.mongodb.net/db")  # host stays for debugging


def test_errors_returned_to_the_user_do_not_leak_keys(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    get_settings.cache_clear()

    async def fake(system, user, max_tokens):
        raise RuntimeError("401 for key AIzaSyA1234567890abcdefghijklmnopqrstu")

    monkeypatch.setitem(llm.PROVIDERS, "fake", fake)
    with TestClient(app) as c:
        r = c.post("/api/strategies", json=VALID)
        assert r.status_code == 502 and "AIzaSyA1234567890" not in r.text
    get_settings.cache_clear()


# ------------------------------------------------------------------ monitoring (Step 8)
def test_unhandled_error_returns_clean_json_with_reference(monkeypatch, caplog):
    import main
    def boom():
        raise RuntimeError("db exploded")
    monkeypatch.setattr(main.database, "get_db", boom)
    with TestClient(app, raise_server_exceptions=False) as c:
        with caplog.at_level(logging.ERROR):
            r = c.get("/api/campaigns")
    assert r.status_code == 500 and r.json()["request_id"] and "reference" in r.json()["detail"]
    assert "db exploded" not in r.text  # internals are not shown to the user


@pytest.mark.anyio
async def test_ai_calls_are_counted_and_failures_recorded():
    obs.metrics.reset()

    async def ok(system, user, n):
        return "fine"

    async def bad(system, user, n):
        raise RuntimeError("429 rate limited AIzaSyA1234567890abcdefghijklmnopqrstu")

    providers = {"a": ok, "b": bad}
    obs.instrument_providers(providers, {}, lambda: "m1", lambda: "m2")
    assert await providers["a"]("s", "u", 1) == "fine"
    with pytest.raises(RuntimeError):
        await providers["b"]("s", "u", 1)
    snap = obs.metrics.snapshot()
    assert snap["ai_calls"]["llm:a"]["calls"] == 1 and snap["ai_calls"]["llm:a"]["errors"] == 0
    assert snap["ai_calls"]["llm:b"]["errors"] == 1 and snap["ai_calls"]["llm:b"]["error_rate"] == 1.0
    failure = snap["recent_failures"][-1]
    assert failure["kind"] == "llm_error" and "AIzaSyA1234567890" not in failure["error"]
    again = dict(providers)
    obs.instrument_providers(again, {}, lambda: "m1", lambda: "m2")
    assert again["a"] is providers["a"]  # never double-wrapped


def test_metrics_endpoint_and_admin_token(monkeypatch):
    with TestClient(app) as c:
        c.get("/api/options")
        body = c.get("/api/metrics").json()
        assert body["requests"] >= 1 and "ai_calls" in body and "latency_ms" in body
    monkeypatch.setenv("ADMIN_TOKEN", "s3cret")
    get_settings.cache_clear()
    with TestClient(app) as c:
        assert c.get("/api/metrics").status_code == 403
        assert c.get("/api/metrics", headers={"X-Admin-Token": "s3cret"}).status_code == 200
    monkeypatch.delenv("ADMIN_TOKEN")
    monkeypatch.setenv("ENVIRONMENT", "production")
    get_settings.cache_clear()
    with TestClient(app) as c:
        assert c.get("/api/metrics").status_code == 403  # closed by default in production
    get_settings.cache_clear()


def test_health_reports_version():
    with TestClient(app) as c:
        h = c.get("/api/health").json()
        assert h["status"] == "ok" and h["version"].startswith("5.")
