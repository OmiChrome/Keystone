"""Thin facade used by both the MCP server and the REST API, so the two can never drift apart."""

from __future__ import annotations

import base64
import tempfile
from pathlib import Path
from typing import Any

from .agents.bids import level_bids
from .agents.compliance import check_compliance
from .agents.leadtime import predict_lead_times
from .agents.pipeline import run_package_pipeline
from .agents.schedule import assess_schedule_risk
from .config import ROOT
from .docs import store

SAMPLES = ROOT / "samples"

AGENTS = {
    "spec_compliance": {
        "description": "Check a vendor submittal against a specification, line by line: comply / deviate / missing / unclear, citing both documents, with a symbolic unit-converted rule check and an independent second-model review.",
        "input": {"spec_doc_id": "str", "submittal_doc_id": "str"},
        "output": "AgentResult.result.findings[] with verdict, evidence.spec, evidence.submittal, rule_check, verifier, confidence",
    },
    "bid_leveling": {
        "description": "Level 2+ bids on a common scope: scope matrix, exclusions, arithmetic audit, plug pricing, leveled totals and an award recommendation.",
        "input": {"bid_doc_ids": "list[str]", "scope": "list[str] | None", "allowances": "dict[str, float] | None"},
        "output": "AgentResult.result.recommendation, ranking[], scope_matrix[], bids[]",
    },
    "lead_time": {
        "description": "Forecast P10/P50/P90 lead times and arrival dates for equipment, from cited market reference classes and empirical supplier-promise reliability.",
        "input": {"items": "list[EquipmentItem]"},
        "output": "AgentResult.result.forecasts[]",
    },
    "schedule_risk": {
        "description": "Rank late-equipment risks by the project delay they actually cause (CPM + Monte Carlo + counterfactual attribution) and suggest actions.",
        "input": {"schedule_csv": "str", "po_csv": "str", "project_start": "YYYY-MM-DD", "target_completion": "YYYY-MM-DD | None"},
        "output": "AgentResult.result.risks[], simulation, cpm[]",
    },
    "package_pipeline": {
        "description": "Chain bid leveling -> submittal compliance -> schedule risk into one package award decision.",
        "input": "see run_package_pipeline",
        "output": "AgentResult.result.decision, conditions[], trail[], steps{}",
    },
}


def ingest_file(path: str, kind: str = "document") -> dict:
    return store().ingest_path(path, kind).to_dict()


def ingest_bytes(name: str, data: bytes, kind: str = "document") -> dict:
    suffix = Path(name).suffix or ".txt"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        f.write(data)
        p = f.name
    return store().ingest_path(p, kind, name=name).to_dict()


def ingest_base64(name: str, b64: str, kind: str = "document") -> dict:
    return ingest_bytes(name, base64.b64decode(b64), kind)


def get_source(doc_id: str, page: int | None = None) -> dict:
    d = store().get(doc_id)
    if page:
        return {"doc_id": doc_id, "name": d.name, "page": page, "n_pages": d.n_pages, "text": d.pages[page - 1]}
    return {"doc_id": doc_id, "name": d.name, "n_pages": d.n_pages, "pages": d.pages}


def load_sample(project: str = "project_alpha") -> dict[str, Any]:
    """Ingest a bundled sample project and return its doc ids + CSVs."""
    root = SAMPLES / project
    if not root.exists():
        raise ValueError(f"unknown sample project {project!r}")
    out: dict[str, Any] = {"project": project, "docs": {}}
    for p in sorted(root.glob("*.pdf")):
        kind = "spec" if p.name.startswith("spec") else "submittal" if p.name.startswith("submittal") else "bid" if p.name.startswith("bid") else "document"
        out["docs"][p.name] = store().ingest_path(p, kind).to_dict()
    for name in ("schedule.csv", "purchase_orders.csv"):
        if (root / name).exists():
            out[name.replace(".csv", "_csv")] = (root / name).read_text()
    for name in ("project.json", "scope_checklist.json"):
        if (root / name).exists():
            import json

            out["project_info" if name == "project.json" else name.replace(".json", "")] = json.loads((root / name).read_text())
    return out


__all__ = [
    "AGENTS",
    "assess_schedule_risk",
    "check_compliance",
    "get_source",
    "ingest_base64",
    "ingest_bytes",
    "ingest_file",
    "level_bids",
    "load_sample",
    "predict_lead_times",
    "run_package_pipeline",
    "store",
]
