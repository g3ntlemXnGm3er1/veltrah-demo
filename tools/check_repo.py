#!/usr/bin/env python3
"""Run the documented developer checks with the current Python executable."""
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    node = shutil.which("node")
    npm = shutil.which("npm.cmd") if sys.platform == "win32" else shutil.which("npm")
    if not node or not npm:
        print("Install Node 24 for developer checks. Running the packaged demo requires only Python.", file=sys.stderr)
        return 2
    if not (ROOT / "frontend/node_modules/vite").is_dir():
        print("First run: npm --prefix frontend ci --ignore-scripts", file=sys.stderr)
        return 2
    stages = [
        ("Python behavior/protocol/calibration", [sys.executable, "-S", "-m", "unittest", "discover", "-s", "backend/tests", "-v"], ROOT),
        ("Frontend interaction/transport", [node, "--test", *[str(p) for p in sorted((ROOT / "frontend/tests").glob("*.test.js"))]], ROOT),
        ("Production frontend build", [npm, "run", "build"], ROOT / "frontend"),
        ("Actual launcher smoke", [sys.executable, "-S", "tools/smoke_demo.py"], ROOT),
    ]
    for label, command, cwd in stages:
        print(f"\nCHECK: {label}", flush=True)
        result = subprocess.run(command, cwd=cwd)
        if result.returncode:
            return result.returncode
    print("\nAll developer checks passed. Camera hardware and real user benefit remain unverified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
