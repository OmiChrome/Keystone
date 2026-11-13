"""Spec & submittal compliance specialist.

Pipeline (neuro-symbolic, multi-model):
 1. Requirement extraction  - LLM turns the spec into atomic, testable requirements, each with a
                              verbatim quote, page, and (when numeric) comparator/value/unit.
 2. Evidence-grounded review - LLM judges each requirement against the submittal, citing a verbatim
                              submittal quote and the offered value.
 3. Citation verification   - every quote is located in the real PDF text (exact, then fuzzy); unverifiable
                              quotes cannot support a verdict.
 4. Symbolic rule check     - numeric requirements are re-decided in Python with unit conversion
                              (mm->in, kW->tons, kg->lb, degC->degF ...).
 5. Cross-model verification - a second model family independently re-judges every finding.
 6. Calibrated confidence   - agreement between evidence, rules and models -> score; conflicts or weak
                              evidence go to a human instead of being guessed.
"""

from __future__ import annotations

import json
from typing import Any

from ..config import settings
from ..docs import BM25, Document, make_evidence, passages, store
from ..llm import chat_json, parallel_map
from ..schemas import AgentResult, Confidence, HumanReview
from ..units import compare
from .base import run_agent

VERDICTS = ("comply", "deviate", "missing", "unclear")

EXTRACT_SYS = """You are a senior construction specifications engineer. You read a CSI-format specification section and \
extract every atomic, verifiable requirement that a vendor submittal must satisfy (ratings, materials, construction, \
listings/standards, dimensions, performance, accessories, testing, warranty, delivery, startup).
Rules:
- One requirement per distinct testable property. Split compound sentences only when they contain independent properties \
that a vendor could satisfy separately (e.g. "Modbus TCP and BACnet/IP" stays ONE requirement because both are needed).
- Skip pure administrative text (section titles, 'Section includes', references to other sections, submittal lists).
- "quote" MUST be copied verbatim from the spec text (exact characters, no paraphrase), long enough to be unique.
- "ref" is the paragraph number as written (e.g. "2.2.C" or "1.5.A"); if a paragraph has letters A, B... compose them.
- For numeric requirements fill comparator (">=", "<=", "==", "range"), value, unit (as written, e.g. "kA", "in", \
"tons", "kW/ton", "dBA", "deg F", "months", "weeks"). For qualitative ones comparator="text" and value=null.
- criticality: "critical" (safety, ratings, code/listing, fit), "major" (performance, materials, warranty, schedule), \
"minor" (finish, documentation).
Return JSON: {"requirements": [{"ref": str, "title": str (<=8 words), "requirement": str (plain restatement), \
"quote": str, "page": int, "parameter": str, "comparator": str, "value": number|null, "value_max": number|null, \
"unit": str|null, "criticality": str}]}"""

REVIEW_SYS = """You are a meticulous submittal reviewer for a general contractor. For each specification requirement, \
decide whether the vendor SUBMITTAL complies, using ONLY the submittal text provided.
Verdicts:
- "comply": the submittal explicitly states something that satisfies the requirement.
- "deviate": the submittal states something that does NOT satisfy it (lower rating, different material, option \
not included, shorter warranty, longer delivery, different units that convert to a non-compliant value...).
- "missing": the submittal does not address the requirement at all.
- "unclear": addressed but ambiguous / cannot be determined (e.g. measured under different conditions).
Rules:
- "submittal_quote" MUST be verbatim text copied from the submittal (exact characters), or "" when missing.
- "offered_value"/"offered_unit": the number and unit the submittal offers for numeric requirements (as written, do \
NOT convert units yourself), else null.
- Convert units mentally only for your verdict reasoning, and show the conversion in "reasoning".
- Optional items "available as an option" or "not included" do NOT comply.
- "certainty": your probability (0-1) that the verdict is right.
Return JSON: {"findings": [{"ref": str, "verdict": str, "submittal_quote": str, "page": int|null, \
"offered_value": number|null, "offered_unit": str|null, "offered_text": str, "reasoning": str, "certainty": number}]}"""

