"""Phase 5, Steps 1-3: run the generator over many industries / audiences / objectives / platforms and score it.

    python scripts/evaluate.py                    # offline: mock providers, checks the pipeline + the quality rules
    python scripts/evaluate.py --live             # uses backend/.env (real Gemini / OpenAI / Anthropic), costs API calls
    python scripts/evaluate.py --base-url https://your-app.onrender.com   # tests the deployed app

Writes docs/evaluation_report.md and docs/evaluation_results.json. Open the report and add your own
reading of the *real* output in the "Manual review" table: automatic checks find repetition and invented facts,
only a human can judge tone and creativity.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SCENARIOS = [
    # industry, product, description, audience, platform, objective, tone
    ("E-commerce", "EcoSip Bottle", "A reusable stainless steel water bottle that keeps drinks cold for 24 hours.",
     "Eco-conscious students and office workers aged 18-35", "Instagram", "Sales / Conversions", "Friendly"),
    ("E-commerce", "PetPal Feeder", "A smart pet feeder with a camera and scheduled portions for busy pet owners.",
     "Working professionals with dogs or cats", "Facebook", "Product Launch", "Playful"),
    ("Education", "CodeCamp Academy", "A 12-week online bootcamp teaching web development with live tutors and real projects.",
     "Career changers aged 25-40 who want a first developer job", "LinkedIn", "Lead Generation", "Professional"),
    ("Education", "LinguaKids", "A playful language-learning app for children aged 6-10 with short daily games.",
     "Parents of primary-school children", "Instagram", "Engagement", "Friendly"),
    ("Restaurant", "Olive & Thyme", "A family restaurant with a seasonal Mediterranean menu, fresh pasta and a sunny terrace.",
     "Local couples and families who like to dine out on weekends", "Instagram", "Brand Awareness", "Inspirational"),
    ("Restaurant", "Brew Lab Coffee", "A specialty coffee shop roasting single-origin beans in-house with a quiet co-working corner.",
     "Freelancers and students near the city centre", "TikTok", "Engagement", "Playful"),
    ("Software", "FlowDesk", "A SaaS platform with a dashboard that automates weekly reporting workflows for small teams.",
     "Operations managers at companies with 10-50 employees", "LinkedIn", "Lead Generation", "Professional"),
    ("Software", "NoteNest", "A note-taking app that syncs across devices and summarises meetings automatically.",
     "Students and remote workers", "YouTube", "Brand Awareness", "Informative"),
    ("Clothing", "Nomad Denim", "A streetwear clothing brand with a limited collection of recycled-cotton jackets.",
     "Style-conscious Gen Z shoppers who care about sustainability", "TikTok", "Product Launch", "Bold"),
    ("Clothing", "Atelier Noor", "A modest-fashion label with premium linen dresses designed for everyday elegance.",
     "Women aged 25-45 looking for refined modest wear", "Instagram", "Sales / Conversions", "Luxury"),
    ("Real estate", "Harbor View Flats", "Modern two-bedroom apartments near the waterfront with a balcony and parking included.",
     "Young families and first-time buyers", "Facebook", "Lead Generation", "Professional"),
    ("Real estate", "Maple Court Rentals", "Furnished studio rentals for relocating professionals, flexible 6-month leases, close to the metro.",
     "Professionals relocating to the city for work", "Google Ads", "Lead Generation", "Informative"),
]


def make_client(args):
    if args.base_url:
        import httpx
        c = httpx.Client(base_url=args.base_url.rstrip("/"), timeout=180)
        return c, lambda: None
    if not args.live:
        os.environ.update({"USE_MOCK_DB": "true", "LLM_PROVIDER": "mock", "IMAGE_PROVIDER": "mock",
                           "STORAGE_DIR": str(ROOT / "storage_eval")})
    from fastapi.testclient import TestClient
    from main import app
    tc = TestClient(app)
    tc.__enter__()
    return tc, lambda: tc.__exit__(None, None, None)


def score_content(variations: list[dict]) -> dict:
    from strategy_quality import similarity
    heads = [json.dumps({k: v for k, v in x.items() if k in ("hook", "headline", "video_title", "introduction", "subject_line")},
                        ensure_ascii=False) for x in variations]
    worst = max((similarity(heads[i], heads[j]) for i in range(len(heads)) for j in range(i + 1, len(heads))), default=0.0)
    return {"variations": len(variations), "max_hook_similarity": round(worst, 2), "repetitive": worst >= 0.7}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="use real providers from backend/.env")
    ap.add_argument("--base-url", help="evaluate a deployed instance instead of running in-process")
    ap.add_argument("--no-content", action="store_true", help="strategies only (saves API calls)")
    ap.add_argument("--limit", type=int, default=0, help="only the first N scenarios")
    args = ap.parse_args()

    from strategy_quality import quality_issues
    from schemas import CampaignInput, MarketingStrategy

    client, close = make_client(args)
    rows = []
    for industry, name, desc, audience, platform, objective, tone in (SCENARIOS[: args.limit] if args.limit else SCENARIOS):
        payload = {"product_name": name, "product_description": desc, "target_audience": audience, "platform": platform,
                   "objective": objective, "tone": tone, "language": "English"}
        row = {"industry": industry, "product": name, "platform": platform, "objective": objective, "tone": tone}
        t0 = time.perf_counter()
        r = client.post("/api/strategies?fresh=true", json=payload)
        row["strategy_ms"] = round((time.perf_counter() - t0) * 1000)
        row["strategy_status"] = r.status_code
        if r.status_code != 201:
            row["error"] = (r.json().get("detail") if r.headers.get("content-type", "").startswith("application/json") else r.text)[:200]
            rows.append(row)
            continue
        body = r.json()
        data = body["strategy"]["data"]
        issues = quality_issues(MarketingStrategy(**data), CampaignInput(**payload))
        row["quality_issues"] = issues
        row["selling_points"] = len(data["key_selling_points"])
        row["cta"] = data["call_to_action"]["primary"]
        if not args.no_content:
            cid = body["campaign"]["id"]
            plat_key = {"Instagram": "instagram", "LinkedIn": "linkedin", "Facebook": "facebook", "YouTube": "youtube"}.get(platform, "instagram")
            c = client.post(f"/api/campaigns/{cid}/content", json={"platforms": [plat_key], "variations": 3})
            if c.status_code == 201 and "content" in c.json()["results"].get(plat_key, {}):
                row["content"] = score_content(c.json()["results"][plat_key]["content"]["variations"])
            else:
                row["content"] = {"error": str(c.json().get("detail", c.status_code))[:150]}
        rows.append(row)
    close()

    ok = [r for r in rows if r["strategy_status"] == 201]
    clean = [r for r in ok if not r["quality_issues"]]
    rep = [r for r in ok if r.get("content", {}).get("repetitive")]
    summary = {
        "runs": len(rows), "succeeded": len(ok), "failed": len(rows) - len(ok),
        "quality_gate_clean": len(clean), "repetitive_content": len(rep),
        "median_strategy_ms": int(statistics.median([r["strategy_ms"] for r in ok])) if ok else None,
        "mode": "deployed" if args.base_url else ("live providers" if args.live else "offline mock providers"),
    }
    out_dir = ROOT.parent / "docs"
    out_dir.mkdir(exist_ok=True)
    (out_dir / "evaluation_results.json").write_text(json.dumps({"summary": summary, "rows": rows}, indent=2, ensure_ascii=False), encoding="utf-8")

    md = [f"# Evaluation report ({summary['mode']})", "",
          f"Generated {time.strftime('%Y-%m-%d %H:%M')} by `backend/scripts/evaluate.py`.", "",
          f"**{summary['succeeded']}/{summary['runs']}** runs succeeded, **{summary['quality_gate_clean']}** passed every automatic "
          f"quality check, **{summary['repetitive_content']}** had repetitive content variations, "
          f"median strategy time **{summary['median_strategy_ms']} ms**.", "",
          "| Industry | Product | Platform | Objective | Strategy | Quality issues | CTA | Content repetition |",
          "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        if r["strategy_status"] != 201:
            md.append(f"| {r['industry']} | {r['product']} | {r['platform']} | {r['objective']} | FAILED: {r.get('error','')} | | | |")
            continue
        cont = r.get("content", {})
        cr = "n/a" if not cont else (cont.get("error", "error") if "error" in cont else f"{cont['max_hook_similarity']} ({'repetitive' if cont['repetitive'] else 'ok'})")
        md.append(f"| {r['industry']} | {r['product']} | {r['platform']} | {r['objective']} | {r['strategy_ms']} ms | "
                  f"{'; '.join(r['quality_issues']) or 'none'} | {r['cta']} | {cr} |")
    md += ["", "## Manual review (fill in after a `--live` run)", "",
           "| Industry | Relevant to the brief? (1-5) | Specific, not generic? (1-5) | Tone matches? (1-5) | Image matches the idea? (1-5) | Notes |",
           "|---|---|---|---|---|---|"] + [f"| {i} | | | | | |" for i in dict.fromkeys(s[0] for s in SCENARIOS)]
    (out_dir / "evaluation_report.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(f"Report: {out_dir / 'evaluation_report.md'}")
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
