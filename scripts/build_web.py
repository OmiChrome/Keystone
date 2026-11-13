"""Build the React UI into web/dist. Used by Vercel's build step (and handy locally).

Tries, in order: an installed `bun`, `npx bun` (Node is present on Vercel build images), then installs Bun.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "web"


def run(cmd: list[str]) -> bool:
    print("+", " ".join(cmd), flush=True)
    return subprocess.run(cmd, cwd=WEB).returncode == 0


def main() -> None:
    shutil.rmtree(WEB / "dist", ignore_errors=True)  # no stale bundles
    candidates: list[list[str]] = []
    if shutil.which("bun"):
        candidates.append(["bun"])
    if shutil.which("npx"):
        candidates.append(["npx", "--yes", "bun@1.3.0"])
    for bun in candidates:
        if run(bun + ["install", "--frozen-lockfile"]) and run(bun + ["run", "build"]):
            print("UI built ->", WEB / "dist")
            return
    # last resort: official installer
    home = Path.home() / ".bun" / "bin" / "bun"
    if subprocess.run("curl -fsSL https://bun.sh/install | bash", shell=True).returncode == 0 and home.exists():
        if run([str(home), "install", "--frozen-lockfile"]) and run([str(home), "run", "build"]):
            return
    sys.exit("could not build the UI: no bun / npx available")


if __name__ == "__main__":
    os.environ.setdefault("CI", "1")
    main()
