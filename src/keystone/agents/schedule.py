"""Schedule & delivery-risk specialist: which late equipment will REALLY hold up the project?

 1. CPM (Python): forward/backward pass over the activity network gives early/late dates and total float,
    and each purchase order's need-by date (late start of the activity that installs it minus a receiving
    buffer).
 2. Probabilistic delivery (lead-time specialist): every PO gets a lead-time distribution (market reference
    class x empirical supplier-promise slip).
 3. Monte Carlo schedule simulation (numpy, vectorised): thousands of joint delivery scenarios are pushed
    through the network -> project-finish distribution and P(meet target).
 4. Counterfactual attribution: for each PO we re-simulate with that PO delivered on its need-by date; the
    drop in expected finish is the delay that PO actually causes. Items are ranked by that, not by how late
    they look in isolation (an item can be late but have float; another can be "on time" but critical).
 5. Actions: rule-based mitigations tied to the numbers; an optional LLM summary is number-grounded.
"""

from __future__ import annotations

import csv
import zlib
import io
from collections import defaultdict, deque
from datetime import date, timedelta
from typing import Any

import numpy as np

from ..docs import store
from ..grounding import grounded_narrative
from ..schemas import AgentResult, Confidence, EquipmentItem, Evidence, HumanReview
from .base import run_agent
from .leadtime import forecast_item, forecast_samples

N = 5000


def _rows(csv_text: str) -> list[dict[str, str]]:
    return [{k.strip(): (v or "").strip() for k, v in r.items()} for r in csv.DictReader(io.StringIO(csv_text.strip()))]


def _topo(acts: dict[str, dict]) -> list[str]:
    indeg = {a: 0 for a in acts}
    succ = defaultdict(list)
    for a, r in acts.items():
        for p in r["preds"]:
            if p not in acts:
                raise ValueError(f"activity {a} has unknown predecessor {p}")
            indeg[a] += 1
            succ[p].append(a)
    q = deque(a for a, d in indeg.items() if d == 0)
    order = []
    while q:
        a = q.popleft()
        order.append(a)
        for s in succ[a]:
            indeg[s] -= 1
            if indeg[s] == 0:
                q.append(s)
    if len(order) != len(acts):
        raise ValueError("schedule has a dependency cycle")
    return order


SUMMARY_SYS = """Write a 4-6 sentence risk briefing for a data-center project manager using ONLY the facts JSON. Lead with \
whether the target date is at risk and the single item driving it, then the top mitigations. Do not introduce numbers \
that are not in the facts. Return JSON: {"text": str}"""


