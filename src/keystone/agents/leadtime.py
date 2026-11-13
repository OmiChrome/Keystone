"""Lead-time forecasting specialist: honest ranges, not single guesses.

Model (fully transparent, no LLM needed for the numbers):
  * Reference class - published 2025-26 market lead-time ranges per equipment category (every number
    cites its source, see data/leadtime_reference.json), fitted as a log-normal through P10/P50/P90.
  * Supplier promise - if the vendor quoted a lead time, we model the real delivery as
    quote x slip, where slip is drawn from the EMPIRICAL distribution of how far 4,124 real shipments
    slipped past their promised date (USAID SCMS public data, by shipment mode).
  * Blend - Monte Carlo mixture of the two, weighted by how plausible the quote is relative to the market
    (quotes far below market are treated sceptically and flagged).
The LLM is only used to classify free-text item descriptions into a category when keywords are ambiguous;
items that match no category are returned with no forecast and handed to a human.
"""

from __future__ import annotations

import json
import math
from datetime import date, timedelta
from functools import lru_cache
from importlib import resources
from typing import Any

import numpy as np

from ..llm import chat_json
from ..schemas import AgentResult, Confidence, EquipmentItem, Evidence, HumanReview
from .base import run_agent

Z90 = 1.2815515655446004
N_SAMPLES = 20000


@lru_cache
def reference() -> dict:
    return json.loads(resources.files("keystone.data").joinpath("leadtime_reference.json").read_text())


@lru_cache
def promise_model() -> dict:
    return json.loads(resources.files("keystone.data").joinpath("promise_reliability.json").read_text())


CLASSIFY_SYS = """Classify a construction equipment line item into exactly one category id from the list, or "unknown" \
if none fits. Return JSON: {"category": str, "confidence": number (0-1), "reason": str (<=15 words)}"""


def classify(description: str, use_llm: bool = True) -> tuple[str | None, float, str]:
    cats = reference()["categories"]
    d = description.lower()
    scores = {cid: sum(1 for k in c["keywords"] if k in d) for cid, c in cats.items()}
    best = sorted(scores.items(), key=lambda kv: -kv[1])
    if best[0][1] >= 1 and (len(best) == 1 or best[0][1] > best[1][1]):
        return best[0][0], min(0.95, 0.75 + 0.1 * best[0][1]), f"keyword match ({best[0][1]} keywords)"
    if not use_llm:
        return None, 0.0, "no unambiguous keyword match"
    opts = {cid: c["label"] for cid, c in cats.items()}
    out = chat_json(CLASSIFY_SYS, f"Categories: {json.dumps(opts)}\nItem: {description}", purpose="leadtime:classify", max_tokens=300)
    cat = out.get("category")
    if cat not in cats:
        return None, 0.0, out.get("reason", "no matching category")
    return cat, float(out.get("confidence", 0.6)) * 0.9, "LLM classification: " + out.get("reason", "")


def _lognormal(p10: float, p50: float, p90: float, rng: np.random.Generator, n: int) -> np.ndarray:
    mu = math.log(p50)
    sigma = max(0.05, (math.log(p90) - math.log(p10)) / (2 * Z90))
    return rng.lognormal(mu, sigma, n)


def _slip_samples(mode: str | None, rng: np.random.Generator, n: int) -> tuple[np.ndarray, dict]:
    pm = promise_model()
    prof = pm["by_shipment_mode"].get(mode or "", None)
    if not prof or prof["n"] < 100 or not prof["late_slip_ratio_samples"]:
        prof_used, label = pm["overall"], "all modes"
    else:
        prof_used, label = prof, mode
    late = np.array(pm["overall"]["late_slip_ratio_samples"] if not prof_used["late_slip_ratio_samples"] else prof_used["late_slip_ratio_samples"])
    is_late = rng.random(n) < prof_used["p_late"]
    s = np.ones(n)
    s[is_late] = rng.choice(late, is_late.sum())
    return s, {"basis": label, "n_shipments": prof_used["n"], "p_late": prof_used["p_late"], "median_slip_if_late": prof_used["slip_ratio_quantiles_given_late"].get("p50")}


def forecast_samples(item: EquipmentItem, seed: int = 7, use_llm: bool = True) -> tuple[np.ndarray | None, dict]:
    """Return lead-time samples in weeks plus an explanation dict."""
    rng = np.random.default_rng(seed)
    cats = reference()["categories"]
    cat, cat_conf, cat_reason = (item.category, 0.95, "provided by caller") if item.category in cats else classify(item.description, use_llm)
    info: dict[str, Any] = {"category": cat, "category_confidence": round(cat_conf, 3), "category_reason": cat_reason}
    q = item.quoted_lead_weeks
    if cat is None and not q:
        return None, info
    ref = cats.get(cat) if cat else None
    parts, weights = [], []
    if ref:
        ref_s = _lognormal(ref["p10"], ref["p50"], ref["p90"], rng, N_SAMPLES)
        info["reference_class"] = {"label": ref["label"], "p10": ref["p10"], "p50": ref["p50"], "p90": ref["p90"], "sources": ref["sources"]}
    if q:
        slip, slip_info = _slip_samples(item.shipment_mode, rng, N_SAMPLES)
        quote_s = q * slip
        info["supplier_promise"] = {"quoted_weeks": q, **slip_info}
        if ref:
            if q < ref["p10"]:
                w, pos = 0.45, "below the market P10 - optimistic quote, treated sceptically"
            elif q > ref["p90"]:
                w, pos = 0.8, "above the market P90 - vendor is signalling a long backlog"
            else:
                w, pos = 0.7, "within the market range"
            info["supplier_promise"]["position_vs_market"] = pos
            pick = rng.random(N_SAMPLES) < w
            samples = np.where(pick, quote_s, ref_s)
            info["blend"] = {"weight_on_quote": w, "weight_on_market": round(1 - w, 2)}
        else:
            samples = quote_s
            info["blend"] = {"weight_on_quote": 1.0, "weight_on_market": 0.0, "note": "no reference class - quote only"}
    else:
        samples = ref_s
        info["blend"] = {"weight_on_quote": 0.0, "weight_on_market": 1.0}
    return samples, info


