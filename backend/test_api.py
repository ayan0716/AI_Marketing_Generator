import os

os.environ["USE_MOCK_DB"] = "true"
os.environ["LLM_PROVIDER"] = "mock"

from fastapi.testclient import TestClient  # noqa: E402

from main import app  # noqa: E402

VALID = {
    "product_name": "EcoSip Bottle",
    "product_description": "A reusable stainless steel water bottle that keeps drinks cold for 24 hours.",
    "target_audience": "Eco-conscious students and office workers aged 18-35",
    "platform": "Instagram",
    "objective": "Sales / Conversions",
    "tone": "Friendly",
    "language": "English",
}


def test_full_flow():
    with TestClient(app) as c:
        assert c.get("/api/health").json()["status"] == "ok"
        assert c.get("/api/llm/test").json()["ok"] is True
        assert "Instagram" in c.get("/api/options").json()["platforms"]

        r = c.post("/api/strategies", json=VALID)
        assert r.status_code == 201
        body = r.json()
        for key in ["campaign_idea", "target_audience", "key_selling_points", "content_tone",
                    "call_to_action", "suggested_content_types"]:
            assert key in body["strategy"]["data"]

        cid = body["campaign"]["id"]
        assert len(c.get("/api/campaigns").json()) == 1
        assert c.get(f"/api/campaigns/{cid}").json()["strategy"] is not None
        assert c.delete(f"/api/campaigns/{cid}").status_code == 204
        assert c.get(f"/api/campaigns/{cid}").status_code == 404


def test_validation():
    with TestClient(app) as c:
        r = c.post("/api/strategies", json={**VALID, "product_name": "", "product_description": "short"})
        assert r.status_code == 422
        errs = r.json()["errors"]
        assert "product_name" in errs and "product_description" in errs

        r = c.post("/api/strategies", json={**VALID, "platform": "MySpace"})
        assert r.status_code == 422
        r = c.post("/api/strategies", json={**VALID, "product_name": "12345"})
        assert r.status_code == 422
