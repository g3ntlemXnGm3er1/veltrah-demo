import scenarios from '../../../fixtures/scenarios.json' with { type: 'json' };
export const SCENARIOS = ['planning', 'logistics', 'social'];
const clone = value => JSON.parse(JSON.stringify(value));

/** Explicit browser-only fixtures. Never an automatic network fallback. */
export class BrowserFixtureTransport {
  constructor(callbacks, { delayMs = 1200, schedule = (...args) => globalThis.setTimeout(...args), unschedule = (...args) => globalThis.clearTimeout(...args) } = {}) {
    this.callbacks = callbacks; this.kind = 'browser-fixtures'; this.delayMs = delayMs;
    this.schedule = schedule; this.unschedule = unschedule; this.connected = false; this.sequence = 0;
    this.sessionId = `browser-${globalThis.crypto?.randomUUID?.() || Date.now()}`;
    this.scenario = 'planning'; this.current = null; this.acks = new Map(); this.timer = null; this.closed = false;
  }
  connect() { this.connected = true; queueMicrotask(() => { if (!this.closed) this.callbacks.open(); }); }
  emit(data) { if (!this.closed) this.callbacks.message(data); }
  clearTimer() { if (this.timer !== null) this.unschedule(this.timer); this.timer = null; }
  load(name = this.scenario) {
    this.clearTimer(); this.acks.clear(); this.selected = false;
    this.scenario = SCENARIOS.includes(name) ? name : this.scenario; this.sequence += 1;
    const fixture = clone(scenarios[this.scenario]);
    this.current = { type: 'session', session_id: this.sessionId, scenario: this.scenario, sequence: this.sequence,
      incoming: { ...fixture.incoming, id: `browser-incoming-${this.sequence}` }, options: fixture.options, generation: 'fixture' };
    this.emit(clone(this.current));
  }
  send(data) {
    if (!this.connected || this.closed) return false;
    if (!data || typeof data !== 'object') return false;
    if (['ready', 'load_scenario', 'reset'].includes(data.type)) {
      if (data.scenario !== undefined && !SCENARIOS.includes(data.scenario)) {
        this.emit({ type: 'error', code: 'invalid_scenario', message: 'Choose a supported scenario.' }); return true;
      }
      this.load(data.scenario); return true;
    }
    if (data.type === 'simulate') {
      this.clearTimer(); this.current = null;
      if (data.kind === 'generation_failure') this.emit({ type: 'status', state: 'error', fixture: true, message: 'Simulated generation failure. No reply committed.' });
      else if (data.kind === 'delay') {
        this.emit({ type: 'status', state: 'generating', fixture: true, message: 'Simulated response delay…' });
        this.timer = this.schedule(() => { this.timer = null; this.load(); }, this.delayMs);
      } else if (data.kind === 'recover') this.load();
      else this.emit({ type: 'error', code: 'invalid_simulation', message: 'Unsupported simulation.' });
      return true;
    }
    if (data.type === 'message-response') {
      const key = data.request_id;
      if (typeof key !== 'string' || key.length === 0 || key.length > 100 || !Number.isInteger(data.sequence)) {
        this.emit({ type: 'error', code: 'invalid_request', message: 'A bounded request ID and current sequence are required.' }); return true;
      }
      const current = this.current; const option = current?.options.find(x => x.id === data.option_id);
      if (!current || data.session_id !== current.session_id || data.sequence !== current.sequence || !option) {
        this.emit({ type: 'error', code: 'stale_selection', message: 'That choice is no longer current.', request_id: key }); return true;
      }
      if (this.acks.has(key)) {
        const prior = this.acks.get(key);
        if (prior.option_id === data.option_id) this.emit(clone(prior));
        else this.emit({ type: 'error', code: 'request_conflict', message: 'That request ID was already used for a different choice.', request_id: key });
        return true;
      }
      if (this.selected) { this.emit({ type: 'error', code: 'already_selected', message: 'This trial was already confirmed.', request_id: key }); return true; }
      const ack = { type: 'selection_ack', session_id: current.session_id, sequence: current.sequence,
        request_id: key, option_id: option.id, text: option.text, elapsed_ms: 0 };
      this.acks.set(key, ack); this.selected = true;
      if (this.acks.size > 100) this.acks.delete(this.acks.keys().next().value);
      queueMicrotask(() => this.emit(ack)); return true;
    }
    if (data.type === 'cancel') return true;
    return false;
  }
  close() { this.closed = true; this.connected = false; this.clearTimer(); }
}

export class SocketTransport {
  constructor(callbacks, url, { Socket = WebSocket, schedule = (...args) => globalThis.setTimeout(...args), unschedule = (...args) => globalThis.clearTimeout(...args) } = {}) {
    this.callbacks = callbacks; this.url = url; this.Socket = Socket;
    this.schedule = schedule; this.unschedule = unschedule; this.kind = 'python-websocket';
    this.socket = null; this.timer = null; this.closed = false; this.attempt = 0;
  }
  connect() {
    if (this.closed) return;
    this.socket = new this.Socket(this.url); const current = this.socket;
    current.onopen = () => { if (this.socket === current && !this.closed) { this.attempt = 0; this.callbacks.open(); } };
    current.onmessage = event => {
      if (this.socket !== current || this.closed) return;
      try { if (typeof event.data !== 'string' || event.data.length > 20000) return; this.callbacks.message(JSON.parse(event.data)); }
      catch { this.callbacks.protocolError?.(); }
    };
    current.onerror = () => { if (this.socket === current && !this.closed) current.close(); };
    current.onclose = () => {
      if (this.socket !== current || this.closed) return;
      this.callbacks.close(); const wait = Math.min(5000, 500 * 2 ** this.attempt++);
      this.timer = this.schedule(() => this.connect(), wait);
    };
  }
  send(data) {
    if (this.closed || !this.socket || this.socket.readyState !== 1) return false;
    try { this.socket.send(JSON.stringify(data)); return true; } catch { return false; }
  }
  close() {
    this.closed = true; if (this.timer !== null) this.unschedule(this.timer);
    const socket = this.socket; this.socket = null; if (socket) socket.close();
  }
}

export async function createTransport(callbacks) {
  const query = new URLSearchParams(location.search);
  if (location.protocol === 'file:' || query.get('standalone') === '1') return new BrowserFixtureTransport(callbacks);
  let port = 8000;
  try {
    const response = await fetch('/config.json', { cache: 'no-store', signal: AbortSignal.timeout(2000) });
    if (response.ok) { const config = await response.json(); if (Number.isInteger(config.ws_port) && config.ws_port > 0 && config.ws_port <= 65535) port = config.ws_port; }
  } catch { /* A Vite dev server can use the explicit default backend port. */ }
  const hostname = ['localhost', '127.0.0.1', '[::1]', '::1'].includes(location.hostname) ? location.hostname : null;
  if (!hostname) throw new Error('This recovery app expects a local host. Use the explicit standalone HTML for browser-only fixtures.');
  return new SocketTransport(callbacks, `ws://${hostname === '::1' ? '[::1]' : hostname}:${port}`);
}