def assess(schedule_csv: str, po_csv: str, project_start: str, target_completion: str | None = None, receiving_buffer_days: int = 5, use_llm: bool = True) -> AgentResult:
    sched_doc = store().ingest_text(schedule_csv, "schedule.csv", "schedule")
    po_doc = store().ingest_text(po_csv, "purchase_orders.csv", "po")
    srows, prow = _rows(schedule_csv), _rows(po_csv)
    sched_lines, po_lines = schedule_csv.strip().splitlines(), po_csv.strip().splitlines()
    line = lambda lines, n: lines[n - 1] if 0 < n <= len(lines) else ""  # noqa: E731 - raw row text = verbatim citation
    start = date.fromisoformat(project_start)
    target = date.fromisoformat(target_completion) if target_completion else None

    acts: dict[str, dict] = {}
    for i, r in enumerate(srows, 2):  # row 1 is the header
        aid = r["activity_id"]
        acts[aid] = {
            "id": aid,
            "name": r.get("name", aid),
            "dur": float(r.get("duration_days") or 0),
            "preds": [p.strip() for p in (r.get("predecessors") or "").replace(",", ";").split(";") if p.strip()],
            "po": [p.strip() for p in (r.get("requires_po") or "").replace(",", ";").split(";") if p.strip()],
            "row": i,
        }
    order = _topo(acts)
    pos = {r["po_number"]: {**r, "row": i} for i, r in enumerate(prow, 2)}
    for a in acts.values():
        for p in a["po"]:
            if p not in pos:
                raise ValueError(f"activity {a['id']} requires unknown PO {p}")

    # ---- deterministic CPM without material constraints (the plan) ------------------------------
    es, ef = {}, {}
    for a in order:
        es[a] = max([ef[p] for p in acts[a]["preds"]], default=0.0)
        ef[a] = es[a] + acts[a]["dur"]
    plan_finish = max(ef.values())
    horizon = max(plan_finish, (target - start).days) if target else plan_finish
    succ = defaultdict(list)
    for a in order:
        for p in acts[a]["preds"]:
            succ[p].append(a)
    lf, ls = {}, {}
    for a in reversed(order):
        lf[a] = min([ls[s] for s in succ[a]], default=horizon)
        ls[a] = lf[a] - acts[a]["dur"]
    cpm = [
        {
            "activity_id": a,
            "name": acts[a]["name"],
            "duration_days": acts[a]["dur"],
            "early_start": (start + timedelta(days=es[a])).isoformat(),
            "early_finish": (start + timedelta(days=ef[a])).isoformat(),
            "late_start": (start + timedelta(days=ls[a])).isoformat(),
            "late_finish": (start + timedelta(days=lf[a])).isoformat(),
            "total_float_days": round(ls[a] - es[a], 1),
            "requires_po": acts[a]["po"],
        }
        for a in order
    ]

    # ---- need-by dates and delivery distributions ------------------------------------------------
    need_by_off: dict[str, float] = {}
    for a in order:
        for p in acts[a]["po"]:
            need_by_off[p] = min(need_by_off.get(p, 1e9), ls[a] - receiving_buffer_days)
    deliv: dict[str, np.ndarray] = {}
    po_info: dict[str, dict] = {}
    for p, r in pos.items():
        od = date.fromisoformat(r["order_date"])
        nb = start + timedelta(days=need_by_off.get(p, horizon))
        item = EquipmentItem(
            item_id=p, po_number=p, description=r.get("item", ""), vendor=r.get("vendor"), quoted_lead_weeks=float(r["quoted_lead_weeks"]) if r.get("quoted_lead_weeks") else None,
            order_date=r["order_date"], promised_date=r.get("promised_date") or None, need_by_date=nb.isoformat(), shipment_mode=r.get("shipment_mode") or None, category=r.get("category") or None,
        )
        samples, _ = forecast_samples(item, seed=zlib.crc32(p.encode()), use_llm=use_llm)
        fc = forecast_item(item, use_llm=use_llm)
        if samples is None:
            raise ValueError(f"cannot forecast delivery for {p}: no category and no quoted lead time")
        deliv[p] = (od - start).days + 7 * samples[:N]
        po_info[p] = {"row": r, "forecast": fc, "need_by": nb}

    def simulate(override: dict[str, np.ndarray] | None = None) -> tuple[np.ndarray, dict[str, np.ndarray]]:
        d = {**deliv, **(override or {})}
        EF: dict[str, np.ndarray] = {}
        ES: dict[str, np.ndarray] = {}
        for a in order:
            s = np.zeros(N)
            for p in acts[a]["preds"]:
                s = np.maximum(s, EF[p])
            for p in acts[a]["po"]:
                s = np.maximum(s, d[p] + receiving_buffer_days)
            ES[a] = s
            EF[a] = s + acts[a]["dur"]
        fin = np.max(np.stack(list(EF.values())), axis=0)
        return fin, ES

    finish, ES = simulate()
    mean_finish = float(finish.mean())
    pct = {k: (start + timedelta(days=float(np.percentile(finish, v)))).isoformat() for k, v in (("p10", 10), ("p50", 50), ("p80", 80), ("p90", 90))}
    p_target = float((finish <= (target - start).days).mean()) if target else None

    risks = []
    for p, info in po_info.items():
        nb_off = need_by_off.get(p, horizon)
        cf, _ = simulate({p: np.minimum(deliv[p], nb_off)})
        contrib = mean_finish - float(cf.mean())
        r = info["row"]
        d = deliv[p]
        p_late = float((d > nb_off).mean())
        exp_late = float(np.maximum(d - nb_off, 0).mean())
        fc = info["forecast"]
        actions = _actions(p, r, fc, p_late, contrib, info["need_by"], start, d)
        risks.append(
            {
                "po_number": p,
                "item": r.get("item"),
                "vendor": r.get("vendor"),
                "status": r.get("status"),
                "order_date": r.get("order_date"),
                "promised_date": r.get("promised_date"),
                "need_by_date": info["need_by"].isoformat(),
                "delivery_forecast": {k: (start + timedelta(days=float(np.percentile(d, v)))).isoformat() for k, v in (("p10", 10), ("p50", 50), ("p90", 90))},
                "p_late_vs_need_by": round(p_late, 3),
                "expected_days_late_vs_need_by": round(exp_late, 1),
                "expected_project_delay_caused_days": round(max(0.0, contrib), 1),
                "lead_time_forecast": fc.get("forecast"),
                "drivers": fc.get("drivers", []),
                "actions": actions,
                "evidence": [
                    Evidence(doc_id=po_doc.doc_id, doc_name=po_doc.name, locator=f"row {r['row']}", quote=line(po_lines, r["row"]), verified=True, match_score=100).model_dump(),
                    *[Evidence(doc_id=sched_doc.doc_id, doc_name=sched_doc.name, locator=f"row {acts[a]['row']}", quote=line(sched_lines, acts[a]["row"]), verified=True, match_score=100).model_dump() for a in order if p in acts[a]["po"]],
                ],
                "lead_time_sources": fc.get("evidence", []),
                "confidence": fc.get("confidence"),
            }
        )
    risks.sort(key=lambda x: (-x["expected_project_delay_caused_days"], -x["p_late_vs_need_by"]))
    for i, r in enumerate(risks, 1):
        r["rank"] = i
        r["severity"] = "critical" if r["expected_project_delay_caused_days"] >= 14 else "high" if r["expected_project_delay_caused_days"] >= 3 or r["p_late_vs_need_by"] >= 0.5 else "medium" if r["p_late_vs_need_by"] >= 0.2 else "low"

    top = risks[0]
    facts = {
        "target_completion": target_completion,
        "p_meet_target_pct": round(100 * p_target, 1) if p_target is not None else None,
        "finish_p50": pct["p50"],
        "finish_p90": pct["p90"],
        "planned_finish_without_material_risk": (start + timedelta(days=plan_finish)).isoformat(),
        "top_risks": [{k: r[k] for k in ("po_number", "item", "need_by_date", "expected_project_delay_caused_days")} | {"p_late_vs_need_by_pct": round(100 * r["p_late_vs_need_by"], 1), "delivery_p50": r["delivery_forecast"]["p50"], "actions": r["actions"][:2]} for r in risks[:3]],
    }
    tmpl = (
        (f"P(meet target {target_completion}) = {facts['p_meet_target_pct']}%. " if target else "")
        + f"Median finish {pct['p50']} (P90 {pct['p90']}). Biggest driver: {top['po_number']} {top['item']} - "
        f"{round(100 * top['p_late_vs_need_by'])}% chance of missing its need-by date {top['need_by_date']}, causing ~{top['expected_project_delay_caused_days']} days of expected project delay. "
        + (f"First action: {top['actions'][0]}" if top["actions"] else "")
    )
    briefing = grounded_narrative(SUMMARY_SYS, facts, tmpl, purpose="schedule:briefing") if use_llm else {"text": tmpl, "source": "template", "grounding_check": "llm disabled"}

    reasons = [f"{r['po_number']}: severity {r['severity']} - expected {r['expected_project_delay_caused_days']} days project delay" for r in risks if r["severity"] == "critical"]
    low_conf = [r["po_number"] for r in risks if (r["confidence"] or {}).get("score", 0) < 0.6]
    if low_conf:
        reasons.append(f"low-confidence lead-time forecasts for {', '.join(low_conf)}")
    conf_score = float(np.mean([(r["confidence"] or {}).get("score", 0.5) for r in risks]))
    return AgentResult(
        agent="schedule_risk",
        summary=briefing["text"],
        result={
            "project_start": project_start,
            "target_completion": target_completion,
            "simulation": {"scenarios": N, "receiving_buffer_days": receiving_buffer_days, "finish_dates": pct, "p_meet_target": round(p_target, 3) if p_target is not None else None, "planned_finish_without_material_risk": facts["planned_finish_without_material_risk"]},
            "risks": risks,
            "cpm": cpm,
            "briefing": briefing,
        },
        confidence=Confidence.from_score(conf_score, rationale="mean lead-time forecast confidence across POs"),
        human_review=HumanReview(required=bool(reasons), reasons=reasons),
    )


