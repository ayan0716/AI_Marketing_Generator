"""Phase 3 - image-generation API integration (Steps 3, 6, 9).

Providers: gemini (Gemini image models, key shared with the text LLM) | openai (gpt-image-1) | mock (offline).
Every provider returns a validated GeneratedImage or raises ImageError with a *kind* the UI can explain:
  rate_limit | quota | auth | config | safety | invalid_response | timeout | network | server | bad_request
Transient problems (429 with a short wait, 5xx, timeouts, broken images) are retried with backoff.
"""

import asyncio
import base64
import binascii
import io
import re
from dataclasses import dataclass

import httpx
from PIL import Image

from config import get_settings

class ImageError(Exception):
    def __init__(self, kind: str, message: str, retryable: bool = False, retry_after: float | None = None):
        super().__init__(message)
        self.kind, self.message, self.retryable, self.retry_after = kind, message, retryable, retry_after

    def to_dict(self) -> dict:
        return {"kind": self.kind, "message": self.message,
                "retry_after": int(self.retry_after) if self.retry_after else None}

FATAL_KINDS = {"auth", "config", "quota"}  # retrying / trying other images cannot help

@dataclass
class ProductRef:
    data: bytes
    mime: str = "image/png"

@dataclass
class GeneratedImage:
    data: bytes  # validated JPEG
    width: int
    height: int
    provider: str
    model: str

MAX_TRIES = 3
BACKOFF_BASE = 1.5      # seconds; tests set this to 0
RETRY_AFTER_CAP = 20    # longer waits are reported to the user instead of blocking the request
PRODUCT_CAPABLE = {"gemini", "openai", "mock"}

def _client() -> httpx.AsyncClient:  # indirection so tests can inject a mock transport
    return httpx.AsyncClient(timeout=150)

# ---------------- validation (invalid responses) ----------------
def finalize_image(data: bytes, spec: dict, provider: str, model: str) -> GeneratedImage:
    """Decode, sanity-check, crop to the platform aspect ratio, cap the size and re-encode as JPEG."""
    try:
        im = Image.open(io.BytesIO(data))
        im.load()
    except Exception:
        raise ImageError("invalid_response", "The image service returned data that is not a valid image.", retryable=True)
    if min(im.size) < 256:
        raise ImageError("invalid_response", f"The image service returned a tiny image ({im.width}x{im.height}).", retryable=True)
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, mask=im.split()[-1])
        im = bg
    else:
        im = im.convert("RGB")
    target = spec["ratio"]
    if abs(im.width / im.height - target) / target > 0.02:  # center-crop to the exact platform ratio
        if im.width / im.height > target:
            w = round(im.height * target)
            x = (im.width - w) // 2
            im = im.crop((x, 0, x + w, im.height))
        else:
            h = round(im.width / target)
            y = (im.height - h) // 2
            im = im.crop((0, y, im.width, y + h))
    if im.width > spec["width"]:
        im = im.resize((spec["width"], round(spec["width"] / target)), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=92, optimize=True)
    return GeneratedImage(buf.getvalue(), im.width, im.height, provider, model)

# ---------------- HTTP error mapping ----------------
def _retry_after(r: httpx.Response, body: dict) -> float | None:
    h = r.headers.get("retry-after")
    if h and h.replace(".", "", 1).isdigit():
        return float(h)
    for d in (body.get("error", {}).get("details") or []):  # Gemini: {"retryDelay": "34s"}
        m = re.match(r"([\d.]+)s", str(d.get("retryDelay", "")))
        if m:
            return float(m.group(1))
    return None