VERIFY_SYS = """You are an independent second reviewer auditing another reviewer's spec-compliance findings. For each \
finding you get the spec requirement, the first reviewer's verdict and the relevant submittal passages. Decide the \
correct verdict yourself ("comply", "deviate", "missing", "unclear") using only the submittal passages. Be strict: \
options not included do not comply; values must meet the requirement after unit conversion.
Return JSON: {"checks": [{"ref": str, "verdict": str, "note": str (<=25 words)}]}"""


def _chunks(seq: list, n: int) -> list[list]:
    return [seq[i : i + n] for i in range(0, len(seq), n)]


def extract_requirements(spec: Document) -> list[dict[str, Any]]:
    groups = _chunks(list(range(len(spec.pages))), 6)

    def one(pages_idx: list[int]) -> list[dict]:
        text = "\n".join(f"<<PAGE {i + 1}>>\n{spec.pages[i]}" for i in pages_idx)
        out = chat_json(EXTRACT_SYS, f"SPECIFICATION ({spec.name}):\n{text}", purpose="compliance:extract", max_tokens=8000, fallbacks=list(settings.fallback_models))
        return out.get("requirements", [])

    reqs: list[dict] = []
    seen = set()
    for batch in parallel_map(one, groups):
        for r in batch:
            key = (r.get("ref"), (r.get("title") or "").lower())
            if key in seen:
                continue
            seen.add(key)
            reqs.append(r)
    for i, r in enumerate(reqs):
        r["req_id"] = f"R{i + 1:02d}"
    return reqs


def _submittal_context(sub: Document, reqs: list[dict], max_chars: int = 60000) -> str:
    full = sub.numbered_text()
    if len(full) <= max_chars:
        return full
    # long submittal: retrieve the most relevant passages per requirement (BM25)
    ps = passages(sub)
    bm = BM25([p.text for p in ps])
    picked: dict[int, None] = {}
    for r in reqs:
        for i in bm.top(f"{r.get('title', '')} {r.get('requirement', '')} {r.get('parameter', '')}", k=4):
            picked[i] = None
    return "\n\n".join(f"<<PAGE {ps[i].page}>>\n{ps[i].text}" for i in picked)


def review(reqs: list[dict], sub: Document) -> dict[str, dict]:
    def one(batch: list[dict]) -> list[dict]:
        ctx = _submittal_context(sub, batch)
        req_txt = json.dumps(
            [{k: r.get(k) for k in ("ref", "title", "requirement", "comparator", "value", "value_max", "unit")} for r in batch],
            indent=1,
        )
        out = chat_json(
            REVIEW_SYS,
            f"REQUIREMENTS:\n{req_txt}\n\nSUBMITTAL ({sub.name}):\n{ctx}",
            purpose="compliance:review",
            fallbacks=list(settings.fallback_models),
            max_tokens=8000,
            reasoning_effort="medium",
        )
        return out.get("findings", [])

    found: dict[str, dict] = {}
    for batch in parallel_map(one, _chunks(reqs, 6)):
        for f in batch:
            if f.get("ref"):
                found[str(f["ref"])] = f
    return found


def cross_verify(items: list[dict], sub: Document) -> dict[str, dict]:
    ps = passages(sub, window=5, stride=2)
    bm = BM25([p.text for p in ps]) if ps else None

    def one(batch: list[dict]) -> list[dict]:
        blocks = []
        for it in batch:
            r, f = it["req"], it["finding"]
            ctx = ""
            if bm:
                idx = bm.top(f"{r.get('title', '')} {r.get('requirement', '')} {r.get('parameter', '')} {f.get('submittal_quote', '')}", k=3)
                ctx = "\n---\n".join(f"[p{ps[i].page}] {ps[i].text}" for i in idx)
            blocks.append(
                {"ref": r["ref"], "requirement": r.get("requirement"), "first_verdict": f.get("verdict"), "first_quote": f.get("submittal_quote"), "submittal_passages": ctx}
            )
        try:
            out = chat_json(
                VERIFY_SYS,
                json.dumps(blocks, indent=1),
                model=settings.verifier_model,
                # independence: never fall back to the primary model that produced the finding
                fallbacks=[m for m in settings.fallback_models if m.split("-")[0] != settings.model.split("-")[0]],
                purpose="compliance:verify",
                max_tokens=6000,
            )
        except Exception as e:  # degrade gracefully: findings stay un-verified (and lose confidence)
            return [{"ref": b["ref"], "_error": str(e)[:200]} for b in blocks]
        return [c | {"_served_by": out.get("_served_by")} for c in out.get("checks", []) if isinstance(c, dict)]

    res: dict[str, dict] = {}
    for batch in parallel_map(one, _chunks(items, 8)):
        for c in batch:
            if c.get("ref"):
                res[str(c["ref"])] = c
    return res


