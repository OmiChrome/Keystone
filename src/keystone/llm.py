"""OpenAI-compatible LLM client with rate limiting, disk cache, retries, JSON mode and usage accounting.

Works against any OpenAI-compatible endpoint (AMD TokenLab, vLLM, SGLang, Ollama, LM Studio), which is
what makes fully private / offline deployment a one-line config change.
"""

from __future__ import annotations

import contextvars
import hashlib
import json
import re
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, TypeVar

import httpx

from .config import settings

T = TypeVar("T")
R = TypeVar("R")


class LLMError(RuntimeError):
    pass


class ModelUnavailable(LLMError):
    """The model kept returning 429/5xx - callers may fall back to another model."""


# --------------------------------------------------------------------------------------------- usage


@dataclass
class CallRecord:
    model: str
    purpose: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    latency_s: float
    cached: bool


@dataclass
class UsageTracker:
    calls: list[CallRecord] = field(default_factory=list)
    started: float = field(default_factory=time.time)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add(self, rec: CallRecord) -> None:
        with self._lock:
            self.calls.append(rec)

    def summary(self) -> dict[str, Any]:
        models = sorted({c.model for c in self.calls})
        return {
            "models": models,
            "llm_calls": len(self.calls),
            "cached_calls": sum(c.cached for c in self.calls),
            "prompt_tokens": sum(c.prompt_tokens for c in self.calls),
            "completion_tokens": sum(c.completion_tokens for c in self.calls),
            "cost_usd": round(sum(c.cost_usd for c in self.calls), 6),
            "llm_latency_s": round(sum(c.latency_s for c in self.calls), 2),
            "wall_time_s": round(time.time() - self.started, 2),
            "trace": [
                {"purpose": c.purpose, "model": c.model, "cached": c.cached, "latency_s": round(c.latency_s, 2), "completion_tokens": c.completion_tokens, "cost_usd": round(c.cost_usd, 6)}
                for c in self.calls
            ],
        }


_tracker: contextvars.ContextVar[UsageTracker | None] = contextvars.ContextVar("tracker", default=None)
# optional live event sink (used by the API to stream "what is the agent doing" to the UI)
_listener: contextvars.ContextVar[list | None] = contextvars.ContextVar("listener", default=None)


def set_listener(sink: list | None) -> None:
    _listener.set(sink)


def _emit(**ev: Any) -> None:
    sink = _listener.get()
    if sink is not None:
        sink.append({"t": round(time.time(), 2), **ev})


def start_tracking() -> UsageTracker:
    t = UsageTracker()
    _tracker.set(t)
    return t


def current_tracker() -> UsageTracker | None:
    return _tracker.get()


def parallel_map(fn: Callable[[T], R], items: Iterable[T], max_workers: int = 6) -> list[R]:
    """Thread-pool map that propagates the usage-tracking context into workers."""
    items = list(items)
    if not items:
        return []
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = [ex.submit(contextvars.copy_context().run, fn, it) for it in items]
        return [f.result() for f in futures]


# --------------------------------------------------------------------------------------- rate limit


class RateLimiter:
    """Sliding-window limiter shared by every thread in the process."""

    def __init__(self, rpm: int):
        self.rpm = max(1, rpm)
        self.stamps: deque[float] = deque()
        self.lock = threading.Lock()

    def acquire(self) -> None:
        while True:
            with self.lock:
                now = time.time()
                while self.stamps and now - self.stamps[0] > 60:
                    self.stamps.popleft()
                if len(self.stamps) < self.rpm:
                    self.stamps.append(now)
                    return
                wait = 60 - (now - self.stamps[0]) + 0.05
            time.sleep(wait)


_limiter = RateLimiter(settings.rpm)
_client = httpx.Client(timeout=settings.timeout_s)


# ------------------------------------------------------------------------------------------- calls


def _cache_path(key: str):
    return settings.cache_dir / key[:2] / f"{key}.json"


