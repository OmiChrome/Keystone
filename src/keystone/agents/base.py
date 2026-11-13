"""Common runner: usage tracking, error capture, audit log persistence for every specialist."""

from __future__ import annotations

import json
import time
import traceback
from typing import Any, Callable

from ..config import settings
from ..llm import start_tracking
from ..schemas import AgentResult, Confidence, HumanReview, Usage


def run_agent(agent: str, inputs: dict[str, Any], fn: Callable[[], AgentResult]) -> AgentResult:
    tracker = start_tracking()
    t0 = time.time()
    try:
        res = fn()
    except Exception as e:  # never crash the caller: return a structured error the orchestrator can act on
        res = AgentResult(
            agent=agent,
            status="error",
            summary=f"{type(e).__name__}: {e}",
            confidence=Confidence.from_score(0.0, rationale="agent failed"),
            human_review=HumanReview(required=True, reasons=[f"agent error: {e}"]),
            result={"traceback": traceback.format_exc(limit=4)},
        )
    res.agent = agent
    res.inputs = inputs
    u = tracker.summary()
    u["wall_time_s"] = round(time.time() - t0, 2)
    res.usage = Usage(**u)
    if res.status != "error" and res.human_review.required:
        res.status = "needs_human_review"
    persist(res)
    return res


def persist(res: AgentResult) -> None:
    try:
        d = settings.runs_dir / "results"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{res.run_id}.json").write_text(res.model_dump_json(indent=1))
    except OSError:  # audit log is best-effort on read-only filesystems
        pass


def load_run(run_id: str) -> dict:
    p = settings.runs_dir / "results" / f"{run_id}.json"
    return json.loads(p.read_text())
