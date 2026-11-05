#!/bin/sh
# Extension-free VS Code task launcher. Install nothing; use a local Python.
CDPATH= cd "$(dirname "$0")/.." || exit 1
for veltrah_python in python3 python; do
  if command -v "$veltrah_python" >/dev/null 2>&1 &&
     "$veltrah_python" -S -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
    if [ "${1-}" = "--smoke-check" ]; then
      shift
      exec "$veltrah_python" -S tools/smoke_demo.py "$@"
    fi
    exec "$veltrah_python" -S run_demo.py "$@"
  fi
done
echo 'Python 3.10+ was not found on PATH. Install it, then restart VS Code.' >&2
echo 'For a browser-only fixture preview, open Veltrah_Demo_Offline.html.' >&2
exit 2
