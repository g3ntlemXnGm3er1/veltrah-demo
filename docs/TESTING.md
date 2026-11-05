# Reproduce the checks

From the repo root, with Python 3.10+ and Node 24:

```sh
npm --prefix frontend ci --ignore-scripts
python3 tools/check_repo.py
```

Windows: use `py -3` in place of `python3`. The check script uses that same Python for subprocesses. Python tests and the launcher smoke use `-S` to exclude installed site packages and verify the bundled WebSocket path. No optional camera packages are required.

Individual checks:

```sh
python3 -S -m unittest discover -s backend/tests -v
npm --prefix frontend test
npm --prefix frontend run build
python3 -S tools/smoke_demo.py
python3 tools/build_offline_preview.py
```

## Browser integration

This optional suite installs a browser for automated local testing, then starts and stops its own Python service. It exercises real DOM behavior and sockets. It uses fixed local ports 19765 and 19000; stop other processes using those ports first.

```sh
npm --prefix qa ci --ignore-scripts
cd qa
npx playwright install chromium
cd ..
node tools/verify_browser.cjs
```

On Linux, Playwright may require OS browser libraries; its documented `install --with-deps chromium` command installs them. The packaged demo itself does not need Playwright. On Windows before running the suite, choose an installed Python executable, for example PowerShell `$env:VELTRAH_TEST_PYTHON = 'python'`.

To include the standalone preview in browser checks:

```sh
# macOS/Linux
VELTRAH_OFFLINE_HTML=Veltrah_Demo_Offline.html node tools/verify_browser.cjs
```

```powershell
# Windows PowerShell
$env:VELTRAH_TEST_PYTHON = 'python'
$env:VELTRAH_OFFLINE_HTML = 'Veltrah_Demo_Offline.html'
node tools/verify_browser.cjs
```

Results and screenshots go to ignored `evidence/browser/` by default. Override with `VELTRAH_QA_OUTPUT`. Camera-source tests are **protocol stubs**; no camera, model inference or gaze accuracy is tested. The no-external-request check concerns the tested browser runtime, not dependency downloads.

## Evidence limits

`evidence/verification.json` and its linked text logs record this package's actual execution results. Supplied CI is a reproducible future check definition, not proof that every platform matrix has run. Current local checks are Linux only. Test counts do not establish production readiness, accessibility certification, empirical gaze performance, clinical benefit or customer demand.
