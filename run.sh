#!/usr/bin/env bash
# One command: install deps (uv + bun), build the UI, generate samples, start Keystone on :8000
set -euo pipefail
cd "$(dirname "$0")"
command -v uv >/dev/null || { echo "install uv: https://docs.astral.sh/uv/"; exit 1; }
command -v bun >/dev/null || { echo "install bun: https://bun.sh"; exit 1; }
[ -f .env ] || { cp .env.example .env; echo "Created .env - put your API key in KEYSTONE_LLM_API_KEY"; }
uv sync --quiet
(cd web && bun install --silent && bun run build >/dev/null)
uv run python samples/generate.py >/dev/null
echo "Keystone: http://127.0.0.1:${PORT:-8000}   MCP: http://127.0.0.1:${PORT:-8000}/mcp/"
exec uv run keystone serve --port "${PORT:-8000}"