def _date(s: str | None) -> date | None:
    try:
        return date.fromisoformat(s) if s else None
    except ValueError:
        return None


def forecast_item(item: EquipmentItem, use_llm: bool = True) -> dict:
    samples, info = forecast_samples(item, use_llm=use_llm)
    out: dict[str, Any] = {"item": item.model_dump(), **info}
    reasons = []
    if samples is None:
        out["forecast"] = None
        reasons.append("item matches no known equipment category and no vendor quote was given - cannot forecast without guessing")
        out["confidence"] = Confidence.from_score(0.0, rationale="no basis for a forecast").model_dump()
        out["needs_human"], out["review_reasons"] = True, reasons
        return out
    p = {k: round(float(np.percentile(samples, v)), 1) for k, v in (("p10", 10), ("p50", 50), ("p80", 80), ("p90", 90))}
    fc: dict[str, Any] = {"lead_time_weeks": p}
    od = _date(item.order_date)
    if od:
        fc["arrival_dates"] = {k: (od + timedelta(weeks=v)).isoformat() for k, v in p.items()}
        if item.promised_date and _date(item.promised_date):
            pw = (_date(item.promised_date) - od).days / 7
            fc["p_late_vs_promise"] = round(float((samples > pw + 1e-9).mean()), 3)
        nb = _date(item.need_by_date)
        if nb:
            nw = (nb - od).days / 7
            fc["p_on_time_vs_need_by"] = round(float((samples <= nw).mean()), 3)
            fc["need_by_weeks_from_order"] = round(nw, 1)
            fc["latest_order_date_for_p80"] = (nb - timedelta(weeks=p["p80"])).isoformat()
    out["forecast"] = fc

    drivers = []
    if "reference_class" in info:
        rc = info["reference_class"]
        drivers.append(f"Market reference class '{rc['label']}': P10 {rc['p10']} / P50 {rc['p50']} / P90 {rc['p90']} weeks ({len(rc['sources'])} published sources)")
    if "supplier_promise" in info:
        sp = info["supplier_promise"]
        drivers.append(f"Vendor quoted {sp['quoted_weeks']:g} weeks ({sp.get('position_vs_market', 'no market reference')})")
        drivers.append(f"Historical promise reliability ({sp['basis']}, n={sp['n_shipments']}): {100 * sp['p_late']:.1f}% of deliveries arrived after the promised date; median slip when late x{sp['median_slip_if_late']}")
    out["drivers"] = drivers
    out["evidence"] = [Evidence(doc_id="reference", doc_name=s["claim"], quote=s["claim"], url=s["url"], verified=True, match_score=100).model_dump() for s in info.get("reference_class", {}).get("sources", [])]

    factors = {"category_match": info["category_confidence"] if info["category"] else 0.3, "has_vendor_quote": 1.0 if item.quoted_lead_weeks else 0.4, "source_count": min(1.0, len(info.get("reference_class", {}).get("sources", [])) / 2)}
    score = 0.45 * factors["category_match"] + 0.3 * factors["has_vendor_quote"] + 0.25 * factors["source_count"]
    if info["category"] is None:
        reasons.append("no market reference class - forecast relies on the vendor quote alone")
    if info.get("supplier_promise", {}).get("position_vs_market", "").startswith("below"):
        reasons.append("vendor quote is below the market P10 - confirm the quote in writing (factory slot, raw materials)")
        score = min(score, 0.65)
    out["confidence"] = Confidence.from_score(score, factors).model_dump()
    out["needs_human"] = bool(reasons) and score < 0.7
    out["review_reasons"] = reasons
    return out


def predict(items: list[dict], use_llm: bool = True) -> AgentResult:
    eq = [EquipmentItem(**{k: v for k, v in it.items() if k in EquipmentItem.model_fields}) for it in items]
    rows = [forecast_item(e, use_llm) for e in eq]
    flagged = [r for r in rows if r["needs_human"]]
    conf = sum(r["confidence"]["score"] for r in rows) / max(1, len(rows))
    parts = []
    for r in rows:
        f = r.get("forecast")
        if f:
            lt = f["lead_time_weeks"]
            parts.append(f"{r['item']['item_id']}: P50 {lt['p50']:g} wks (P10-P90 {lt['p10']:g}-{lt['p90']:g})")
    return AgentResult(
        agent="lead_time",
        summary="; ".join(parts) or "no forecasts",
        result={"forecasts": rows, "method": "reference-class log-normal x empirical promise-slip Monte Carlo", "calibration": promise_model().get("calibration_test")},
        confidence=Confidence.from_score(conf, rationale="mean item confidence"),
        human_review=HumanReview(required=bool(flagged), reasons=[f"{r['item']['item_id']}: {'; '.join(r['review_reasons'])}" for r in flagged]),
    )


def predict_lead_times(items: list[dict], use_llm: bool = True) -> AgentResult:
    return run_agent("lead_time", {"n_items": len(items)}, lambda: predict(items, use_llm))
