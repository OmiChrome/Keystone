"""Accuracy evaluation against hand-labelled ground truth.

  dev      = Project Alpha (switchgear) - used while developing prompts
  heldout  = Project Beta (chillers)    - never looked at while writing prompts; tests generalisation

Writes eval/results.json and eval/REPORT.md.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from . import service
from .config import ROOT

SPLITS = {"dev": "project_alpha", "heldout": "project_beta"}
PRIORITY = {"deviate": 3, "missing": 2, "unclear": 1, "comply": 0}


def _ref(s: str) -> str:
    s = str(s).upper().replace(" ", "").rstrip(".")
    s = re.sub(r"\.+", ".", s)
    return s


def eval_compliance(project: str) -> dict:
    smp = service.load_sample(project)
    truth = json.loads((service.SAMPLES / project / "ground_truth.json").read_text())["compliance"]
    docs = smp["docs"]
    r = service.check_compliance(docs[truth["spec"]]["doc_id"], docs[truth["submittal"]]["doc_id"])
    if r.status == "error":
        return {"error": r.summary}
    by_ref: dict[str, list[dict]] = {}
    for f in r.result["findings"]:
        by_ref.setdefault(_ref(f["ref"]), []).append(f)
    rows, correct, tp, fp, fn = [], 0, 0, 0, 0
    auto_total = auto_correct = 0
    buckets: dict[str, list[int]] = {"high": [], "medium": [], "low": []}
    for label_key, expected in truth["labels"].items():
        ref = _ref(label_key.split(" ")[0])
        fs = by_ref.get(ref, [])
        if not fs:
            rows.append({"ref": ref, "label": label_key, "expected": expected, "got": "NOT EXTRACTED", "correct": False})
            fn += expected in ("deviate", "missing")
            continue
        got = max((f["verdict"] for f in fs), key=lambda v: PRIORITY.get(v, 0))
        f0 = next(f for f in fs if f["verdict"] == got)
        ok = got == expected or (expected == "missing" and got == "unclear")  # unclear on a missing item is a safe escalation
        exact = got == expected
        correct += exact
        is_issue, flagged = expected in ("deviate", "missing"), got in ("deviate", "missing", "unclear")
        tp += is_issue and flagged
        fn += is_issue and not flagged
        fp += (not is_issue) and got in ("deviate", "missing")
        if not f0["needs_human"]:
            auto_total += 1
            auto_correct += exact
        buckets[f0["confidence"]["level"]].append(int(exact))
        rows.append({"ref": ref, "label": label_key, "expected": expected, "got": got, "correct": exact, "safe": ok, "confidence": f0["confidence"]["score"], "needs_human": f0["needs_human"]})
    n = len(truth["labels"])
    return {
        "project": project,
        "n_labels": n,
        "n_findings": len(r.result["findings"]),
        "exact_accuracy": round(correct / n, 3),
        "issue_recall": round(tp / max(1, tp + fn), 3),
        "false_issue_rate": round(fp / max(1, n - sum(1 for v in truth["labels"].values() if v in ("deviate", "missing"))), 3),
        "escalation_rate": round(sum(1 for x in rows if x.get("needs_human")) / n, 3),
        "auto_decided_accuracy": round(auto_correct / max(1, auto_total), 3),
        "auto_decided_n": auto_total,
        "accuracy_by_confidence": {k: {"n": len(v), "accuracy": round(sum(v) / len(v), 3) if v else None} for k, v in buckets.items()},
        "citation_verification_rate": r.result["citation_verification_rate"],
        "usage": r.usage.model_dump(),
        "rows": rows,
        "run_id": r.run_id,
    }


def eval_bids(project: str) -> dict:
    smp = service.load_sample(project)
    truth = json.loads((service.SAMPLES / project / "ground_truth.json").read_text())["bids"]
    ids = [v["doc_id"] for k, v in smp["docs"].items() if k.startswith("bid")]
    r = service.level_bids(ids, truth["scope"])
    if r.status == "error":
        return {"error": r.summary}
    total = correct = 0
    errors = []
    for b in r.result["bids"]:
        key = next((k for k in truth["status"] if k.lower() in b["bidder"].lower()), None)
        if key is None:
            continue
        for item in truth["scope"]:
            exp = truth["status"][key].get(item, "included")
            got = b["scope"][item]["status"]
            # "excluded" vs "not_mentioned" both mean "not in price" - count as equivalent for leveling purposes
            ok = got == exp or {got, exp} == {"excluded", "not_mentioned"}
            total += 1
            correct += ok
            if not ok:
                errors.append({"bidder": key, "item": item, "expected": exp, "got": got})
    arith_truth = set(truth.get("arithmetic_errors", {}))
    arith_found = {k for b in r.result["bids"] if b["arithmetic_error"] for k in truth["status"] if k.lower() in b["bidder"].lower()}
    return {
        "project": project,
        "scope_status_accuracy": round(correct / max(1, total), 3),
        "n_cells": total,
        "arithmetic_errors_expected": sorted(arith_truth),
        "arithmetic_errors_found": sorted(arith_found),
        "arithmetic_detection_correct": arith_truth == arith_found,
        "recommendation": r.result["recommendation"]["bidder"],
        "citation_verification_rate": r.result["citation_verification_rate"],
        "mismatches": errors,
        "usage": r.usage.model_dump(),
        "run_id": r.run_id,
    }


def main(split: str = "all") -> None:
    projects = SPLITS.items() if split == "all" else [(split, SPLITS[split])]
    out = {}
    for name, proj in projects:
        out[name] = {"compliance": eval_compliance(proj), "bids": eval_bids(proj)}
    from .agents.leadtime import promise_model

    out["lead_time_calibration"] = promise_model()["calibration_test"]
    d = ROOT / "eval"
    d.mkdir(exist_ok=True)
    (d / "results.json").write_text(json.dumps(out, indent=1))
    lines = ["# Keystone evaluation report", "", "| split | agent | metric | value |", "|---|---|---|---|"]
    for name in (n for n, _ in projects):
        c, b = out[name]["compliance"], out[name]["bids"]
        for k in ("exact_accuracy", "issue_recall", "false_issue_rate", "escalation_rate", "auto_decided_accuracy", "citation_verification_rate"):
            lines.append(f"| {name} | spec_compliance | {k} | {c.get(k)} |")
        lines.append(f"| {name} | spec_compliance | cost_usd / wall_s | {c.get('usage', {}).get('cost_usd')} / {c.get('usage', {}).get('wall_time_s')} |")
        for k in ("scope_status_accuracy", "arithmetic_detection_correct", "recommendation", "citation_verification_rate"):
            lines.append(f"| {name} | bid_leveling | {k} | {b.get(k)} |")
        lines.append(f"| {name} | bid_leveling | cost_usd / wall_s | {b.get('usage', {}).get('cost_usd')} / {b.get('usage', {}).get('wall_time_s')} |")
    (d / "REPORT.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
