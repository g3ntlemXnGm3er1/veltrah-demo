# Veltrah / CrownGuard

A runnable desktop experiment for selecting a suggested reply, cancelling it, and deliberately confirming it. This public technical review repo is recovered from the historical Veltrah prototype and preserves the charcoal, gold and mint interface.

**Start here in VS Code:** clone the repository or extract the downloaded ZIP, open `Veltrah.code-workspace`, then press **Ctrl+Shift+B** (macOS: **Cmd+Shift+B**). The default **Veltrah: Run demo** task starts the app and opens your browser. Opening the repository folder through **File → Open Folder** also loads the task. Requires Python 3.10+ on PATH; VS Code extensions are optional. See [VS Code setup and troubleshooting](docs/VSCODE.md).

The production React frontend and pure-Python WebSocket dependency are included. The default demo needs no npm/pip install, account, API key, camera or model download. Terminal commands are below.

## Run in one command

Open a terminal in the cloned or extracted repository folder. Requires **Python 3.10+**.

```powershell
# Windows
py -3 run_demo.py --open
```

```sh
# macOS / Linux
python3 run_demo.py --open
```

Open **http://127.0.0.1:8765** if the browser does not open. Stop with **Ctrl+C**. Windows users can also double-click `Start_Veltrah_Demo.cmd` or run `./start.ps1`. On macOS, `sh Start_Veltrah_Demo.command` works from a terminal.

If a port is occupied:

```sh
python3 run_demo.py --http-port 8875 --ws-port 8100 --open
```

The launcher binds to this computer only. Do not expose it through a tunnel or public host. If Python is unavailable, open `Veltrah_Demo_Offline.html`: that explicitly labelled browser-only preview does **not** exercise the backend.

## Two-minute walkthrough

1. Hold the mouse still over a reply for **0.7 seconds**. It becomes a draft.
2. Press **Escape** to cancel. Move away and back to start a fresh dwell.
3. Choose another reply, then click **Confirm locally**. Python acknowledges a fixture selection; no message is delivered.
4. Reset the trial, then switch to **Keyboard** and try Tab/Enter or reply keys 1–4. Confirmation stays separate.
5. Reset after any confirmation, then switch to **Synthetic replay** and click **Replay over reply 1**. These generated coordinates are not eye tracking.
6. Try the scenarios, failure, delay, recovery and reset controls. Export session metrics if useful.

## Capability status

| Capability | Status |
|---|---|
| React + real local Python/WebSocket transport | Runnable; automated software checks supplied |
| Mouse dwell, keyboard/click selection, cancel, separate confirm | Implemented; unit and browser checks |
| Conversations and suggested replies | Three deterministic synthetic scenarios; not live AI |
| Reset, stale acknowledgement guards, reconnect, fault injection | Implemented; software checks |
| Synthetic coordinate producer and input-source gates | Implemented; not gaze-performance evidence |
| Session metrics | In memory; explicit export excludes message text and raw gaze coordinates |
| Camera adapter and affine calibration | Experimental source; real camera/model/display accuracy unverified |
| Glasses, live AI, SMS/email delivery, navigation, production SDK | Not implemented or established by this repo |
| Customer benefit, false activations, fatigue, willingness to pay | Unknown; requires real task and user evidence |

## Develop and verify

Pinned React/ReactDOM **19.3.1**, Vite **8.3.5**, with lockfile. Use **Node 24** (minimum 22.12). From the repo root:

```sh
npm --prefix frontend ci --ignore-scripts
python3 tools/check_repo.py
```

On Windows replace `python3` with `py -3`. The check runs the Python suite, frontend unit suite, production build, and a separate-process HTTP/WebSocket smoke test. See [TESTING.md](docs/TESTING.md) for the real browser suite and evidence limits.

For hot reload, keep `python3 run_demo.py` running, then run `npm --prefix frontend run dev` in another terminal and open **http://127.0.0.1:5173**. Development expects WebSocket port **8000**. The packaged production page supports custom ports through `/config.json`.

After frontend changes, run `npm --prefix frontend run build` and `python3 tools/build_offline_preview.py`. Commit source, lockfiles and built assets together. `.github/workflows/ci.yml` supplies checks if you later choose to host the repository; hosted CI has not run merely because this file exists.

## Get a local checkout

On this repository's GitHub page, select **Code → Download ZIP**, extract the archive, then open `Veltrah.code-workspace` in the extracted folder. If you use Git, copy the repository URL from the **Code** menu and clone it with your Git client.

The separately distributed original review ZIP includes `veltrah-review.bundle` for restoring the offline recovery-review history. That bundle is not part of the GitHub source tree or GitHub's generated ZIP download. The recovery-review history is distinct from the original historical prototype commits.

## Code map

| Path | Purpose |
|---|---|
| `run_demo.py` | Loopback HTTP/WebSocket launcher |
| `frontend/src/recovery/main.jsx` | Active UI, input lifecycle and confirmation |
| `frontend/src/recovery/interaction.js` | Dwell tracker, session guards, bounded metrics |
| `frontend/src/recovery/transport.js` | Socket and explicit browser-only fixture transports |
| `frontend/src/recovery/original-theme.css` | Restored presentation |
| `backend/recovery_server.py` | Built-asset serving, configuration, socket roles |
| `backend/fixture_service.py` | Per-browser scenario state and local acknowledgements |
| `backend/recovery_calibration.py` | Dependency-free calibration math and rejection gates |
| `backend/recovery_gaze.py` | Optional camera producer; never started by default |
| `fixtures/scenarios.json` | Shared synthetic data |
| `tools/replay_coordinates.py` | Explicit local synthetic-coordinate producer |
| `backend/tests/`, `frontend/tests/`, `tools/verify_browser.cjs` | Behavioral, protocol and browser tests |

Inactive historical branches, old launchers, credentials and private recruiting documents are excluded. This repo has one active app path. Read [architecture](docs/ARCHITECTURE.md), the [technical review guide](docs/TECHNICAL_REVIEW.md) and [provenance](PROVENANCE.json) for boundaries and next work.

## Review and rights

Original application ownership and contributor assignments are not established by source access. No new application-wide open-source license is granted. See [RIGHTS.md](RIGHTS.md); third-party notices are retained. Confirm applicable disclosure rights before distributing source.

This is a public technical-review repository. Physical camera/glasses behavior, live models, real messaging and customer outcomes remain unvalidated.