def _score(factors: dict[str, float], weights: dict[str, float]) -> float:
    num = sum(weights[k] * v for k, v in factors.items() if k in weights)
    den = sum(weights[k] for k in factors if k in weights)
    return num / den if den else 0.0


WEIGHTS = {"spec_citation": 0.15, "submittal_citation": 0.25, "rule_check": 0.25, "cross_model": 0.25, "model_certainty": 0.10}


def assess(spec_doc_id: str, submittal_doc_id: str, verify: bool = True) -> AgentResult:
    spec, sub = store().get(spec_doc_id), store().get(submittal_doc_id)
    reqs = extract_requirements(spec)
    found = review(reqs, sub)

    items = []
    for r in reqs:
        f = found.get(str(r.get("ref"))) or {"verdict": "unclear", "submittal_quote": "", "reasoning": "reviewer returned no finding"}
        items.append({"req": r, "finding": f})
    checks = cross_verify(items, sub) if verify else {}

    findings = []
    for it in items:
        r, f = it["req"], it["finding"]
        verdict = (f.get("verdict") or "unclear").lower()
        if verdict not in VERDICTS:
            verdict = "unclear"
        spec_ev = make_evidence(spec, r.get("quote", ""), r.get("page"), locator=r.get("ref"))
        sub_ev = make_evidence(sub, f.get("submittal_quote", ""), f.get("page")) if f.get("submittal_quote") else None

        factors: dict[str, float] = {"spec_citation": 1.0 if spec_ev.verified else 0.0}
        reasons: list[str] = []
        if verdict in ("comply", "deviate"):
            factors["submittal_citation"] = 1.0 if (sub_ev and sub_ev.verified) else 0.0
            if not (sub_ev and sub_ev.verified):
                reasons.append("submittal quote could not be found in the document")

        rule = compare(r, {"value": f.get("offered_value"), "unit": f.get("offered_unit")})
        final = verdict
        if rule.status in ("comply", "deviate") and verdict in ("comply", "deviate"):
            if rule.status == verdict:
                factors["rule_check"] = 1.0
            else:
                factors["rule_check"] = 0.0
                reasons.append(f"rule check says {rule.status} ({rule.explanation}) but model said {verdict}")
                final = rule.status  # trust arithmetic over the model, but flag it
        chk = checks.get(str(r.get("ref")))
        verifier = None
        if chk and chk.get("_error"):
            verifier = {"model": settings.verifier_model, "verdict": None, "agrees": None, "note": "verifier unavailable: " + chk["_error"]}
            reasons.append("independent cross-model check unavailable for this finding")
            factors["cross_model"] = 0.5
        elif chk:
            v2 = (chk.get("verdict") or "").lower()
            agrees = v2 == final
            factors["cross_model"] = 1.0 if agrees else 0.0
            verifier = {"model": chk.get("_served_by") or settings.verifier_model, "verdict": v2, "agrees": agrees, "note": chk.get("note", "")}
            if not agrees:
                reasons.append(f"independent model judged '{v2}': {chk.get('note', '')}")
        try:
            factors["model_certainty"] = max(0.0, min(1.0, float(f.get("certainty", 0.5))))
        except (TypeError, ValueError):
            factors["model_certainty"] = 0.5

        score = _score(factors, WEIGHTS)
        if any(factors.get(k) == 0.0 for k in ("submittal_citation", "rule_check", "cross_model")):
            score = min(score, 0.55)
        if final == "unclear":
            score = min(score, 0.5)
            reasons.append("verdict could not be determined from the submittal")
        conf = Confidence.from_score(score, factors)
        needs_human = conf.score < 0.7 or final == "unclear"
        findings.append(
            {
                "req_id": r["req_id"],
                "ref": r.get("ref"),
                "title": r.get("title"),
                "requirement": r.get("requirement"),
                "criticality": r.get("criticality", "major"),
                "verdict": final,
                "model_verdict": verdict,
                "offered": {"value": f.get("offered_value"), "unit": f.get("offered_unit"), "text": f.get("offered_text", "")},
                "rule_check": {"status": rule.status, "explanation": rule.explanation},
                "reasoning": f.get("reasoning", ""),
                "evidence": {"spec": spec_ev.model_dump(), "submittal": sub_ev.model_dump() if sub_ev else None},
                "verifier": verifier,
                "confidence": conf.model_dump(),
                "needs_human": needs_human,
                "review_reasons": reasons,
            }
        )

    counts = {v: sum(1 for f in findings if f["verdict"] == v) for v in VERDICTS}
    crit_dev = [f for f in findings if f["verdict"] in ("deviate", "missing") and f["criticality"] == "critical"]
    if counts["deviate"] + counts["missing"] == 0 and counts["unclear"] == 0:
        action = "Approved"
    elif crit_dev:
        action = "Revise and Resubmit"
    elif counts["deviate"] + counts["missing"] <= 2:
        action = "Approved as Noted"
    else:
        action = "Revise and Resubmit"
    review_items = [f for f in findings if f["needs_human"]]
    overall = sum(f["confidence"]["score"] for f in findings) / max(1, len(findings))
    cited = sum(1 for f in findings if f["evidence"]["spec"]["verified"] and (f["evidence"]["submittal"] is None or f["evidence"]["submittal"]["verified"]))
    summary = (
        f"{len(findings)} requirements checked: {counts['comply']} comply, {counts['deviate']} deviate, "
        f"{counts['missing']} missing, {counts['unclear']} unclear. Recommended stamp: {action}. "
        f"{len(crit_dev)} critical issue(s); {len(review_items)} finding(s) routed to a human."
    )
    draft = _review_comments(spec, sub, findings, action)
    return AgentResult(
        agent="spec_compliance",
        summary=summary,
        result={
            "spec": spec.to_dict(),
            "submittal": sub.to_dict(),
            "recommended_action": action,
            "counts": counts,
            "critical_issues": [f["req_id"] for f in crit_dev],
            "citation_verification_rate": round(cited / max(1, len(findings)), 3),
            "review_comments": draft,
            "findings": findings,
        },
        confidence=Confidence.from_score(overall, {"mean_finding_confidence": overall}, "mean of per-finding confidence"),
        human_review=HumanReview(
            required=bool(review_items),
            reasons=[f"{f['ref']} {f['title']}: {'; '.join(f['review_reasons']) or 'low confidence'}" for f in review_items],
        ),
    )


