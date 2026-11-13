"""REST API + web UI host.

  uv run keystone serve          -> http://127.0.0.1:8000  (UI)  /api/*  (REST)  /mcp  (MCP over HTTP)

Long-running specialist calls run as background jobs; the UI polls /api/jobs/{id} and shows a live
log of every model call the agent makes.
"""

from __future__ import annotations

import contextlib
import contextvars
import json
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import service
from .config import ROOT, settings
from .llm import set_listener
from .schemas import SCHEMA_VERSION

WEB = ROOT / "web" / "dist"

app = FastAPI(title="Keystone", version="0.1.0", description="Procurement specialist agents for construction (keystone/1.0)")

# ------------------------------------------------------------------------------------------- jobs

_pool = ThreadPoolExecutor(max_workers=4)
_jobs: dict[str, dict[str, Any]] = {}
_lock = threading.Lock()


def submit(kind: str, fn: Callable[[], Any]) -> dict:
    jid = uuid.uuid4().hex[:10]
    events: list = []
    job = {"job_id": jid, "kind": kind, "status": "running", "started": time.time(), "events": events, "result": None, "error": None}
    with _lock:
        _jobs[jid] = job

    def work():
        set_listener(events)
        try:
            res = fn()
            job["result"] = res.model_dump() if hasattr(res, "model_dump") else res
            job["status"] = "done"
        except Exception as e:
            job["error"] = f"{type(e).__name__}: {e}"
            job["status"] = "error"
        job["finished"] = time.time()

    if settings.serverless:
        # No background threads on serverless, and the next poll may hit another instance:
        # run inline and hand back the finished job in the same response.
        contextvars.copy_context().run(work)
        return job_view(jid)
    _pool.submit(contextvars.copy_context().run, work)
    return {"job_id": jid, "status": "running"}


@app.get("/api/jobs/{jid}")
def job(jid: str, since: int = 0) -> dict:
    if jid not in _jobs:
        raise HTTPException(404, "unknown job")
    return job_view(jid, since)


def job_view(jid: str, since: int = 0) -> dict:
    j = _jobs[jid]
    return {
        "job_id": jid,
        "kind": j["kind"],
        "status": j["status"],
        "elapsed_s": round((j.get("finished") or time.time()) - j["started"], 1),
        "events": j["events"][since:],
        "n_events": len(j["events"]),
        "result": j["result"] if j["status"] == "done" else None,
        "error": j["error"],
    }


# ------------------------------------------------------------------------------------------ meta


@app.get("/api/health")
def health() -> dict:
    return {
        "ok": True,
        "schema_version": SCHEMA_VERSION,
        "model": settings.model,
        "verifier_model": settings.verifier_model,
        "fallback_models": list(settings.fallback_models),
        "base_url": settings.base_url,
        "rpm": settings.rpm,
        "cache": settings.cache,
        "api_key_configured": bool(settings.api_key),
        "serverless": settings.serverless,
    }


@app.get("/api/specialists")
def specialists() -> dict:
    return service.AGENTS


# ------------------------------------------------------------------------------------- documents


@app.post("/api/samples/{project}")
def load_sample(project: str) -> dict:
    try:
        return service.load_sample(project)
    except ValueError as e:
        raise HTTPException(404, str(e))


@app.get("/api/documents")
def documents() -> list[dict]:
    return service.store().list()


@app.post("/api/documents")
async def upload(file: UploadFile = File(...), kind: str = Form("document")) -> dict:
    data = await file.read()
    if file.filename and file.filename.lower().endswith(".csv"):
        return {"name": file.filename, "kind": kind, "csv": data.decode("utf-8", "replace")}
    return service.ingest_bytes(file.filename or "upload.pdf", data, kind)


@app.get("/api/documents/{doc_id}")
def document(doc_id: str, page: int | None = None) -> dict:
    try:
        return service.get_source(doc_id, page)
    except (KeyError, IndexError) as e:
        raise HTTPException(404, str(e))


@app.get("/api/documents/{doc_id}/file")
def document_file(doc_id: str):
    d = service.store().get(doc_id)
    if not d.source_path:
        raise HTTPException(404, "no file")
    return FileResponse(d.source_path, filename=d.name)


