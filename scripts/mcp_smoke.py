"""MCP smoke test: connect like Amber would (stdio or HTTP), list tools, call specialists.

  uv run python scripts/mcp_smoke.py            # stdio (spawns keystone-mcp)
  uv run python scripts/mcp_smoke.py --http http://127.0.0.1:8000/mcp/
"""

import argparse
import asyncio
import json

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamable_http_client


async def exercise(session: ClientSession) -> None:
    await session.initialize()
    tools = await session.list_tools()
    print("tools:", [t.name for t in tools.tools])
    r = await session.call_tool("load_sample_project", {"project": "project_alpha"})
    sample = r.structured_content or json.loads(r.content[0].text)
    sample = sample.get("result", sample)
    print("sample docs:", list(sample["docs"]))
    r = await session.call_tool(
        "assess_schedule_risk",
        {"schedule_csv": sample["schedule_csv"], "po_csv": sample["purchase_orders_csv"], "project_start": "2026-12-01", "target_completion": "2028-01-31"},
    )
    res = r.structured_content or json.loads(r.content[0].text)
    res = res.get("result", res) if "agent" not in res else res
    print("schedule_risk:", res["status"], "|", res["summary"][:160])
    r = await session.call_tool("predict_lead_time", {"items": [{"item_id": "T1", "description": "2500 kVA pad-mounted transformer", "quoted_lead_weeks": 50, "order_date": "2026-12-01"}]})
    res = r.structured_content or json.loads(r.content[0].text)
    res = res.get("result", res) if "agent" not in res else res
    print("lead_time:", res["summary"])


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--http")
    a = ap.parse_args()
    if a.http:
        async with streamable_http_client(a.http) as streams:
            async with ClientSession(streams[0], streams[1]) as s:
                await exercise(s)
    else:
        params = StdioServerParameters(command="uv", args=["run", "keystone-mcp"])
        async with stdio_client(params) as (rd, wr):
            async with ClientSession(rd, wr) as s:
                await exercise(s)


if __name__ == "__main__":
    asyncio.run(main())
