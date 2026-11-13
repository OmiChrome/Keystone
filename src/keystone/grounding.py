"""Numeric grounding guard for LLM-written narratives.

Any number in a model-written memo must exist in the computed facts it was given (allowing for
thousand/million formatting). Otherwise the narrative is rejected and a template is used instead.
"""

from __future__ import annotations

import json
import re
from typing import Any

from .config import settings
from .llm import chat_json

_NUMS = re.compile(r"(?<![A-Za-z])\d[\d,]*(?:\.\d+)?")


def _collect(x: Any, out: set[float]) -> None:
    if isinstance(x, bool):
        return
    if isinstance(x, (int, float)):
        out.add(float(x))
    elif isinstance(x, dict):
        for k, v in x.items():
            _collect(k, out)
            _collect(v, out)
    elif isinstance(x, (list, tuple)):
        for v in x:
            _collect(v, out)
    elif isinstance(x, str):
        for m in _NUMS.findall(x):
            try:
                out.add(float(m.replace(",", "")))
            except ValueError:
                pass


def unsupported_numbers(text: str, facts: Any) -> list[str]:
    allowed: set[float] = set()
    _collect(facts, allowed)
    bad = []
    for m in _NUMS.findall(text):
        try:
            v = float(m.replace(",", ""))
        except ValueError:
            continue
        if v <= 12 and v == int(v):  # small counts / ordinals
            continue
        ok = any(
            abs(v - a) <= max(0.051, 0.0005 * abs(a))  # same number
            or abs(v * 1e3 - a) <= 0.05 * abs(a)  # "1,068k"
            or abs(v * 1e6 - a) <= 0.05 * abs(a)  # "1.07M"
            or abs(round(a) - v) < 0.51  # rounding
            or abs(100 * a - v) < 0.6  # fraction shown as %
            for a in allowed
        )
        if not ok:
            bad.append(m)
    return bad


def grounded_narrative(system: str, facts: dict, template: str, purpose: str, key: str = "text") -> dict:
    try:
        text = chat_json(system, json.dumps(facts, indent=1, default=str), purpose=purpose, max_tokens=1500, fallbacks=list(settings.fallback_models)).get(key, "")
    except Exception as e:  # narrative is optional - never fail the agent for it
        text, err = "", str(e)
    else:
        err = ""
    bad = unsupported_numbers(text, facts) if text else []
    if text and not bad:
        return {"text": text, "source": "model", "grounding_check": "passed"}
    return {
        "text": template,
        "source": "template",
        "grounding_check": f"model narrative rejected: unsupported numbers {bad}" if bad else (f"model error: {err}" if err else "no model narrative"),
    }