def http_error(provider: str, r: httpx.Response) -> ImageError:
    try:
        body = r.json()
    except Exception:
        body = {}
    err = body.get("error", {}) if isinstance(body, dict) else {}
    msg = (err.get("message") if isinstance(err, dict) else str(err)) or r.text[:200]
    low = msg.lower()
    code = r.status_code
    ra = _retry_after(r, body if isinstance(body, dict) else {})
    if code == 429:
        if "limit: 0" in low or "billing" in low or "insufficient_quota" in low or ("exceeded your current quota" in low and ra is None):
            return ImageError("quota", f"{provider} image generation has no available quota on this API key/plan. "
                              "Enable billing for image generation, wait for the quota to reset, or switch IMAGE_PROVIDER.")
        wait = f" Try again in about {int(ra)}s." if ra else " Please wait a moment and retry."
        return ImageError("rate_limit", f"{provider} rate limit reached.{wait}", retryable=(ra is None or ra <= RETRY_AFTER_CAP), retry_after=ra)
    if code in (401, 403):
        return ImageError("auth", f"{provider} rejected the API key ({code}). Check the key in backend/.env and restart the backend.")
    if code == 400 or code == 422:
        if any(w in low for w in ("safety", "policy", "moderation", "blocked", "prohibited")):
            return ImageError("safety", "The request was blocked by the provider's safety filter. Rephrase the instructions and try again.")
        return ImageError("bad_request", f"{provider} rejected the request: {msg[:200]}")
    if code == 404:
        return ImageError("bad_request", f"{provider}: model or endpoint not found ({msg[:120]}).")
    if code in (408, 504):
        return ImageError("timeout", f"{provider} took too long to respond.", retryable=True)
    if code >= 500:
        return ImageError("server", f"{provider} is having problems ({code}).", retryable=True)
    return ImageError("bad_request", f"{provider} error {code}: {msg[:200]}")

async def _post(client: httpx.AsyncClient, provider: str, url: str, **kw) -> httpx.Response:
    try:
        r = await client.post(url, **kw)
    except httpx.TimeoutException:
        raise ImageError("timeout", f"{provider} did not answer in time.", retryable=True)
    except httpx.HTTPError as e:
        raise ImageError("network", f"Cannot reach {provider} ({e.__class__.__name__}).", retryable=True)
    if r.status_code != 200:
        raise http_error(provider, r)
    return r

async def _with_retries(factory):
    for attempt in range(MAX_TRIES):
        try:
            return await factory()
        except ImageError as e:
            if not e.retryable or attempt == MAX_TRIES - 1:
                raise
            await asyncio.sleep(min(e.retry_after or BACKOFF_BASE * (2 ** attempt), RETRY_AFTER_CAP))

def _b64(s: str) -> bytes:
    try:
        return base64.b64decode(s, validate=False)
    except (binascii.Error, ValueError):
        raise ImageError("invalid_response", "The image service returned corrupt image data.", retryable=True)

# ---------------- Gemini ----------------
_DEV_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
_VERTEX_URL = "https://aiplatform.googleapis.com/v1/publishers/google/models/{model}:generateContent"
_SAFETY_FINISH = {"SAFETY", "IMAGE_SAFETY", "PROHIBITED_CONTENT", "IMAGE_PROHIBITED_CONTENT", "BLOCKLIST", "SPII", "RECITATION"}

def parse_gemini(body: dict) -> bytes:
    reason = (body.get("promptFeedback") or {}).get("blockReason")
    if reason:
        raise ImageError("safety", f"The prompt was blocked by the safety filter ({reason}). Edit the instructions and try again.")
    cands = body.get("candidates") or []
    if not cands:
        raise ImageError("invalid_response", "The image service returned no result.", retryable=True)
    parts = (cands[0].get("content") or {}).get("parts") or []
    for p in parts:
        d = p.get("inlineData") or p.get("inline_data")
        if d and d.get("data"):
            return _b64(d["data"])
    if cands[0].get("finishReason") in _SAFETY_FINISH:
        raise ImageError("safety", "The image was blocked by the safety filter. Rephrase the instructions and try again.")
    text = "".join(p.get("text", "") for p in parts).strip()[:140]
    raise ImageError("invalid_response", "The model returned no image" + (f" (it said: '{text}')." if text else "."), retryable=True)

async def _gemini(prompt: str, spec: dict, product: ProductRef | None) -> GeneratedImage:
    s = get_settings()
    key = s.gemini_api_key
    if not key:
        raise ImageError("config", "GEMINI_API_KEY is not set in backend/.env (restart the backend after editing it).")
    endpoints = [_VERTEX_URL, _DEV_URL] if key.startswith("AQ.") else [_DEV_URL, _VERTEX_URL]
    models = [s.gemini_image_model] + [m.strip() for m in s.gemini_image_fallback_models.split(",") if m.strip()]
    parts = []
    if product:
        parts.append({"inline_data": {"mime_type": product.mime, "data": base64.b64encode(product.data).decode()}})
    parts.append({"text": prompt})
    payload = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {"responseModalities": ["TEXT", "IMAGE"], "imageConfig": {"aspectRatio": spec["aspect"]}},
    }
    last: ImageError | None = None
    async with _client() as client:
        for model in (m.removeprefix("models/") for m in models):
            auth_err = None
            for tpl in endpoints:
                async def once(url=tpl.format(model=model)):
                    r = await _post(client, "Gemini", url, headers={"x-goog-api-key": key}, json=payload)
                    try:
                        body = r.json()
                    except Exception:
                        raise ImageError("invalid_response", "Gemini returned a response that is not valid JSON.", retryable=True)
                    return finalize_image(parse_gemini(body), spec, "gemini", model)
                try:
                    return await _with_retries(once)
                except ImageError as e:
                    last = e
                    if e.kind == "auth":
                        auth_err = e
                        continue  # the other endpoint style may accept this key
                    if e.kind in ("safety", "config"):
                        raise
                    break  # try the next fallback model
            else:
                if auth_err:
                    raise auth_err
    raise last or ImageError("server", "Gemini image generation failed.")

