"""Vercel entrypoint (also usable with any ASGI server: `uvicorn app:app`).

Vercel detects a FastAPI instance named `app` in a root-level app.py.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))  # works whether or not the package was installed

from keystone.api import app  # noqa: E402,F401
