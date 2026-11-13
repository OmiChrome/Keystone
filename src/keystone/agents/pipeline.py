"""Package pipeline: the specialists chained into one procurement decision.

  bids --(bid_leveling)--> recommended vendor + its quoted lead time
       --(spec_compliance on that vendor's submittal)--> deviations / stamp
       --(schedule_risk with the vendor's quoted lead time fed into the PO)--> project impact
  ==> a single "package readiness" decision with every hand-off logged.

Each hand-off uses the shared keystone/1.0 envelope, so Amber could run any step on its own.
"""

from __future__ import annotations

import csv
import io
from datetime import date, timedelta
from typing import Any

from ..schemas import AgentResult, Confidence, HumanReview
from .base import run_agent
from .bids import level
from .compliance import assess as compliance_assess
from .schedule import assess as schedule_assess


def _patch_po(po_csv: str, po_number: str, vendor: str, lead_weeks: float) -> str:
    rows = list(csv.DictReader(io.StringIO(po_csv.strip())))
    for r in rows:
        if r["po_number"] == po_number:
            r["vendor"] = vendor
            r["quoted_lead_weeks"] = f"{lead_weeks:g}"
            r["promised_date"] = (date.fromisoformat(r["order_date"]) + timedelta(weeks=lead_weeks)).isoformat()
    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)
    return out.getvalue()


def run(
    bid_doc_ids: list[str],
    spec_doc_id: str,
    submittal_doc_id: str,
    schedule_csv: str,
    po_csv: str,
    package_po: str,
    project_start: str,
    target_completion: str | None = None,
    scope: list[str] | None = None,
) -> AgentResult:
    trail: list[dict[str, Any]] = []
    bids = level(bid_doc_ids, scope)
    rec = bids.result["recommendation"]
    winner = next(b for b in bids.result["bids"] if b["bidder"] == rec["bidder"])
    trail.append({"step": 1, "agent": "bid_leveling", "output": bids.summary, "handoff": {"vendor": rec["bidder"], "lead_time_weeks": winner["lead_time_weeks"]}})

    comp = compliance_assess(spec_doc_id, submittal_doc_id)
    trail.append({"step": 2, "agent": "spec_compliance", "output": comp.summary, "handoff": {"stamp": comp.result["recommended_action"], "critical_issues": comp.result["critical_issues"]}})

    po2 = _patch_po(po_csv, package_po, rec["bidder"], winner["lead_time_weeks"]) if winner.get("lead_time_weeks") else po_csv
    sched = schedule_assess(schedule_csv, po2, project_start, target_completion)
    pkg = next((r for r in sched.result["risks"] if r["po_number"] == package_po), None)
    trail.append({"step": 3, "agent": "schedule_risk", "output": sched.summary, "handoff": {"package_po_risk": pkg and {k: pkg[k] for k in ("p_late_vs_need_by", "expected_project_delay_caused_days", "need_by_date")}}})

    blockers = []
    if comp.result["recommended_action"] != "Approved":
        dev = [f"{f['ref']} {f['title']}" for f in comp.result["findings"] if f["verdict"] in ("deviate", "missing")]
        blockers.append(f"Submittal from {rec['bidder']} is '{comp.result['recommended_action']}': {len(dev)} deviation(s)/omission(s) - " + "; ".join(dev[:6]))
    if pkg and pkg["expected_project_delay_caused_days"] >= 3:
        blockers.append(f"{package_po} with {rec['bidder']}'s {winner['lead_time_weeks']:g}-week lead time is expected to delay the project ~{pkg['expected_project_delay_caused_days']} days (P(late vs need-by {pkg['need_by_date']}) = {100 * pkg['p_late_vs_need_by']:.0f}%)")
    for r in winner["risks"]:
        blockers.append(f"Bid condition: {r}")
    decision = "Award with conditions" if blockers else "Ready to award"
    conf = min(bids.confidence.score, comp.confidence.score, sched.confidence.score)
    reasons = list(dict.fromkeys(bids.human_review.reasons + comp.human_review.reasons[:5] + sched.human_review.reasons))
    return AgentResult(
        agent="package_pipeline",
        summary=f"{decision}: {rec['bidder']} (leveled {rec['leveled_total']:,.0f}). {len(blockers)} condition(s) before release to manufacture.",
        result={
            "decision": decision,
            "vendor": rec["bidder"],
            "conditions": blockers,
            "trail": trail,
            "steps": {"bid_leveling": bids.model_dump(), "spec_compliance": comp.model_dump(), "schedule_risk": sched.model_dump()},
        },
        confidence=Confidence.from_score(conf, {"bid_leveling": bids.confidence.score, "spec_compliance": comp.confidence.score, "schedule_risk": sched.confidence.score}, "weakest link of the three specialists"),
        human_review=HumanReview(required=True, reasons=["Award is a commercial commitment - always requires sign-off"] + reasons),
    )


def run_package_pipeline(**kw) -> AgentResult:
    inputs = {k: v for k, v in kw.items() if not k.endswith("_csv")}
    return run_agent("package_pipeline", inputs, lambda: run(**kw))
