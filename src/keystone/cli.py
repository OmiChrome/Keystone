"""keystone CLI.

  keystone serve [--port 8000]                    web UI + REST + MCP(HTTP)
  keystone mcp                                    MCP over stdio
  keystone demo [project_alpha|project_beta]      run the whole package pipeline on a sample, print JSON
  keystone eval [--split all|dev|heldout]         accuracy evaluation against hand-labelled ground truth
"""

from __future__ import annotations

import argparse
import json
import sys


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="keystone")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    sub.add_parser("mcp")
    d = sub.add_parser("demo")
    d.add_argument("project", nargs="?", default="project_alpha")
    e = sub.add_parser("eval")
    e.add_argument("--split", default="all", choices=["all", "dev", "heldout"])
    a = ap.parse_args(argv)

    if a.cmd == "serve":
        import uvicorn

        uvicorn.run("keystone.api:app", host=a.host, port=a.port)
    elif a.cmd == "mcp":
        sys.argv = ["keystone-mcp"]
        from .mcp_server import main as mcp_main

        mcp_main()
    elif a.cmd == "demo":
        from . import service

        smp = service.load_sample(a.project)
        docs = smp["docs"]
        pick = lambda pre: [v["doc_id"] for k, v in docs.items() if k.startswith(pre)]  # noqa: E731
        proj = smp.get("project_info", {})
        res = service.run_package_pipeline(
            bid_doc_ids=pick("bid"),
            spec_doc_id=pick("spec")[0],
            submittal_doc_id=pick("submittal")[0],
            schedule_csv=smp["schedule_csv"],
            po_csv=smp["purchase_orders_csv"],
            package_po="PO-1001",
            project_start=proj.get("start_date", "2026-12-01"),
            target_completion=proj.get("target_completion"),
            scope=smp.get("scope_checklist"),
        )
        out = res.model_dump()
        out["result"].pop("steps", None)
        print(json.dumps(out, indent=1))
    elif a.cmd == "eval":
        from .evaluate import main as eval_main

        eval_main(a.split)


if __name__ == "__main__":
    main()
