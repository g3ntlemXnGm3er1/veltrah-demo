# Veltrah frontend

The active entry point is `src/recovery/main.jsx`. This is a React interface for
synthetic reply selection, cancellation and separate local confirmation. It does
not deliver messages or call an AI service.

The prebuilt `dist/` directory is included so the Python launcher can run without
Node or an installation step. See the repository README for the fastest launch.

## Develop and rebuild

Use Node 22.12 or newer (Node 24.22.1 was used for this handoff):

```sh
npm ci --ignore-scripts
npm test
npm run build
```

To develop against the Python backend, start `python3 run_demo.py` from the repo
root in one terminal and `npm run dev` from this directory in another. Open the
Vite URL shown in that terminal. The development frontend expects WebSocket port
8000; the packaged Python-served build reads the configured port from
`/config.json`. Use the packaged launcher when testing custom backend ports.

## Source map

| File | Responsibility |
| --- | --- |
| `src/recovery/main.jsx` | React screen, input modes and interaction lifecycle |
| `src/recovery/interaction.js` | Clock-driven dwell, session guards and metrics |
| `src/recovery/transport.js` | WebSocket transport and explicitly selected browser fixtures |
| `src/recovery/original-theme.css` | Charcoal, gold and mint presentation |
| `../fixtures/scenarios.json` | Shared synthetic conversations used by both runtimes |
| `tests/` | State and transport tests using Node's built-in test runner |

Browser fixtures can be selected explicitly with `?standalone=1` on a local URL.
They are not a silent fallback when Python disconnects. Camera mode requires
fresh samples from the separate experimental adapter; it is unavailable in
browser-only mode. Software tests do not establish physical gaze accuracy.

`THIRD_PARTY_LICENSES_FRONTEND.txt` contains the recovered runtime notices. The
root rights/provenance documentation applies to application source.