def _actions(po: str, row: dict, fc: dict, p_late: float, contrib: float, need_by: date, start: date, d: np.ndarray) -> list[str]:
    acts = []
    f = fc.get("forecast") or {}
    status = (row.get("status") or "").lower()
    if contrib >= 3 or p_late >= 0.5:
        if any(k in status for k in ("review", "resubmit", "returned")):
            acts.append(f"Submittal is not approved ('{row.get('status')}') - fast-track review this week; release to manufacture is gated on it (run spec_compliance on the resubmittal)")
        acts.append(f"Ask {row.get('vendor')} for a confirmed factory production slot and ship date in writing; hold weekly expediting calls")
        lo = f.get("latest_order_date_for_p80")
        if lo and lo < row.get("order_date", ""):
            acts.append(f"Order date {row.get('order_date')} is after the latest order date for 80% confidence ({lo}) - qualify an alternate source or equivalent product")
        if (row.get("shipment_mode") or "").lower() == "ocean":
            acts.append("Price air freight or split shipment for the final leg (ocean shipments arrive late 17.8% of the time in the historical data)")
        acts.append(f"Resequence: look for work that can proceed before {need_by.isoformat()} (temporary power / load banks for commissioning) to buy float")
    elif p_late >= 0.2:
        acts.append("Monitor: request monthly fabrication progress reports and photos")
    else:
        acts.append("No action beyond routine tracking")
    return acts


def assess_schedule_risk(schedule_csv: str, po_csv: str, project_start: str, target_completion: str | None = None, receiving_buffer_days: int = 5, use_llm: bool = True) -> AgentResult:
    return run_agent(
        "schedule_risk",
        {"project_start": project_start, "target_completion": target_completion, "receiving_buffer_days": receiving_buffer_days},
        lambda: assess(schedule_csv, po_csv, project_start, target_completion, receiving_buffer_days, use_llm),
    )
