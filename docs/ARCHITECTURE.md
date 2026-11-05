# Runtime and boundaries

`run_demo.py` adds the included `vendor` directory to Python's import path, then starts loopback HTTP and WebSocket servers. HTTP serves only `frontend/dist` and explicit `/health` and `/config.json` routes. The browser fetches its socket port before connecting.

Each UI socket receives a separate `FixtureSession`, session ID and sequence. The service loads three synthetic scenarios. Selecting a reply creates a client-side draft. A separate confirm command sends a request ID, option ID, session ID and sequence; Python validates them and acknowledges a **local fixture selection**. Duplicate requests receive the same acknowledgement; stale sessions and conflicts are rejected. The frontend accepts an acknowledgement only for its current pending request. It does not queue confirmations while disconnected.

`DwellTracker` uses elapsed time, not event count. Default dwell is 700 ms. Input mode changes, lost/stale samples, blur, cancellation and disconnection invalidate pending interaction state. Coordinate input expires after 450 ms without a valid update. These guards do not establish real-world gaze usability.

External producers use a separate socket and `tracker_hello`, then declare `source: synthetic` or `source: camera`. The UI gates samples by the selected mode. This is **not authenticated hardware identity**. Coordinates are relayed across connected UI clients. Use one producer at a time on a trusted local machine, stop it and reset before switching. No user accounts, database or production authorization model is provided.

The optional camera adapter explicitly opens hardware only when invoked with a local model. It extracts heuristic iris ratios using MediaPipe Tasks, fits an affine mapping and rejects unsuitable calibration/validation data. Tests use synthetic landmarks, calibration samples and protocol stubs. Head-pose compensation, empirical accuracy and screen-to-browser alignment remain unvalidated.

Browser-only transport is selected explicitly by the standalone HTML or `?standalone=1`; it never silently replaces a failed backend. Its simulated timing and acknowledgement metadata differ from Python's. Treat it as an interaction preview, not transport proof.

Default runtime has no external API calls, analytics, persistent message storage or camera capture. Metrics are capped in memory and written only through explicit export. Real user-supplied traces and future integrations require their own data review.
