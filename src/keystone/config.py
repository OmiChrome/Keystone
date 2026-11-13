"""Runtime configuration, read from environment variables (and an optional .env file)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

def _root() -> Path:
    """Project root (samples/, demo_cache/, web/dist). Works from a checkout or when installed as a package
    (e.g. on Vercel, where the working directory is the project root)."""
    if os.environ.get("KEYSTONE_ROOT"):
        return Path(os.environ["KEYSTONE_ROOT"])
    src_root = Path(__file__).resolve().parents[2]
    if (src_root / "samples").exists():
        return src_root
    return Path.cwd()


ROOT = _root()
# Serverless (Vercel): read-only filesystem except /tmp, and no long-lived background threads.
SERVERLESS = bool(os.environ.get("VERCEL") or os.environ.get("KEYSTONE_SERVERLESS"))
_WRITABLE = Path("/tmp/keystone") if SERVERLESS else ROOT


def _load_dotenv() -> None:
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv()


@dataclass(frozen=True)
class Settings:
    base_url: str = os.environ.get("KEYSTONE_LLM_BASE_URL", "https://api.tokenlab.amd.com/v1")
    api_key: str = os.environ.get("KEYSTONE_LLM_API_KEY", "")
    model: str = os.environ.get("KEYSTONE_MODEL", "DeepSeek-V4.1-Flash")
    verifier_model: str = os.environ.get("KEYSTONE_VERIFIER_MODEL", "Gemma-4-31B-IT")
    fallback_models: tuple[str, ...] = tuple(m for m in os.environ.get("KEYSTONE_FALLBACK_MODELS", "Gemma-4-31B-IT,Qwen3.8-27B,DeepSeek-V4-Flash,MiniCPM-V-4.7-35B-A3B").split(",") if m)
    rpm: int = int(os.environ.get("KEYSTONE_RPM", "18"))
    cache: bool = os.environ.get("KEYSTONE_CACHE", "1") == "1"
    cache_dir: Path = Path(os.environ.get("KEYSTONE_CACHE_DIR", str(ROOT / "demo_cache" / "llm")))
    runs_dir: Path = Path(os.environ.get("KEYSTONE_RUNS_DIR", str(_WRITABLE / "runs")))
    serverless: bool = SERVERLESS
    timeout_s: float = float(os.environ.get("KEYSTONE_TIMEOUT", "100"))


settings = Settings()
