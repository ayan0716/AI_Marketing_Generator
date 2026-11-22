"""Phase 5 - logging, monitoring, security helpers (Steps 7 and 8).

* setup_logging()      - one log format for the whole app, secrets are masked, optional rotating log file
* request ids          - every request gets an X-Request-ID that appears in every log line and in error bodies
* Metrics              - in-memory counters: requests, latency, AI calls, recent failures  (GET /api/metrics)
* RateLimiter          - sliding-window limit for the expensive (AI) endpoints
* instrument_*()       - wraps the LLM / image providers so every AI call is timed and counted, without
                         touching the provider code itself

Everything is dependency-free (standard library only).
"""
from __future__ import annotations

import contextvars
import functools
import json
import logging
import re
import threading
import time
from collections import deque
from logging.handlers import RotatingFileHandler

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")

# ----------------------------------------------------------------------------- secret masking
_SECRET_PATTERNS = [
    (re.compile(r"AIza[0-9A-Za-z_\-]{20,}"), "AIza***"),  # Google AI Studio keys
    (re.compile(r"AQ\.[0-9A-Za-z_\-]{20,}"), "AQ.***"),  # Vertex express keys
    (re.compile(r"sk-[A-Za-z0-9_\-]{16,}"), "sk-***"),  # OpenAI / Anthropic style keys
    (re.compile(r"(mongodb(?:\+srv)?://)[^:/@\s]+:[^@\s]+@"), r"\1***:***@"),  # credentials in a Mongo URI
    (re.compile(r"(?i)((?:api[_-]?key|token|secret|password)[\"']?\s*[:=]\s*[\"']?)[^\s\"',}]{6,}"), r"\1***"),
]


def redact(text: str) -> str:
    """Mask anything that looks like an API key / password so it can never reach the logs."""
    for pattern, repl in _SECRET_PATTERNS:
        text = pattern.sub(repl, text)
    return text


class _ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        try:
            record.msg = redact(record.getMessage())
            record.args = ()
        except Exception:  # never let logging crash a request
            pass
        return True


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "request_id": getattr(record, "request_id", "-"),
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False)


_configured = False


def setup_logging(level: str = "INFO", json_logs: bool = False, log_file: str = "") -> None:
    """Idempotent. Call once at start-up."""
    global _configured
    if _configured:
        return
    fmt: logging.Formatter
    if json_logs:
        fmt = _JsonFormatter()
    else:
        fmt = logging.Formatter("%(asctime)s %(levelname)-7s [%(request_id)s] %(name)s: %(message)s", "%H:%M:%S")
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_file:
        handlers.append(RotatingFileHandler(log_file, maxBytes=2_000_000, backupCount=3, encoding="utf-8"))
    flt = _ContextFilter()
    root = logging.getLogger()
    for h in handlers:
        h.setFormatter(fmt)
        h.addFilter(flt)
        root.addHandler(h)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    logging.getLogger("httpx").setLevel(logging.WARNING)  # httpx logs full URLs, keep it quiet
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    _configured = True


