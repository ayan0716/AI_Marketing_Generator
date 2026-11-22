"""LLM client with pluggable providers: anthropic | openai | gemini | mock."""
import asyncio
import json
import logging
import re

import httpx
from pydantic import ValidationError

from config import get_settings
from prompts import SYSTEM_PROMPT, build_user_prompt
from schemas import CampaignInput, MarketingStrategy
from strategy_quality import quality_issues

log = logging.getLogger("llm")


class LLMError(Exception):
    pass

def _extract_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            return json.loads(text[start : end + 1])
        raise

async def _call_anthropic(system: str, user: str, max_tokens: int) -> str:
    from anthropic import AsyncAnthropic

    s = get_settings()
    if not s.anthropic_api_key:
        raise LLMError("ANTHROPIC_API_KEY is not set.")
    client = AsyncAnthropic(api_key=s.anthropic_api_key)
    msg = await client.messages.create(
        model=s.anthropic_model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")

async def _call_openai(system: str, user: str, max_tokens: int) -> str:
    from openai import AsyncOpenAI

    s = get_settings()
    if not s.openai_api_key:
        raise LLMError("OPENAI_API_KEY is not set.")
    client = AsyncOpenAI(api_key=s.openai_api_key)
    res = await client.chat.completions.create(
        model=s.openai_model,
        max_tokens=max_tokens,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        response_format={"type": "json_object"} if "JSON" in system else None,
    )
    return res.choices[0].message.content or ""

# Gemini has two REST endpoints and two key styles:
#   - Gemini Developer API (Google AI Studio keys, usually start with "AIza")
#   - Vertex AI Express Mode (keys that start with "AQ.")
# We pick by key prefix and, on a 401/403, try the other endpoint once.
_DEV_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
_VERTEX_URL = "https://aiplatform.googleapis.com/v1/publishers/google/models/{model}:generateContent"
_RETRY_STATUS = {429, 500, 502, 503, 504}

def _gemini_error_text(r: httpx.Response) -> str:
    try:
        err = r.json().get("error", {})
        return f"{r.status_code} {err.get('status', '')}: {err.get('message', r.text[:200])}".strip()
    except Exception:
        return f"{r.status_code}: {r.text[:200]}"

async def _call_gemini(system: str, user: str, max_tokens: int) -> str:
    s = get_settings()
    key = s.gemini_api_key
    if not key:
        raise LLMError("GEMINI_API_KEY is not set in backend/.env (restart the server after editing it).")

    # Order of endpoints: by key style first, the other one as a fallback.
    endpoints = [_VERTEX_URL, _DEV_URL] if key.startswith("AQ.") else [_DEV_URL, _VERTEX_URL]
    models = [s.gemini_model] + [m.strip() for m in s.gemini_fallback_models.split(",") if m.strip()]
    wants_json = "JSON" in system
    problems: list[str] = []

    async with httpx.AsyncClient(timeout=90) as client:
        for model in models:
            model = model.removeprefix("models/")
            gen_cfg = {"maxOutputTokens": max(max_tokens, 1024)}
            if wants_json:
                gen_cfg["responseMimeType"] = "application/json"
            if "2.5-flash" in model:
                gen_cfg["thinkingConfig"] = {"thinkingBudget": 0}  # thinking would eat the output budget
            payload = {
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "generationConfig": gen_cfg,
            }
            auth_failed_everywhere = True
            for url_tpl in endpoints:
                url = url_tpl.format(model=model)
                for attempt in range(3):
                    try:
                        r = await client.post(url, headers={"x-goog-api-key": key}, json=payload)
                    except httpx.HTTPError as e:
                        problems.append(f"{model}: network error {e.__class__.__name__}")
                        auth_failed_everywhere = False
                        await asyncio.sleep(2 ** attempt)
                        continue
                    if r.status_code == 200:
                        try:
                            parts = r.json()["candidates"][0]["content"]["parts"]
                            text = "".join(p.get("text", "") for p in parts).strip()
                        except (KeyError, IndexError, TypeError):
                            text = ""
                        if text:
                            return text
                        problems.append(f"{model}: empty response (blocked or truncated)")
                        auth_failed_everywhere = False
                        break
                    problems.append(f"{model}: {_gemini_error_text(r)}")
                    if r.status_code in _RETRY_STATUS:
                        auth_failed_everywhere = False
                        await asyncio.sleep(2 ** attempt)  # 1s, 2s, 4s
                        continue
                    if r.status_code not in (401, 403):
                        auth_failed_everywhere = False
                    break  # 401/403 -> try the other endpoint; 404 etc -> next model
            if auth_failed_everywhere:
                break  # the key itself is rejected; other models will not help

    if problems and all(("401" in p or "403" in p) for p in problems):
        raise LLMError(
            "Gemini rejected the API key (401/403). Create a new key at https://aistudio.google.com/apikey, "
            "paste it into GEMINI_API_KEY in backend/.env with no quotes or spaces, and restart the backend. "
            f"Details: {problems[-1]}"
        )
    raise LLMError("Gemini request failed. " + " | ".join(problems[-4:]))

def _mock_strategy(data: CampaignInput) -> dict:
    """Deterministic offline strategy so the app runs without any API key."""
    n, p = data.product_name, data.platform.value
    return {
        "campaign_idea": {
            "title": f"{n}: Made for {data.target_audience.split(',')[0][:40]}",
            "concept": f"Position {n} as the obvious choice for its audience on {p}, "
            f"focusing on {data.objective.value.lower()} with a {data.tone.value.lower()} voice.",
            "hook": f"Meet {n} - the upgrade you did not know you needed.",
        },
        "target_audience": {
            "summary": data.target_audience,
            "demographics": ["Primary segment from brief", "Active on " + p, "Digitally engaged"],
            "psychographics": ["Value-conscious", "Seeks quality", "Influenced by social proof"],
            "pain_points": ["Too many similar options", "Unclear value", "Low trust in new brands"],
        },
        "key_selling_points": [
            {"point": "Core benefit from description", "benefit": "Solves the audience's main problem"},
            {"point": "Ease of use", "benefit": "Saves time and effort"},
            {"point": "Quality and reliability", "benefit": "Builds confidence to buy"},
            {"point": "Distinct positioning", "benefit": "Stands out from competitors"},
        ],
        "content_tone": {
            "voice": f"{data.tone.value} and clear",
            "style_guidelines": ["Short sentences", "Benefit-first messaging", "One idea per post"],
            "words_to_use": ["discover", "simple", "trusted", "results", "new"],
            "words_to_avoid": ["cheap", "guaranteed miracle", "best ever"],
        },
        "call_to_action": {
            "primary": "Try it today",
            "alternatives": ["Learn more", "Get started now"],
        },
        "suggested_content_types": [
            {"type": "Short video", "description": "30s product story", "why_it_works": f"High reach on {p}"},
            {"type": "Carousel", "description": "Problem > solution walk-through", "why_it_works": "Saves and shares"},
            {"type": "Customer story", "description": "Real use case", "why_it_works": "Social proof"},
            {"type": "Offer post", "description": "Time-limited incentive", "why_it_works": "Drives action"},
        ],
        "success_metrics": ["Reach", "Engagement rate", "Click-through rate", "Conversion rate"],
    }

PROVIDERS = {"anthropic": _call_anthropic, "openai": _call_openai, "gemini": _call_gemini}

def active_model() -> str:
    s = get_settings()
    return {
        "anthropic": s.anthropic_model,
        "openai": s.openai_model,
        "gemini": s.gemini_model,
    }.get(s.llm_provider, "mock")

async def ping() -> dict:
    """First API request check (Step 6)."""
    s = get_settings()
    if s.llm_provider == "mock":
        return {"ok": True, "provider": "mock", "model": "mock", "reply": "Mock provider active (no API key needed)."}
    fn = PROVIDERS.get(s.llm_provider)
    if not fn:
        raise LLMError(f"Unknown LLM_PROVIDER '{s.llm_provider}'.")
    reply = await fn("You are a helpful assistant.", "Reply with exactly: Connection OK", 20)
    return {"ok": True, "provider": s.llm_provider, "model": active_model(), "reply": reply.strip()}

async def generate_strategy(data: CampaignInput) -> tuple[MarketingStrategy, str, str]:
    s = get_settings()
    if s.llm_provider == "mock":
        return MarketingStrategy(**_mock_strategy(data)), "mock", "mock"

    fn = PROVIDERS.get(s.llm_provider)
    if not fn:
        raise LLMError(f"Unknown LLM_PROVIDER '{s.llm_provider}'.")

    user_prompt = build_user_prompt(data)
    last_err = ""
    best: MarketingStrategy | None = None  # first schema-valid answer, kept as a fallback (Phase 5)
    for attempt in range(2):  # one retry: malformed output OR a failed quality check
        prompt = user_prompt if attempt == 0 else (
            user_prompt + f"\n\nYour previous reply was rejected: {last_err}. "
            "Fix exactly these problems and return ONLY the JSON object."
        )
        try:
            raw = await fn(SYSTEM_PROMPT, prompt, 3000)
        except LLMError:
            if best:
                break  # the retry failed, but we already hold a valid strategy
            raise
        except Exception as e:  # network/auth/rate-limit errors
            if best:
                break
            raise LLMError(f"{s.llm_provider} request failed: {e}") from e
        try:
            strategy = MarketingStrategy(**_extract_json(raw))
        except (json.JSONDecodeError, ValidationError, TypeError) as e:
            last_err = f"invalid JSON/schema ({str(e)[:200]})"
            log.warning("strategy attempt %d invalid: %s", attempt + 1, last_err)
            continue
        issues = quality_issues(strategy, data)  # Phase 5 quality gate
        if not issues:
            return strategy, s.llm_provider, active_model()
        best = best or strategy
        last_err = "quality problems: " + "; ".join(issues)
        log.warning("strategy attempt %d failed the quality gate: %s", attempt + 1, "; ".join(issues))
        if attempt == 1:
            log.warning("returning strategy with remaining issues: %s", "; ".join(issues))
            return strategy, s.llm_provider, active_model()
    if best:
        return best, s.llm_provider, active_model()
    raise LLMError("The AI returned an invalid strategy twice. Please try again.")