# ---------------- OpenAI ----------------
async def _openai(prompt: str, spec: dict, product: ProductRef | None) -> GeneratedImage:
    s = get_settings()
    if not s.openai_api_key:
        raise ImageError("config", "OPENAI_API_KEY is not set in backend/.env (restart the backend after editing it).")
    model = s.openai_image_model
    headers = {"Authorization": f"Bearer {s.openai_api_key}"}
    data = {"model": model, "prompt": prompt, "size": spec["openai_size"], "quality": s.openai_image_quality, "n": "1"}

    async with _client() as client:
        async def once():
            if product:  # image edit: the product photo is the reference image
                ext = "png" if "png" in product.mime else "jpg"
                r = await _post(client, "OpenAI", "https://api.openai.com/v1/images/edits", headers=headers, data=data,
                                files={"image": (f"product.{ext}", product.data, product.mime)})
            else:
                r = await _post(client, "OpenAI", "https://api.openai.com/v1/images/generations", headers=headers, json=data)
            try:
                item = (r.json().get("data") or [None])[0] or {}
            except Exception:
                raise ImageError("invalid_response", "OpenAI returned a response that is not valid JSON.", retryable=True)
            if item.get("b64_json"):
                raw = _b64(item["b64_json"])
            elif item.get("url"):
                raw = (await _post_get(client, item["url"]))
            else:
                raise ImageError("invalid_response", "OpenAI returned no image.", retryable=True)
            return finalize_image(raw, spec, "openai", model)
        return await _with_retries(once)

async def _post_get(client: httpx.AsyncClient, url: str) -> bytes:
    try:
        r = await client.get(url)
        r.raise_for_status()
        return r.content
    except httpx.HTTPError:
        raise ImageError("network", "Could not download the generated image.", retryable=True)

# ---------------- Mock (offline) ----------------
async def _mock(prompt: str, spec: dict, product: ProductRef | None) -> GeneratedImage:
    from mock_images import render_mock  # local import keeps Pillow drawing code out of the hot path
    data = await asyncio.to_thread(render_mock, prompt, spec, product.data if product else None)
    return finalize_image(data, spec, "mock", "mock")

IMAGE_PROVIDERS = {"gemini": _gemini, "openai": _openai, "mock": _mock}

def active_model() -> str:
    s = get_settings()
    return {"gemini": s.gemini_image_model, "openai": s.openai_image_model}.get(s.image_provider, "mock")

def provider_status() -> dict:
    s = get_settings()
    p = s.image_provider
    key_ok = {"gemini": bool(s.gemini_api_key), "openai": bool(s.openai_api_key), "mock": True}.get(p, False)
    notice = None
    if p == "mock":
        notice = "Offline preview mode: images are generated locally as placeholders. Set IMAGE_PROVIDER=gemini or openai in backend/.env for real AI images."
    elif p not in IMAGE_PROVIDERS:
        notice = f"Unknown IMAGE_PROVIDER '{p}'. Use gemini, openai or mock."
    elif not key_ok:
        notice = f"The API key for {p} is missing in backend/.env."
    return {"provider": p, "model": active_model(), "ready": p in IMAGE_PROVIDERS and key_ok,
            "supports_product_image": p in PRODUCT_CAPABLE, "notice": notice}

async def generate_image(prompt: str, spec: dict, product: ProductRef | None) -> GeneratedImage:
    p = get_settings().image_provider
    fn = IMAGE_PROVIDERS.get(p)
    if not fn:
        raise ImageError("config", f"Unknown IMAGE_PROVIDER '{p}'. Use gemini, openai or mock.")
    return await fn(prompt, spec, product)
