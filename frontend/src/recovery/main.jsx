import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { DwellTracker, SessionGuard, MetricsLog } from './interaction.js';
import { createTransport, SCENARIOS } from './transport.js';
import './original-theme.css';

const MODES = [
  ['mouse', 'Mouse dwell', 'Hold over a reply for 0.7 seconds, or click it. Then confirm deliberately.'],
  ['keyboard', 'Keyboard', 'Tab to a reply and press Enter, or use keys 1–4. Confirmation is a separate action.'],
  ['synthetic', 'Synthetic gaze replay', 'Replay generated coordinates over a reply. This is not eye tracking.'],
  ['camera', 'Experimental camera', 'Requires the separate local camera adapter and calibration. Accuracy is unverified.'],
];
const SCENARIO_NAMES = { planning: 'Make a plan', logistics: 'Coordinate a delivery', social: 'Stay in touch' };
const INITIAL = { connection: 'connecting', transport: 'pending', session: null, scenario: 'planning', mode: 'mouse',
  draft: null, pending: false, committed: null, progress: 0, activeTarget: null, point: null,
  cameraAvailable: false, cameraState: 'No camera adapter', notice: 'Connecting to the local fixture service…',
  state: 'connecting', counts: { selected: 0, cancelled: 0, committed: 0 }, events: 0 };