def chat(
    messages: list[dict[str, Any]],
    *,
    model: str | None = None,
    purpose: str = "chat",
    json_mode: bool = False,
    temperature: float = 0.0,
    max_tokens: int = 4000,
    reasoning_effort: str | None = None,
) -> str:
    """Single chat completion. Returns the assistant text."""
    model = model or settings.model
    body: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    if reasoning_effort:
        body["reasoning_effort"] = reasoning_effort

    key = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
    tracker = current_tracker()
    if settings.cache:
        p = _cache_path(key)
        if p.exists():
            data = json.loads(p.read_text())
            if tracker:
                tracker.add(CallRecord(model, purpose, 0, 0, 0.0, 0.0, True))
            _emit(event="llm_call", purpose=purpose, model=model, cached=True, latency_s=0.0)
            return data["content"]

    if not settings.api_key:
        raise LLMError("KEYSTONE_LLM_API_KEY is not set (copy .env.example to .env)")

    last_err: Exception | None = None
    for attempt in range(3):
        _limiter.acquire()
        t0 = time.time()
        try:
            r = _client.post(
                f"{settings.base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {settings.api_key}"},
                json=body,
            )
        except httpx.TimeoutException as e:  # overloaded model: don't wait again, let the caller fall back
            _emit(event="llm_retry", purpose=purpose, model=model, status=504)
            raise ModelUnavailable(f"{model} timed out after {settings.timeout_s:.0f}s") from e
        except httpx.HTTPError as e:  # network error -> retry
            last_err = e
            time.sleep(2**attempt)
            continue
        latency = time.time() - t0
        if r.status_code == 429 or r.status_code >= 500:
            _emit(event="llm_retry", purpose=purpose, model=model, status=r.status_code)
            last_err = ModelUnavailable(f"{model} HTTP {r.status_code}: {r.text[:200]}")
            time.sleep(min(10, 2 * 2**attempt))
            continue
        if r.status_code != 200:
            raise LLMError(f"HTTP {r.status_code}: {r.text[:500]}")
        data = r.json()
        content = (data["choices"][0]["message"].get("content") or "").strip()
        usage = data.get("usage") or {}
        if tracker:
            tracker.add(
                CallRecord(
                    model,
                    purpose,
                    int(usage.get("prompt_tokens", 0)),
                    int(usage.get("completion_tokens", 0)),
                    float(usage.get("cost", 0.0) or 0.0),
                    latency,
                    False,
                )
            )
        _emit(event="llm_call", purpose=purpose, model=model, cached=False, latency_s=round(latency, 2), tokens=int(usage.get("completion_tokens", 0)))
        if not content:
            last_err = LLMError("empty completion")
            continue
        if settings.cache:
            try:
                p = _cache_path(key)
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(json.dumps({"content": content, "model": model, "purpose": purpose}))
            except OSError:  # read-only filesystem (serverless) - caching is an optimisation only
                pass
        return content
    if isinstance(last_err, (ModelUnavailable, httpx.HTTPError)) or last_err is None:
        raise ModelUnavailable(f"{model} unavailable after retries: {last_err}")
    raise LLMError(f"LLM call failed after retries: {last_err}")


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.M)


def parse_json(text: str) -> Any:
    text = _FENCE.sub("", text.strip())
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # salvage the outermost object/array
        for open_c, close_c in (("{", "}"), ("[", "]")):
            s, e = text.find(open_c), text.rfind(close_c)
            if s != -1 and e > s:
                try:
                    return json.loads(text[s : e + 1])
                except json.JSONDecodeError:
                    pass
        raise


def chat_json(
    system: str,
    user: str,
    *,
    model: str | None = None,
    purpose: str = "json",
    max_tokens: int = 6000,
    reasoning_effort: str | None = None,
    images: list[str] | None = None,
    fallbacks: list[str] | None = None,
) -> Any:
    """Chat with JSON mode; one automatic repair round-trip on malformed JSON.

    ``fallbacks``: other models to try, in order, if the primary model is unavailable."""
    chain = [model or settings.model] + [m for m in (fallbacks or []) if m != (model or settings.model)]
    last: Exception | None = None
    for round_ in range(2 if fallbacks else 1):  # shared endpoints have bad minutes: one more full pass after a pause
        if round_:
            _emit(event="llm_retry", purpose=purpose, model="all", status=0)
            time.sleep(8)
        for m in chain:
            try:
                out = _chat_json_once(system, user, model=m, purpose=purpose, max_tokens=max_tokens, reasoning_effort=reasoning_effort, images=images)
                if isinstance(out, dict):
                    out["_served_by"] = m
                return out
            except ModelUnavailable as e:
                last = e
    raise ModelUnavailable(f"all models unavailable for {purpose}: {last}")


def _chat_json_once(system, user, *, model, purpose, max_tokens, reasoning_effort, images) -> Any:
    content: Any = user
    if images:
        content = [{"type": "text", "text": user}] + [
            {"type": "image_url", "image_url": {"url": u}} for u in images
        ]
    messages = [{"role": "system", "content": system}, {"role": "user", "content": content}]
    raw = chat(
        messages,
        model=model,
        purpose=purpose,
        json_mode=True,
        max_tokens=max_tokens,
        reasoning_effort=reasoning_effort,
    )
    try:
        return parse_json(raw)
    except json.JSONDecodeError:
        fix = chat(
            messages
            + [
                {"role": "assistant", "content": raw},
                {"role": "user", "content": "That was not valid JSON. Return ONLY the corrected JSON object."},
            ],
            model=model,
            purpose=purpose + ":repair",
            json_mode=True,
            max_tokens=max_tokens,
        )
        return parse_json(fix)
