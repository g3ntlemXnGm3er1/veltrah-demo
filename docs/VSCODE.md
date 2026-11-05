# Open and run in VS Code

1. **Extract All** from the ZIP into a normal folder. Do not run from the ZIP viewer.
2. In VS Code choose **File → Open Workspace from File** and select `Veltrah.code-workspace`. **File → Open Folder** on the extracted folder also works: the ZIP places `.vscode` directly at that project root. The same workspace file works inside a Git bundle clone.
3. Review VS Code's normal Workspace Trust prompt. Tasks and debugging need the folder to be trusted.
4. Press **Ctrl+Shift+B** on Windows/Linux or **Cmd+Shift+B** on macOS. This runs the default **Veltrah: Run demo** task. You can also choose it through **Terminal → Run Task**.
5. The browser opens at **http://127.0.0.1:8765**. The backend uses local WebSocket port **8000**. To stop, focus the task terminal and press **Ctrl+C**, or use **Terminal → Terminate Task**.

Requires an installed **Python 3.10+** accessible on PATH. On Windows the task tries `py -3`, then `python`; on macOS/Linux it tries `python3`, then `python`. The packaged demo starts with site packages disabled and uses its included WebSocket dependency and built React frontend. It does not need npm, pip, a virtual environment, VS Code extensions, credentials or camera packages.

Opening a folder does not automatically execute it. Run the task once after opening. The repo does not change your global VS Code, shell or Python settings, and performs no automatic extension/package installation.

## Optional debugging and development

- Install the recommended Microsoft Python/Python Debugger extensions only if you want Python editing/debugging support. Select a Python 3.10+ interpreter with **Python: Select Interpreter**, then press **F5** using **Veltrah: Debug demo (Python extension)**. Stop an existing demo task first so the ports are free.
- **Terminal → Run Task → Veltrah: Smoke check (no npm required)** verifies a separate-process launch on temporary ports and uses the same Python fallback as the demo task.
- Frontend development needs Node 24 and `npm --prefix frontend ci --ignore-scripts`. This is separate from running the packaged demo.
- Optional camera code may show missing imports until the separately documented camera environment is installed. That is not a dependency of the demo task.

## If startup fails

| Symptom | Action |
|---|---|
| No Veltrah task appears | Open `Veltrah.code-workspace` or the extracted project folder containing `.vscode` and `run_demo.py`. Do not open its parent Downloads folder. |
| Python not found | Install Python 3.10+ with its launcher/PATH option, then restart VS Code. No automatic download is performed. |
| Restricted Mode | Review Workspace Trust and enable tasks if you trust this source. |
| Port already in use | Stop the earlier demo terminal, or run `py -3 run_demo.py --http-port 8875 --ws-port 8100 --open` on Windows (`python3` on macOS/Linux). |
| Browser doesn't open | Open the printed localhost URL manually. |
| F5 says debugpy is unsupported | Install the optional recommended extensions, or use Ctrl/Cmd+Shift+B without extensions. |

## Verification scope

Current packaging checks parse the workspace/settings/task/debug JSON, verify all referenced local paths, and exercise a fresh extraction and its Linux task command, including a folder path containing spaces. The application build, Python/frontend tests and HTTP/WebSocket smoke checks are recorded in `evidence/`.

VS Code GUI execution is not verified here: the editor is not installed in this environment. Windows/macOS launchers have been reviewed but still need native-machine execution. No configuration can guarantee startup without a compatible local Python or override an individual machine's trust, PATH, firewall or occupied-port state.

Official configuration references, checked November 4, 2026:

- https://code.visualstudio.com/docs/debugtest/tasks
- https://code.visualstudio.com/docs/python/debugging
- https://code.visualstudio.com/docs/editing/workspaces/multi-root-workspaces
