#!/usr/bin/env python3
"""Launch the local recovered fixture demo; no installation or API calls."""
from __future__ import annotations

import argparse
import asyncio
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
# A pure-Python websockets copy with its license is packaged by the recovery task.
if (ROOT / "vendor").is_dir():
    sys.path.insert(0, str(ROOT / "vendor"))
sys.path.insert(0, str(ROOT))


def port_number(value):
    try:
        port = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Port must be an integer.") from exc
    if not 1024 <= port <= 65535:
        raise argparse.ArgumentTypeError("Choose an unprivileged port from 1024 to 65535.")
    return port


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run Veltrah's local synthetic recovery demo. No real messages are delivered.")
    parser.add_argument("--host", choices=["127.0.0.1", "localhost"], default="127.0.0.1", help="Loopback only; public serving is not supported.")
    parser.add_argument("--http-port", type=port_number, default=8765)
    parser.add_argument("--ws-port", type=port_number, default=8000)
    parser.add_argument("--open", action="store_true", help="Explicitly open the local URL in your browser.")
    args = parser.parse_args(argv)
    if sys.version_info < (3, 10):
        parser.exit(2, "Python 3.10 or newer is required.\n")
    if args.http_port == args.ws_port:
        parser.error("HTTP and WebSocket ports must differ.")
    asset_root = ROOT / "frontend" / "dist"
    if not (asset_root / "index.html").is_file():
        parser.exit(2, "Built frontend not found at frontend/dist/index.html. Use the packaged build, or run npm ci && npm run build in frontend.\n")
    try:
        from backend.recovery_server import run_services
    except ImportError as exc:
        parser.exit(2, f"Demo dependency is missing ({exc.name}). Use the packaged vendor directory or install requirements-demo.txt in a private environment.\n")
    try:
        asyncio.run(run_services(host="127.0.0.1", http_port=args.http_port, ws_port=args.ws_port, asset_root=asset_root, open_browser=args.open))
    except KeyboardInterrupt:
        print("\nRecovery demo stopped.")
        return 0
    except OSError as exc:
        parser.exit(2, f"Could not start local services: {exc}. Try different --http-port and --ws-port values.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