function App() {
  const [model, setModel] = useState(INITIAL);
  const modelRef = useRef(INITIAL);
  const guard = useRef(new SessionGuard());
  const dwell = useRef(new DwellTracker());
  const transport = useRef(null);
  const metrics = useRef(new MetricsLog());
  const point = useRef({ x: 0, y: 0, valid: false, at: 0, source: 'mouse' });
  const camera = useRef({ at: 0, valid: false, state: 'No camera adapter' });
  const replay = useRef(null);
  const focus = useRef(true);
  const optionRefs = useRef(new Map());
  const selectionStart = useRef(0);
  const alive = useRef(true);

  function update(patch) {
    const next = { ...modelRef.current, ...patch };
    modelRef.current = next;
    if (alive.current) setModel(next);
  }
  function record(event, details) {
    metrics.current.record(event, modelRef.current, details);
    update({ events: metrics.current.events.length });
  }
  function stopInput({ reset = false } = {}) {
    if (reset) dwell.current.reset(); else dwell.current.cancel();
    replay.current = null;
    point.current = { ...point.current, valid: false };
    update({ progress: 0, activeTarget: null, point: null });
  }
  function cancel(reason = 'cancel_button', { announce = true } = {}) {
    const m = modelRef.current;
    const active = Boolean(m.draft || m.progress > 0);
    const hadPending = Boolean(guard.current.pending);
    if (hadPending) guard.current.invalidate(); else guard.current.cancel();
    stopInput();
    update({ draft: null, ...(hadPending ? { session: null, pending: false, state: 'paused' } : {}),
      counts: active ? { ...m.counts, cancelled: m.counts.cancelled + 1 } : m.counts,
      ...(announce && hadPending ? { notice: 'Pending local acknowledgement discarded. Reset the trial before continuing.' } : {}),
      ...(announce && active ? { notice: 'Selection cancelled. Nothing was committed.' } : {}) });
    if (active) record('cancelled', { reason });
    if (hadPending) record('pending_ack_discarded', { reason });
  }
  function select(id, reason = 'click') {
    if (modelRef.current.mode === 'camera' && (!camera.current.valid || performance.now() - camera.current.at > 450)) return;
    if (!guard.current.select(id)) return;
    const m = modelRef.current;
    dwell.current.blockedTarget = id;
    update({ draft: id, progress: 0, activeTarget: null, committed: null,
      counts: { ...m.counts, selected: m.counts.selected + 1 },
      notice: 'Reply selected as a draft. Confirm locally or cancel.' });
    record('draft_selected', { target_id: id, reason, elapsed_ms: Math.round(performance.now() - selectionStart.current) });
  }
  function commit() {
    const request = guard.current.beginCommit();
    if (!request) return;
    stopInput(); update({ draft: null, pending: true, notice: 'Recording your explicit selection locally…', state: 'committing' });
    record('commit_requested', { target_id: request.option_id });
    if (!transport.current?.send(request)) {
      guard.current.failRequest(request.request_id);
      update({ pending: false, notice: 'Connection unavailable. Nothing was queued or resent.', state: 'error' });
      record('commit_unavailable', { reason: 'disconnected' });
    }
  }
  function command(data) {
    if (modelRef.current.connection !== 'connected') {
      update({ notice: 'Start or reconnect the local service before loading a trial.' }); return;
    }
    cancel('trial_changed', { announce: false }); guard.current.invalidate();
    update({ session: null, committed: null, pending: false, state: 'loading', notice: 'Loading a synthetic conversation…' });
    if (!transport.current?.send(data)) update({ state: 'error', notice: 'Connection unavailable. No command was queued.' });
    record(data.type === 'simulate' ? 'simulation_requested' : 'trial_requested', { reason: data.kind || data.type });
  }
  function setMode(mode) {
    if (mode === 'camera' && (!modelRef.current.cameraAvailable || modelRef.current.transport === 'browser-fixtures')) return;
    cancel('input_mode_changed', { announce: false }); stopInput({ reset: true });
    update({ mode, notice: MODES.find(x => x[0] === mode)[2] });
    record('mode_changed');
  }
  function handleData(data) {
    if (!data || typeof data !== 'object') return;
    if (data.type === 'session') {
      if (!guard.current.setSession(data)) {
        update({ session: null, draft: null, pending: false, state: 'error', notice: 'Unexpected session data. Reload a scenario to recover.' });
        record('protocol_error', { code: 'invalid_session' }); return;
      }
      stopInput({ reset: true }); selectionStart.current = performance.now();
      update({ session: data, scenario: data.scenario || modelRef.current.scenario, draft: null, committed: null, pending: false,
        state: 'ready', notice: 'Synthetic replies are ready. Select a reply; confirmation stays separate.' });
      record('session_ready');
    } else if (data.type === 'selection_ack') {
      if (!guard.current.acceptAck(data)) { record('ack_ignored', { reason: 'stale_or_duplicate' }); return; }
      const m = modelRef.current; stopInput({ reset: true });
      update({ session: null, committed: { text: data.text, option_id: data.option_id }, pending: false, draft: null, state: 'complete',
        counts: { ...m.counts, committed: m.counts.committed + 1 }, notice: 'Selection recorded locally. No message was sent.' });
      record('commit_acknowledged', { target_id: data.option_id, elapsed_ms: Number.isFinite(data.elapsed_ms) ? data.elapsed_ms : 0 });
    } else if (data.type === 'status') {
      const state = String(data.state || 'notice');
      if (['generating', 'loading', 'error', 'failed', 'generation_failed', 'generation_failure'].includes(state)) {
        cancel('service_status_changed', { announce: false }); guard.current.invalidate();
        update({ session: null, pending: false, draft: null, state: ['generating', 'loading'].includes(state) ? 'loading' : 'error' });
      }
      update({ notice: typeof data.message === 'string' ? data.message : 'Fixture service status changed.' });
      record('service_status', { status: state });
    } else if (data.type === 'error') {
      guard.current.failRequest(data.request_id); cancel('service_error', { announce: false });
      update({ pending: false, state: 'error', notice: typeof data.message === 'string' ? data.message : 'Fixture service rejected the request.' });
      record('service_error', { code: String(data.code || 'unknown') });
    } else if (data.type === 'coordinates' && data.source === 'camera') {
      const valid = data.valid === true && Number.isFinite(data.x) && Number.isFinite(data.y) && data.x >= 0 && data.x <= 1 && data.y >= 0 && data.y <= 1;
      camera.current = { at: performance.now(), valid, state: valid ? 'Camera samples received' : 'Tracking lost' };
      if (modelRef.current.mode === 'camera') {
        point.current = { x: data.x, y: data.y, at: performance.now(), valid, source: 'camera' };
        if (!valid) cancel('camera_tracking_lost');
      }
    } else if (data.type === 'coordinates' && data.source === 'synthetic') {
      const valid = data.valid === true && Number.isFinite(data.x) && Number.isFinite(data.y) && data.x >= 0 && data.x <= 1 && data.y >= 0 && data.y <= 1;
      if (modelRef.current.mode === 'synthetic' && !replay.current) {
        point.current = { x: data.x, y: data.y, at: performance.now(), valid, source: 'synthetic' };
        if (!valid) cancel('synthetic_tracking_lost');
      } else if (modelRef.current.mode === 'camera') {
        camera.current.valid = false; cancel('camera_source_changed');
      }
    } else if (data.type === 'tracker_status' && data.source === 'synthetic') {
      if (modelRef.current.mode === 'synthetic' && ['lost', 'stopped', 'error', 'disconnected'].includes(data.state)) cancel(`synthetic_${data.state}`);
    } else if (data.type === 'tracker_status' && data.source === 'camera') {
      const state = String(data.state || 'unknown'); camera.current.state = `Camera: ${state}`;
      if (['lost', 'stopped', 'error', 'disconnected', 'calibrating'].includes(state)) {
        camera.current.valid = false;
        if (modelRef.current.mode === 'camera') cancel(`camera_${state}`);
      }
      update({ cameraState: camera.current.state });
    } else if (data.type === 'tracker_status' && ['lost', 'stopped', 'error', 'disconnected'].includes(data.state)) {
      // An abruptly disconnected producer may have no trustworthy source field.
      // It can stop active gaze input but can never enable a camera claim.
      if (modelRef.current.mode === 'camera' || modelRef.current.mode === 'synthetic') {
        camera.current.valid = false; cancel('unknown_tracker_stopped');
        update({ cameraAvailable: false, cameraState: 'Tracker disconnected' });
      }
    }
  }

  useEffect(() => {
    alive.current = true; let mounted = true; let frame; let lastPaint = 0;
    const callbacks = {
      open: () => {
        if (!mounted) return;
        guard.current.setConnected(true); guard.current.invalidate(); stopInput({ reset: true });
        update({ connection: 'connected', session: null, draft: null, pending: false, state: 'loading', notice: 'Loading a synthetic conversation…' });
        record('connected'); transport.current.send({ type: 'ready', scenario: modelRef.current.scenario });
      },
      close: () => {
        if (!mounted) return;
        cancel('connection_lost', { announce: false }); guard.current.setConnected(false); camera.current.valid = false;
        update({ connection: 'disconnected', session: null, pending: false, draft: null, state: 'disconnected', cameraAvailable: false,
          notice: 'Local service disconnected. Actions are paused; no selection is queued. Reconnecting…' });
        record('disconnected');
      },
      message: data => { if (mounted) handleData(data); },
      protocolError: () => { if (mounted) { cancel('invalid_message'); record('protocol_error', { code: 'invalid_json' }); } },
    };
    createTransport(callbacks).then(t => {
      if (!mounted) { t.close(); return; }
      transport.current = t; update({ transport: t.kind }); t.connect();
    }).catch(error => update({ connection: 'disconnected', state: 'error', notice: error.message }));

    const mousemove = event => {
      if (modelRef.current.mode !== 'mouse') return;
      point.current = { x: event.clientX / innerWidth, y: event.clientY / innerHeight, valid: true, at: performance.now(), source: 'mouse' };
    };
    const leave = () => { if (modelRef.current.mode === 'mouse') { cancel('pointer_left_window'); dwell.current.reset(); } };
    const blur = () => { focus.current = false; cancel('focus_lost'); };
    const regain = () => { focus.current = true; point.current.valid = false; };
    const visibility = () => { if (document.hidden) blur(); else regain(); };
    const keydown = event => {
      if (event.key === 'Escape') { cancel('escape'); return; }
      if (modelRef.current.mode !== 'keyboard' || event.altKey || event.ctrlKey || event.metaKey || event.repeat) return;
      if (['INPUT', 'TEXTAREA', 'SELECT'].includes(event.target.tagName)) return;
      if (/^[1-4]$/.test(event.key)) {
        const option = modelRef.current.session?.options[Number(event.key) - 1];
        if (option) { event.preventDefault(); select(option.id, 'keyboard_shortcut'); }
      }
    };
    window.addEventListener('mousemove', mousemove);
    document.addEventListener('mouseleave', leave);
    window.addEventListener('blur', blur); window.addEventListener('focus', regain);
    document.addEventListener('visibilitychange', visibility); window.addEventListener('keydown', keydown);

    function tick(now) {
      const m = modelRef.current;
      const cameraFresh = camera.current.valid && now - camera.current.at <= 450 && m.transport !== 'browser-fixtures';
      if (m.mode === 'camera' && !cameraFresh && (m.draft || m.progress > 0)) cancel('camera_samples_stale');
      const syntheticFresh = point.current.valid && now - point.current.at <= 450;
      if (m.mode === 'synthetic' && !replay.current && !syntheticFresh && (m.draft || m.progress > 0)) cancel('synthetic_samples_stale');
      if (replay.current && m.mode === 'synthetic') {
        const element = optionRefs.current.get(replay.current.optionId);
        if (element && now - replay.current.start < 30000 && m.session) {
          const rect = element.getBoundingClientRect();
          point.current = { x: (rect.left + rect.width / 2) / innerWidth, y: (rect.top + rect.height / 2) / innerHeight, valid: true, at: now, source: 'synthetic' };
        } else { replay.current = null; point.current.valid = false; }
      }
      const p = point.current;
      const valid = p.valid && focus.current && !document.hidden && m.connection === 'connected' && m.state === 'ready'
        && Boolean(m.session) && !m.draft && !m.pending && m.mode !== 'keyboard' && (m.mode !== 'camera' || cameraFresh);
      let target = null;
      if (valid) {
        const x = p.x * innerWidth, y = p.y * innerHeight;
        for (const [id, element] of optionRefs.current) {
          if (!element) continue;
          const r = element.getBoundingClientRect();
          if (x >= r.left && x <= r.right && y >= r.top && y <= r.bottom) { target = id; break; }
        }
      }
      const result = dwell.current.tick({ target, now, valid, sampleAt: p.at, requireFresh: m.mode === 'camera' || m.mode === 'synthetic', sessionKey: m.session ? `${m.session.session_id}/${m.session.sequence}/${m.mode}` : `none/${m.mode}` });
      if (result.selected) select(result.selected, m.mode === 'synthetic' ? 'synthetic_replay' : `${m.mode}_dwell`);
      if (now - lastPaint > 45) {
        lastPaint = now;
        update({ progress: result.selected ? 0 : result.progress, activeTarget: target,
          point: p.valid && focus.current && (m.mode !== 'camera' || cameraFresh) && m.mode !== 'keyboard' ? { x: p.x, y: p.y } : null,
          cameraAvailable: cameraFresh, cameraState: cameraFresh ? camera.current.state : camera.current.valid ? 'Camera samples stale' : camera.current.state });
      }
      frame = requestAnimationFrame(tick);
    }
    frame = requestAnimationFrame(tick);
    return () => {
      mounted = false; alive.current = false; cancelAnimationFrame(frame); transport.current?.close();
      window.removeEventListener('mousemove', mousemove); document.removeEventListener('mouseleave', leave);
      window.removeEventListener('blur', blur); window.removeEventListener('focus', regain);
      document.removeEventListener('visibilitychange', visibility); window.removeEventListener('keydown', keydown);
    };
  }, []);

  function startReplay(index = 0) {
    cancel('replay_started', { announce: false }); dwell.current.reset();
    const option = modelRef.current.session?.options[index];
    if (!option || modelRef.current.mode !== 'synthetic') return;
    replay.current = { optionId: option.id, start: performance.now() };
    update({ notice: `Holding a synthetic fixation over reply ${index + 1} for up to 30 seconds. Confirm locally or cancel.` });
    record('replay_started', { target_id: option.id });
  }
  function exportMetrics() {
    const content = JSON.stringify(metrics.current.export(modelRef.current), null, 2);
    const url = URL.createObjectURL(new Blob([content], { type: 'application/json' }));
    const a = document.createElement('a'); a.href = url; a.download = 'veltrah_local_session_metrics.json'; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  const draft = model.session?.options.find(x => x.id === model.draft);
  const canOperate = model.connection === 'connected';
  const browserOnly = model.transport === 'browser-fixtures';
  return <main className="app-shell">
    <header className="topbar">
      <a className="brand" href="#main-demo" aria-label="Veltrah local recovery demo"><span className="brand-mark" aria-hidden="true">V</span><span>VELTRAH<span className="brand-sub">CROWNGUARD</span></span></a>
      <div className="top-status"><span className={`status-dot ${model.connection}`} aria-hidden="true" /><span data-testid="connection-status">{browserOnly ? 'Browser-only fixtures' : model.connection === 'connected' ? 'Local Python backend' : model.connection === 'connecting' ? 'Connecting locally' : 'Local backend offline'}</span><span className="version-tag">RECOVERY / 01</span></div>
    </header>
    <section className="intro"><div><p className="eyebrow">VELTRAH / SOFTWARE PROTOTYPE</p><h1>CrownGuard reply demo</h1><p>Select a suggested reply, then deliberately confirm or cancel.</p></div><div className="scope-pill"><span aria-hidden="true">◇</span> Synthetic conversation<br /><strong>No messages are sent</strong></div></section>
    <div className="workspace">
      <section className="demo-column" id="main-demo" aria-label="Recovered HUD interaction">
        <div className="stage-top"><span><span className="tiny-dot" /> CROWNGUARD / REPLY</span><span>{browserOnly ? 'BROWSER FIXTURES · NO BACKEND' : 'PYTHON + WEBSOCKET · FIXTURE DATA'}</span></div>
        <div className="hud-stage" data-testid="hud-stage">
          <div className="scene-grid" aria-hidden="true" /><div className="scene-orbit orbit-one" aria-hidden="true" /><div className="scene-orbit orbit-two" aria-hidden="true" />
          <div className="hud-caption"><span className="hud-aperture" aria-hidden="true">⌖</span><span>GLANCEABLE INTERFACE<br /><b>One local interaction</b></span></div>
          <div className="hud-content">
            {model.session ? <>
              <div className="incoming-card"><div className="message-meta"><span className="avatar" aria-hidden="true">{model.session.incoming.from.slice(0, 1)}</span><span>{model.session.incoming.from}<small>Synthetic incoming message</small></span><span className="message-icon" aria-hidden="true">↙</span></div><p data-testid="incoming-text">{model.session.incoming.text}</p></div>
              <div className="reply-heading"><span>CHOOSE A REPLY</span><span>{model.mode === 'keyboard' ? 'KEYS 1–4 / TAB' : model.mode === 'synthetic' ? 'SYNTHETIC REPLAY' : model.mode === 'camera' ? 'EXPERIMENTAL CAMERA' : '0.7 SECOND DWELL'}</span></div>
              <div className="reply-list">
                {model.session.options.map((option, index) => <button key={option.id} type="button" className={`reply-option ${model.draft === option.id ? 'selected' : ''}`} disabled={model.pending}
                  ref={element => { if (element) optionRefs.current.set(option.id, element); else optionRefs.current.delete(option.id); }}
                  data-testid={`reply-${index + 1}`} data-option-id={option.id} aria-pressed={model.draft === option.id}
                  onClick={event => select(option.id, event.detail === 0 ? 'keyboard' : 'click')}>
                  <span className="option-number">{String(index + 1).padStart(2, '0')}</span><span>{option.text}</span><span className="option-arrow" aria-hidden="true">↗</span>
                  <span className="dwell-progress" data-testid={`dwell-${index + 1}`} style={{ transform: `scaleX(${model.activeTarget === option.id ? model.progress : 0})` }} />
                </button>)}
              </div>
            </> : model.committed ? <div className="complete-card" data-testid="selection-result"><span className="complete-icon" aria-hidden="true">✓</span><p className="eyebrow">RECORDED LOCALLY</p><h2>Your choice stayed deliberate.</h2><blockquote>{model.committed.text}</blockquote><p>This was a local fixture acknowledgement.<br />No SMS, email or external message was sent.</p><button type="button" className="stage-button" onClick={() => command({ type: 'reset', scenario: model.scenario })}>Start another trial <span aria-hidden="true">↗</span></button></div>
            : <div className={`waiting-card ${model.state === 'error' ? 'is-error' : ''}`} data-testid="empty-state"><span className="waiting-symbol" aria-hidden="true">{model.state === 'error' || model.state === 'disconnected' ? '!' : '◇'}</span><h2>{model.state === 'error' ? 'The fixture is paused.' : model.state === 'disconnected' ? 'Connection lost.' : model.state === 'paused' ? 'Start a fresh trial.' : 'Preparing a conversation…'}</h2><p>{model.state === 'disconnected' ? 'Start the local service. Actions resume with a fresh session after reconnecting.' : model.state === 'error' ? 'Try Recover fixture in the workbench. No new reply can be committed while paused.' : model.state === 'paused' ? 'The input context changed before acknowledgement. Use Reset trial; nothing is queued or resent.' : 'Only local synthetic data is used.'}</p></div>}
          </div>
          <div className="stage-bottom"><span>INPUT <b>{MODES.find(x => x[0] === model.mode)[1]}</b></span><span>TRANSPORT <b>{browserOnly ? 'IN BROWSER' : 'LOCAL FIXTURES'}</b></span><span>DELIVERY <b>NONE</b></span></div>
        </div>
        <div className={`confirmation ${draft || model.pending ? 'has-draft' : ''}`} aria-live="polite" data-testid="confirmation">
          <div><span className="confirm-step">{draft ? '02' : '01'}</span><div><p className="eyebrow">{model.pending ? 'RECORDING LOCALLY' : draft ? 'CONFIRM OR CANCEL' : 'SELECTION IS NOT CONFIRMATION'}</p><p data-testid="draft-text">{draft ? draft.text : model.pending ? 'Waiting for the local acknowledgement…' : 'A reply becomes a draft first. Looking alone never confirms it.'}</p></div></div>
          <div className="confirm-actions"><button type="button" className="quiet-button" disabled={!draft} onClick={() => cancel()} aria-label="Cancel selection">Cancel <kbd>Esc</kbd></button><button type="button" className="primary-button" data-testid="confirm-button" disabled={!draft || model.pending || !canOperate} onClick={commit} aria-label="Confirm selection">Confirm locally <span aria-hidden="true">↗</span></button></div>
        </div>
        <div className={`notice-bar ${model.state === 'error' || model.state === 'disconnected' ? 'notice-error' : ''}`} role="status" data-testid="notice"><span aria-hidden="true">{model.state === 'error' || model.state === 'disconnected' ? '!' : '•'}</span>{model.notice}</div>
      </section>
      <aside className="workbench" aria-label="Test workbench">
        <div className="workbench-heading"><div><p className="eyebrow">TECHNICAL WALKTHROUGH</p><h2>Demo controls</h2></div><span className="panel-icon" aria-hidden="true">⌘</span></div>
        <div className="control-section"><label htmlFor="input-mode">01 / Input method</label><select id="input-mode" data-testid="input-mode" value={model.mode} onChange={event => setMode(event.target.value)}>{MODES.map(([value, label]) => <option value={value} key={value} disabled={value === 'camera' && (!model.cameraAvailable || browserOnly)}>{label}{value === 'camera' && (!model.cameraAvailable || browserOnly) ? ' · unavailable' : ''}</option>)}</select><p className="control-help">{MODES.find(x => x[0] === model.mode)[2]}</p>
          {model.mode === 'synthetic' && <button type="button" className="outline-button full" data-testid="replay-button" onClick={() => startReplay()} disabled={!model.session || model.pending}>Replay over reply 1 <span aria-hidden="true">▷</span></button>}
          <p className="camera-note" data-testid="camera-status"><span className={`tiny-dot ${model.cameraAvailable ? 'available' : ''}`} />{browserOnly ? 'Camera unavailable in browser-only mode' : model.cameraState}</p></div>
        <div className="control-section"><label htmlFor="scenario">02 / Synthetic scenario</label><select id="scenario" data-testid="scenario-select" value={model.scenario} onChange={event => { update({ scenario: event.target.value }); command({ type: 'load_scenario', scenario: event.target.value }); }} disabled={!canOperate}>{SCENARIOS.map(value => <option value={value} key={value}>{SCENARIO_NAMES[value]}</option>)}</select><button type="button" className="outline-button full" data-testid="reset-button" disabled={!canOperate} onClick={() => command({ type: 'reset', scenario: model.scenario })}>Reset trial <span aria-hidden="true">↻</span></button></div>
        <div className="control-section"><span className="control-label">03 / Failure & recovery</span><div className="simulation-buttons"><button type="button" disabled={!canOperate} onClick={() => command({ type: 'simulate', kind: 'generation_failure' })} data-testid="failure-button">Generation failure</button><button type="button" disabled={!canOperate} onClick={() => command({ type: 'simulate', kind: 'delay' })} data-testid="delay-button">Response delay</button><button type="button" disabled={!canOperate} onClick={() => command({ type: 'simulate', kind: 'recover' })} data-testid="recover-button">Recover fixture <span aria-hidden="true">↗</span></button></div></div>
        <div className="control-section metrics-section"><span className="control-label">04 / This local session</span><div className="metric-grid"><div><strong data-testid="selected-count">{model.counts.selected}</strong><span>Selected</span></div><div><strong data-testid="cancelled-count">{model.counts.cancelled}</strong><span>Cancelled</span></div><div><strong data-testid="committed-count">{model.counts.committed}</strong><span>Confirmed</span></div></div><button type="button" className="export-button" onClick={exportMetrics}>Export session metrics <span aria-hidden="true">↓</span></button><p className="control-help">{model.events} events, held in memory. Export excludes message content and raw gaze coordinates.</p></div>
        <div className="scope-note"><b>What this demonstrates</b><p>Local reply selection, cancellation and explicit confirmation. Fixture responses are scripted; gaze replay is synthetic.</p><p>This does not establish live AI, SMS, glasses integration or eye-tracking accuracy.</p></div>
      </aside>
    </div>
    <footer className="app-footer"><span>VELTRAH / PRIVATE RECOVERY BRANCH</span><span>Historical software concept · measurable next step</span></footer>
    {model.point && <div className={`gaze-cursor ${model.mode}`} style={{ left: `${model.point.x * 100}vw`, top: `${model.point.y * 100}vh` }} aria-hidden="true"><span /></div>}
  </main>;
}

class ErrorBoundary extends React.Component {
  constructor(props) { super(props); this.state = { failed: false }; }
  static getDerivedStateFromError() { return { failed: true }; }
  render() { return this.state.failed ? <main className="fatal-error"><h1>The local interface stopped.</h1><p>No further selection can be made. Reload to start a fresh fixture session.</p><button onClick={() => location.reload()}>Reload local demo</button></main> : this.props.children; }
}
createRoot(document.getElementById('root')).render(<ErrorBoundary><App /></ErrorBoundary>);
