"""Bid leveling specialist.

 1. Per-bid structured extraction (LLM): line items, stated total, exclusions, qualifications, warranty,
    validity, lead time - each with a verbatim quote that is verified against the PDF.
 2. Scope mapping (LLM): every scope item -> included / excluded / qualified / not_mentioned, with quote.
 3. Arithmetic audit (Python): line items re-added; mismatches vs the stated total are flagged.
 4. Leveling (Python): missing scope is "plugged" at the median price other bidders charged for it (or an
    estimator allowance); unpriced gaps are flagged rather than silently ignored.
 5. Award recommendation (Python ranks, LLM only phrases): every number in the narrative is checked
    against the computed facts; if the model invents one, the narrative is replaced by a template.
"""

from __future__ import annotations

import json
import re
import statistics
from typing import Any

from ..config import settings
from ..docs import Document, make_evidence, store
from ..grounding import grounded_narrative
from ..llm import chat_json, parallel_map
from ..schemas import AgentResult, Confidence, HumanReview
from .base import run_agent

STATUSES = ("included", "excluded", "qualified", "not_mentioned")

EXTRACT_SYS = """You are an experienced construction estimator leveling subcontractor/vendor bids. Read ONE bid and \
return its commercial content as JSON. Every "quote" must be copied verbatim from the bid text.
Map the bid against the SCOPE CHECKLIST: for each scope item give
- status: "included" (bid explicitly includes it, e.g. a priced line item or stated inclusion), "excluded" (bid says \
excluded / by others / not included / FOB factory for freight), "qualified" (included but with a condition that falls \
short of the requirement, e.g. shorter warranty than asked, partial scope), "not_mentioned" (bid is silent).
- price: the line-item price if the bid prices it separately, else null.
- quote: verbatim supporting text ("" if not_mentioned).
Return JSON:
{"bidder": str, "stated_total": number, "currency": str,
 "line_items": [{"description": str, "price": number, "quote": str}],
 "exclusions": [{"text": str, "quote": str}],
 "qualifications": [{"text": str, "quote": str, "risk": "high"|"medium"|"low"}],
 "warranty": {"text": str, "months": number|null, "quote": str},
 "validity_days": number|null, "lead_time_weeks": number|null, "lead_time_quote": str,
 "scope": [{"item": str (exactly as in checklist), "status": str, "price": number|null, "quote": str, "note": str}]}"""

SCOPE_SYS = """You define a scope checklist for leveling construction bids. Given the bids' line items and exclusions, \
return the union of distinct scope items a buyer must compare (8-15 items), phrased generically. \
Return JSON: {"scope": [str]}"""

MEMO_SYS = """You write a short award recommendation memo (<=170 words) for a procurement manager, using ONLY the facts \
in the JSON provided. Do not introduce any number that is not in the facts. Mention the recommended bidder, why \
(leveled total vs stated totals, key exclusions that were plugged), and the conditions to clear before award. \
Return JSON: {"memo": str}"""


def _extract(doc: Document, scope: list[str]) -> dict:
    return chat_json(
        EXTRACT_SYS,
        f"SCOPE CHECKLIST:\n{json.dumps(scope, indent=1)}\n\nBID DOCUMENT ({doc.name}):\n{doc.numbered_text()}",
        purpose="bids:extract",
        fallbacks=list(settings.fallback_models),
        max_tokens=8000,
    )


def derive_scope(docs: list[Document]) -> list[str]:
    text = "\n\n".join(f"### {d.name}\n{d.numbered_text(12000)}" for d in docs)
    out = chat_json(SCOPE_SYS, text, purpose="bids:scope", fallbacks=list(settings.fallback_models))
    return [s for s in out.get("scope", []) if isinstance(s, str)]


def _num(v: Any) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    m = re.search(r"-?\d[\d,]*\.?\d*", str(v))
    return float(m.group().replace(",", "")) if m else None


