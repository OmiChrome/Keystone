"""Keystone MCP server - lets Amber (or any MCP client) call each specialist directly.

  stdio:            uv run keystone-mcp
  streamable HTTP:  uv run keystone-mcp --http --port 8765     (endpoint /mcp)

Every tool returns the shared keystone/1.0 AgentResult envelope as structured JSON.
"""

from __future__ import annotations

import argparse
import asyncio
from typing import Any

import anyio
from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from . import service
from .agents.base import load_run
from .schemas import SCHEMA_VERSION

mcp = MCPServer(
    name="keystone",
    title="Keystone procurement specialists",
    version="0.1.0",
    instructions=(
        "Specialist procurement agents for construction / data-center projects. Ingest documents first "
        "(ingest_document or load_sample_project) to obtain doc_ids, then call a specialist. Every result uses the "
        f"{SCHEMA_VERSION} envelope: status, summary, result, confidence{{score,level,factors}}, "
        "human_review{required,reasons}, usage{models,llm_calls,cost_usd,wall_time_s}. Findings cite evidence "
        "(doc_id, page/locator, verbatim quote, verified flag). If human_review.required is true, do not act "
        "without a person's sign-off."
    ),
)

READ_ONLY = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False)


async def _run(fn, *a, **kw) -> Any:
    return await anyio.to_thread.run_sync(lambda: fn(*a, **kw))


@mcp.tool(annotations=READ_ONLY)
def list_specialists() -> dict:
    """List the specialists in this suite with their inputs and outputs."""
    return {"schema_version": SCHEMA_VERSION, "specialists": service.AGENTS}


@mcp.tool()
async def ingest_document(path: str | None = None, content_base64: str | None = None, filename: str | None = None, kind: str = "document") -> dict:
    """Ingest a PDF/TXT/CSV (by local path, or base64 content + filename). kind: spec | submittal | bid | document.
    Returns {doc_id, name, n_pages}."""
    if path:
        return await _run(service.ingest_file, path, kind)
    if content_base64 and filename:
        return await _run(service.ingest_base64, filename, content_base64, kind)
    raise ValueError("give either path or content_base64 + filename")


@mcp.tool()
async def load_sample_project(project: str = "project_alpha") -> dict:
    """Ingest a bundled sample project ('project_alpha' switchgear, 'project_beta' chillers) and return doc ids and CSVs."""
    return await _run(service.load_sample, project)


@mcp.tool(annotations=READ_ONLY)
def get_source(doc_id: str, page: int | None = None) -> dict:
    """Return the text of a source document page, to inspect any citation."""
    return service.get_source(doc_id, page)


@mcp.tool(annotations=READ_ONLY)
async def check_spec_compliance(spec_doc_id: str, submittal_doc_id: str, verify: bool = True) -> dict:
    """Check a submittal against a spec section line by line (comply / deviate / missing / unclear) with citations
    to both documents, unit-converted rule checks, cross-model verification and per-finding confidence."""
    return (await _run(service.check_compliance, spec_doc_id, submittal_doc_id, verify)).model_dump()


@mcp.tool(annotations=READ_ONLY)
async def level_bids(bid_doc_ids: list[str], scope: list[str] | None = None, allowances: dict[str, float] | None = None, required_lead_weeks: float | None = None) -> dict:
    """Level two or more bids on a common scope; returns scope matrix, exclusions, arithmetic audit, plug-priced
    leveled totals and an award recommendation with a number-grounded memo."""
    return (await _run(service.level_bids, bid_doc_ids, scope, allowances, required_lead_weeks)).model_dump()


@mcp.tool(annotations=READ_ONLY)
async def predict_lead_time(items: list[dict]) -> dict:
    """Forecast P10/P50/P80/P90 lead time (weeks) and arrival dates. Each item: {item_id, description,
    quoted_lead_weeks?, order_date?, need_by_date?, promised_date?, shipment_mode?, vendor?, category?}."""
    return (await _run(service.predict_lead_times, items)).model_dump()


@mcp.tool(annotations=READ_ONLY)
async def assess_schedule_risk(schedule_csv: str, po_csv: str, project_start: str, target_completion: str | None = None, receiving_buffer_days: int = 5) -> dict:
    """Rank late-equipment risks by the project delay they actually cause. schedule_csv columns: activity_id,
    name, duration_days, predecessors (;-separated), requires_po. po_csv columns: po_number, item, vendor,
    order_date, quoted_lead_weeks, promised_date, shipment_mode, status."""
    return (await _run(service.assess_schedule_risk, schedule_csv, po_csv, project_start, target_completion, receiving_buffer_days)).model_dump()


@mcp.tool(annotations=READ_ONLY)
async def run_package_pipeline(
    bid_doc_ids: list[str],
    spec_doc_id: str,
    submittal_doc_id: str,
    schedule_csv: str,
    po_csv: str,
    package_po: str,
    project_start: str,
    target_completion: str | None = None,
    scope: list[str] | None = None,
) -> dict:
    """Bid leveling -> submittal compliance -> schedule impact for one package, returning an award decision with
    conditions and a full hand-off trail. Never places an order; award always requires human sign-off."""
    kw = dict(bid_doc_ids=bid_doc_ids, spec_doc_id=spec_doc_id, submittal_doc_id=submittal_doc_id, schedule_csv=schedule_csv, po_csv=po_csv, package_po=package_po, project_start=project_start, target_completion=target_completion, scope=scope)
    return (await _run(lambda: service.run_package_pipeline(**kw))).model_dump()


@mcp.tool(annotations=READ_ONLY)
def get_run(run_id: str) -> dict:
    """Fetch a previous result (audit log) by run_id."""
    return load_run(run_id)


def main() -> None:
    ap = argparse.ArgumentParser(description="Keystone MCP server")
    ap.add_argument("--http", action="store_true", help="serve streamable HTTP instead of stdio")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args()
    if a.http:
        import uvicorn

        uvicorn.run(mcp.streamable_http_app(host=a.host), host=a.host, port=a.port)
    else:
        asyncio.run(mcp.run_stdio_async())


if __name__ == "__main__":
    main()