def _review_comments(spec: Document, sub: Document, findings: list[dict], action: str) -> dict:
    """Reviewer comments + a draft email to the vendor, built ONLY from verified findings (no LLM, no new facts).
    Sending it is an outward action: it is returned as a draft for a person to approve."""
    issues = [f for f in findings if f["verdict"] in ("deviate", "missing")]
    lines = []
    for i, f in enumerate(issues, 1):
        offered = ""
        if f["verdict"] == "deviate" and f["evidence"]["submittal"]:
            offered = f' Submitted: "{f["evidence"]["submittal"]["quote"]}" (p{f["evidence"]["submittal"]["page"]}).'
        elif f["verdict"] == "missing":
            offered = " Not addressed in the submittal - provide documentation."
        lines.append(f'{i}. [{f["ref"]}] {f["requirement"]}{offered}')
    body = (
        f"Subject: {action} - {sub.name} vs {spec.name}\n\n"
        f"The submittal has been reviewed against {spec.name}. Status: {action}.\n"
        + (f"Please address the following {len(issues)} item(s) and resubmit:\n\n" + "\n".join(lines) if issues else "No exceptions taken.")
        + "\n\nItems not listed were found compliant. This review does not relieve the vendor of responsibility for compliance with the contract documents."
    )
    return {"stamp": action, "comments": lines, "draft_email": body, "requires_approval_to_send": True}


def check_compliance(spec_doc_id: str, submittal_doc_id: str, verify: bool = True) -> AgentResult:
    return run_agent(
        "spec_compliance",
        {"spec_doc_id": spec_doc_id, "submittal_doc_id": submittal_doc_id, "verify": verify},
        lambda: assess(spec_doc_id, submittal_doc_id, verify),
    )