def level(bid_doc_ids: list[str], scope: list[str] | None = None, allowances: dict[str, float] | None = None, required_lead_weeks: float | None = None) -> AgentResult:
    docs = [store().get(i) for i in bid_doc_ids]
    if len(docs) < 2:
        raise ValueError("bid leveling needs at least two bids")
    scope = scope or derive_scope(docs)
    allowances = allowances or {}
    raw = parallel_map(lambda d: _extract(d, scope), docs)

    bids = []
    n_quotes = n_verified = 0
    for doc, b in zip(docs, raw):
        def ev(q, page=None):
            nonlocal n_quotes, n_verified
            if not q:
                return None
            e = make_evidence(doc, q, page)
            n_quotes += 1
            n_verified += int(e.verified)
            return e.model_dump()

        items = [{"description": li.get("description"), "price": _num(li.get("price")), "evidence": ev(li.get("quote"))} for li in b.get("line_items", [])]
        computed = round(sum(li["price"] or 0 for li in items), 2)
        stated = _num(b.get("stated_total"))
        arith = None
        if stated is not None and items and abs(computed - stated) > max(1.0, 0.0005 * stated):
            arith = {"stated_total": stated, "sum_of_line_items": computed, "difference": round(computed - stated, 2)}
        scope_map = {}
        for s in b.get("scope", []):
            name = s.get("item")
            if name not in scope:
                # tolerate small wording drift from the model
                match = next((x for x in scope if x.lower() == str(name).lower()), None)
                if not match:
                    continue
                name = match
            st = (s.get("status") or "not_mentioned").lower()
            scope_map[name] = {
                "status": st if st in STATUSES else "not_mentioned",
                "price": _num(s.get("price")),
                "note": s.get("note", ""),
                "evidence": ev(s.get("quote")),
            }
        for name in scope:
            scope_map.setdefault(name, {"status": "not_mentioned", "price": None, "note": "not returned by extractor", "evidence": None})
        bids.append(
            {
                "doc_id": doc.doc_id,
                "doc_name": doc.name,
                "bidder": b.get("bidder") or doc.name,
                "currency": b.get("currency") or "USD",
                "stated_total": stated,
                "line_items": items,
                "line_item_sum": computed,
                "arithmetic_error": arith,
                "exclusions": [{"text": x.get("text"), "evidence": ev(x.get("quote"))} for x in b.get("exclusions", [])],
                "qualifications": [{"text": x.get("text"), "risk": x.get("risk", "medium"), "evidence": ev(x.get("quote"))} for x in b.get("qualifications", [])],
                "warranty": {**(b.get("warranty") or {}), "evidence": ev((b.get("warranty") or {}).get("quote"))},
                "validity_days": _num(b.get("validity_days")),
                "lead_time_weeks": _num(b.get("lead_time_weeks")),
                "lead_time_evidence": ev(b.get("lead_time_quote")),
                "scope": scope_map,
            }
        )

    # ---------------------------------------------------------------- leveling (deterministic)
    for b in bids:
        base = b["line_item_sum"] if b["arithmetic_error"] else (b["stated_total"] or b["line_item_sum"])
        plugs, unpriced = [], []
        for item in scope:
            st = b["scope"][item]["status"]
            if st in ("excluded", "not_mentioned"):
                others = [o["scope"][item]["price"] for o in bids if o is not b and o["scope"][item]["status"] == "included" and o["scope"][item]["price"]]
                if others:
                    plugs.append({"item": item, "amount": round(statistics.median(others), 2), "basis": f"median of {len(others)} other bid(s) pricing this item", "status": st})
                elif item in allowances:
                    plugs.append({"item": item, "amount": float(allowances[item]), "basis": "estimator allowance", "status": st})
                else:
                    unpriced.append({"item": item, "status": st, "reason": "no other bidder priced it separately and no allowance given"})
            elif st == "qualified":
                if item in allowances:
                    plugs.append({"item": item, "amount": float(allowances[item]), "basis": "estimator allowance for qualified scope", "status": st})
                else:
                    unpriced.append({"item": item, "status": st, "reason": b["scope"][item].get("note") or "qualified scope - cost of closing the gap unknown"})
        b["leveling"] = {
            "base_used": base,
            "base_basis": "corrected sum of line items" if b["arithmetic_error"] else "stated total",
            "plugs": plugs,
            "plug_total": round(sum(p["amount"] for p in plugs), 2),
            "leveled_total": round(base + sum(p["amount"] for p in plugs), 2),
            "unpriced_gaps": unpriced,
        }
        risks = []
        if b["arithmetic_error"]:
            risks.append(f"arithmetic error: line items sum to {b['line_item_sum']:,.0f} vs stated {b['stated_total']:,.0f}")
        for q in b["qualifications"]:
            if q.get("risk") in ("high", "medium"):
                risks.append(f"qualification: {q['text']}")
        if required_lead_weeks and b["lead_time_weeks"] and b["lead_time_weeks"] > required_lead_weeks:
            risks.append(f"lead time {b['lead_time_weeks']:g} wks exceeds required {required_lead_weeks:g} wks")
        if b["validity_days"] and b["validity_days"] < 45:
            risks.append(f"short price validity ({b['validity_days']:g} days)")
        b["risks"] = risks

    ranked = sorted(bids, key=lambda b: b["leveling"]["leveled_total"])
    stated_rank = sorted(bids, key=lambda b: b["stated_total"] or 1e18)
    winner, runner = ranked[0], ranked[1]
    margin = (runner["leveling"]["leveled_total"] - winner["leveling"]["leveled_total"]) / winner["leveling"]["leveled_total"]

    matrix = [{"item": item, **{b["bidder"]: {k: b["scope"][item][k] for k in ("status", "price")} for b in bids}} for item in scope]
    facts = {
        "recommended": winner["bidder"],
        "leveled_totals": {b["bidder"]: b["leveling"]["leveled_total"] for b in ranked},
        "stated_totals": {b["bidder"]: b["stated_total"] for b in bids},
        "lowest_stated_bidder": stated_rank[0]["bidder"],
        "margin_to_second_pct": round(100 * margin, 1),
        "plugs": {b["bidder"]: [(p["item"], p["amount"]) for p in b["leveling"]["plugs"]] for b in bids},
        "unpriced_gaps": {b["bidder"]: [g["item"] for g in b["leveling"]["unpriced_gaps"]] for b in bids},
        "risks": {b["bidder"]: b["risks"] for b in bids},
        "lead_time_weeks": {b["bidder"]: b["lead_time_weeks"] for b in bids},
    }
    memo = _memo(facts)

    reasons = []
    if margin < 0.03:
        reasons.append(f"top two leveled bids are within {100 * margin:.1f}% - award is a judgement call")
    if winner["leveling"]["unpriced_gaps"]:
        reasons.append(f"recommended bidder has unpriced scope gaps: {', '.join(g['item'] for g in winner['leveling']['unpriced_gaps'])}")
    if winner["arithmetic_error"]:
        reasons.append("recommended bidder's bid has an arithmetic error - confirm price in writing")
    verify_rate = n_verified / max(1, n_quotes)
    if verify_rate < 0.9:
        reasons.append(f"only {100 * verify_rate:.0f}% of extracted quotes were found verbatim in the bids")

    factors = {
        "citation_verification": verify_rate,
        "award_margin": min(1.0, margin / 0.08),
        "scope_priced": 1 - len(winner["leveling"]["unpriced_gaps"]) / max(1, len(scope)),
    }
    score = 0.4 * factors["citation_verification"] + 0.35 * factors["award_margin"] + 0.25 * factors["scope_priced"]
    flip = stated_rank[0]["bidder"] != winner["bidder"]
    summary = (
        f"Recommend {winner['bidder']} at leveled {winner['leveling']['leveled_total']:,.0f} "
        f"({100 * margin:.1f}% below {runner['bidder']})."
        + (f" Lowest stated bid ({stated_rank[0]['bidder']}, {stated_rank[0]['stated_total']:,.0f}) is not lowest once scope gaps are plugged." if flip else "")
    )
    return AgentResult(
        agent="bid_leveling",
        summary=summary,
        result={
            "scope": scope,
            "recommendation": {"bidder": winner["bidder"], "doc_id": winner["doc_id"], "leveled_total": winner["leveling"]["leveled_total"], "margin_to_second_pct": facts["margin_to_second_pct"], "ranking_changed_by_leveling": flip, "memo": memo},
            "ranking": [{"rank": i + 1, "bidder": b["bidder"], "stated_total": b["stated_total"], "leveled_total": b["leveling"]["leveled_total"], "plug_total": b["leveling"]["plug_total"], "lead_time_weeks": b["lead_time_weeks"], "risks": b["risks"]} for i, b in enumerate(ranked)],
            "scope_matrix": matrix,
            "bids": bids,
            "citation_verification_rate": round(verify_rate, 3),
        },
        confidence=Confidence.from_score(score, factors, "weighted: citations 40%, award margin 35%, scope priced 25%"),
        human_review=HumanReview(required=bool(reasons), reasons=reasons),
    )


def _memo(facts: dict) -> dict:
    lt = facts["leveled_totals"]
    tmpl = (
        f"Recommend {facts['recommended']} at a leveled total of {lt[facts['recommended']]:,.0f}, "
        f"{facts['margin_to_second_pct']}% below the next bidder. Leveled totals: "
        + "; ".join(f"{k} {v:,.0f}" for k, v in lt.items())
        + ". Clear before award: "
        + ("; ".join(facts["risks"][facts["recommended"]]) or "no open risks")
        + "."
    )
    return grounded_narrative(MEMO_SYS, facts, tmpl, purpose="bids:memo", key="memo")


def level_bids(bid_doc_ids: list[str], scope: list[str] | None = None, allowances: dict[str, float] | None = None, required_lead_weeks: float | None = None) -> AgentResult:
    return run_agent(
        "bid_leveling",
        {"bid_doc_ids": bid_doc_ids, "scope": scope, "allowances": allowances, "required_lead_weeks": required_lead_weeks},
        lambda: level(bid_doc_ids, scope, allowances, required_lead_weeks),
    )