# ------------------------------------------------------------------------------------- specialists


class ComplianceIn(BaseModel):
    spec_doc_id: str
    submittal_doc_id: str
    verify: bool = True


class BidsIn(BaseModel):
    bid_doc_ids: list[str]
    scope: list[str] | None = None
    allowances: dict[str, float] | None = None
    required_lead_weeks: float | None = None


class LeadIn(BaseModel):
    items: list[dict]


class ScheduleIn(BaseModel):
    schedule_csv: str
    po_csv: str
    project_start: str
    target_completion: str | None = None
    receiving_buffer_days: int = 5


class PipelineIn(BaseModel):
    bid_doc_ids: list[str]
    spec_doc_id: str
    submittal_doc_id: str
    schedule_csv: str
    po_csv: str
    package_po: str
    project_start: str
    target_completion: str | None = None
    scope: list[str] | None = None


@app.post("/api/compliance")
def compliance(b: ComplianceIn) -> dict:
    return submit("spec_compliance", lambda: service.check_compliance(b.spec_doc_id, b.submittal_doc_id, b.verify))


@app.post("/api/bids")
def bids(b: BidsIn) -> dict:
    return submit("bid_leveling", lambda: service.level_bids(b.bid_doc_ids, b.scope, b.allowances, b.required_lead_weeks))


@app.post("/api/leadtime")
def leadtime(b: LeadIn) -> dict:
    return submit("lead_time", lambda: service.predict_lead_times(b.items))


@app.post("/api/schedule")
def schedule(b: ScheduleIn) -> dict:
    return submit("schedule_risk", lambda: service.assess_schedule_risk(b.schedule_csv, b.po_csv, b.project_start, b.target_completion, b.receiving_buffer_days))


@app.post("/api/pipeline")
def pipeline(b: PipelineIn) -> dict:
    return submit("package_pipeline", lambda: service.run_package_pipeline(**b.model_dump()))


@app.get("/api/runs")
def runs(limit: int = 30) -> list[dict]:
    d = settings.runs_dir / "results"
    if not d.exists():
        return []
    files = sorted(d.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]
    out = []
    for f in files:
        try:
            r = json.loads(f.read_text())
        except Exception:
            continue
        out.append({k: r.get(k) for k in ("run_id", "agent", "created_at", "status", "summary")} | {"confidence": (r.get("confidence") or {}).get("score"), "usage": r.get("usage")})
    return out


@app.get("/api/runs/{run_id}")
def run(run_id: str) -> dict:
    p = settings.runs_dir / "results" / f"{run_id}.json"
    if not p.exists():
        raise HTTPException(404, "unknown run")
    return json.loads(p.read_text())


# ------------------------------------------------------------------------------------- MCP + UI

try:
    from .mcp_server import mcp as _mcp

    # stateless + JSON responses on serverless: any instance can answer any MCP request
    _mcp_app = _mcp.streamable_http_app(streamable_http_path="/", host="127.0.0.1", stateless_http=settings.serverless, json_response=settings.serverless)
    app.mount("/mcp", _mcp_app)
except Exception as _e:  # pragma: no cover - MCP over HTTP is optional
    _mcp_app = None
    print("MCP HTTP mount disabled:", _e)


@contextlib.asynccontextmanager
async def _lifespan(_app):
    async with contextlib.AsyncExitStack() as stack:
        if _mcp_app is not None:  # the MCP session manager needs its lifespan running
            await stack.enter_async_context(_mcp_app.router.lifespan_context(_mcp_app))
        yield


app.router.lifespan_context = _lifespan

# UI: mounted last so every /api and /mcp route wins; on Vercel this directory is promoted to the CDN.
if WEB.exists():
    app.mount("/", StaticFiles(directory=WEB, html=True), name="ui")
else:

    @app.get("/")
    def no_ui() -> JSONResponse:
        return JSONResponse({"detail": "UI not built - run `cd web && bun install && bun run build`", "api": "/api/health", "mcp": "/mcp/"})