# ----------------------------------------------------------------------------- metrics
class Metrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        with self._lock:
            self.started = time.time()
            self.requests = 0
            self.by_status: dict[str, int] = {}
            self.slowest: deque = deque(maxlen=200)  # (ms, "METHOD path")
            self.ai: dict[str, dict] = {}  # "llm:gemini" -> {calls, errors, total_ms}
            self.failures: deque = deque(maxlen=50)  # recent failed AI calls / 5xx

    def record_request(self, method: str, path: str, status: int, ms: float) -> None:
        with self._lock:
            self.requests += 1
            key = f"{status // 100}xx"
            self.by_status[key] = self.by_status.get(key, 0) + 1
            self.slowest.append((round(ms, 1), f"{method} {path}"))
            if status >= 500:
                self.failures.append({"at": _now(), "kind": "http_5xx", "where": f"{method} {path}",
                                      "status": status, "request_id": request_id_var.get()})

    def record_ai(self, kind: str, provider: str, model: str, ok: bool, ms: float, error: str = "") -> None:
        with self._lock:
            s = self.ai.setdefault(f"{kind}:{provider}", {"calls": 0, "errors": 0, "total_ms": 0.0, "model": model})
            s["calls"] += 1
            s["total_ms"] += ms
            s["model"] = model
            if not ok:
                s["errors"] += 1
                self.failures.append({"at": _now(), "kind": f"{kind}_error", "where": f"{provider}/{model}",
                                      "error": redact(error)[:300], "request_id": request_id_var.get()})

    def snapshot(self) -> dict:
        with self._lock:
            times = sorted(t for t, _ in self.slowest)
            p95 = times[int(len(times) * 0.95) - 1] if len(times) >= 20 else (times[-1] if times else 0)
            ai = {
                k: {"calls": v["calls"], "errors": v["errors"], "model": v["model"],
                    "avg_ms": round(v["total_ms"] / v["calls"], 1) if v["calls"] else 0,
                    "error_rate": round(v["errors"] / v["calls"], 3) if v["calls"] else 0}
                for k, v in self.ai.items()
            }
            return {
                "uptime_seconds": int(time.time() - self.started),
                "requests": self.requests,
                "responses_by_class": dict(self.by_status),
                "latency_ms": {"p95": p95, "max": times[-1] if times else 0},
                "slowest_requests": sorted(self.slowest, reverse=True)[:5],
                "ai_calls": ai,
                "recent_failures": list(self.failures)[-10:],
            }


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())


metrics = Metrics()
log = logging.getLogger("monitor")


# ----------------------------------------------------------------------------- AI call instrumentation
def _instrument(kind: str, provider: str, fn, model_name):
    if getattr(fn, "_instrumented", False):
        return fn

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        t0 = time.perf_counter()
        try:
            result = await fn(*args, **kwargs)
        except Exception as e:
            ms = (time.perf_counter() - t0) * 1000
            err = f"{getattr(e, 'kind', type(e).__name__)}: {e}"
            metrics.record_ai(kind, provider, model_name(), False, ms, err)
            log.warning("AI call failed kind=%s provider=%s model=%s ms=%.0f error=%s",
                        kind, provider, model_name(), ms, err[:300])
            raise
        ms = (time.perf_counter() - t0) * 1000
        metrics.record_ai(kind, provider, model_name(), True, ms)
        log.info("AI call ok kind=%s provider=%s model=%s ms=%.0f", kind, provider, model_name(), ms)
        return result

    wrapper._instrumented = True  # type: ignore[attr-defined]
    return wrapper


def instrument_providers(llm_providers: dict, image_providers: dict, llm_model, image_model) -> None:
    """Wrap every provider function in place (idempotent). Tests that add a 'fake' provider afterwards are untouched."""
    for name, fn in list(llm_providers.items()):
        llm_providers[name] = _instrument("llm", name, fn, llm_model)
    for name, fn in list(image_providers.items()):
        image_providers[name] = _instrument("image", name, fn, image_model)


# ----------------------------------------------------------------------------- rate limiting
class RateLimiter:
    """Sliding window, per client key. Memory is bounded: idle keys are dropped."""

    def __init__(self, limit: int, window: float = 60.0) -> None:
        self.limit, self.window = limit, window
        self._hits: dict[str, deque] = {}
        self._lock = threading.Lock()
        self._last_gc = time.monotonic()

    def check(self, key: str) -> tuple[bool, int]:
        """Returns (allowed, retry_after_seconds)."""
        if self.limit <= 0:
            return True, 0
        now = time.monotonic()
        with self._lock:
            q = self._hits.setdefault(key, deque())
            while q and now - q[0] > self.window:
                q.popleft()
            if len(q) >= self.limit:
                return False, max(1, int(self.window - (now - q[0])) + 1)
            q.append(now)
            if now - self._last_gc > self.window:  # occasional clean-up
                for k in [k for k, v in self._hits.items() if not v or now - v[-1] > self.window]:
                    self._hits.pop(k, None)
                self._last_gc = now
            return True, 0


# POST endpoints that call a paid LLM / image API
EXPENSIVE = re.compile(
    r"^/api/(strategies"
    r"|campaigns/[^/]+/(content|creatives)(/.*)?"
    r"|agent/runs(/[^/]+/continue)?"
    r"|agent/campaigns/[^/]+/regenerate)$"
)

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}
