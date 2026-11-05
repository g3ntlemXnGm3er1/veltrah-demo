/** Dwell is driven by a clock, never by mouse-movement frequency. */
export class DwellTracker {
  constructor({ dwellMs = 700, staleMs = 450 } = {}) {
    this.dwellMs = dwellMs; this.staleMs = staleMs;
    this.target = null; this.enteredAt = null; this.blockedTarget = null; this.sessionKey = null;
  }
  cancel({ blockCurrent = true } = {}) {
    if (blockCurrent && this.target) this.blockedTarget = this.target;
    this.target = null; this.enteredAt = null;
  }
  reset() { this.target = null; this.enteredAt = null; this.blockedTarget = null; this.sessionKey = null; }
  tick({ target, now, valid = true, sampleAt = null, requireFresh = false, sessionKey }) {
    if (sessionKey !== this.sessionKey) { this.reset(); this.sessionKey = sessionKey; }
    if (!Number.isFinite(now)) return { progress: 0, selected: null };
    if (requireFresh && (!Number.isFinite(sampleAt) || now - sampleAt > this.staleMs || sampleAt > now + 50)) valid = false;
    if (!valid || !target) {
      this.target = null; this.enteredAt = null;
      // A real exit is required before the same stationary target can fire again.
      if (valid && !target) this.blockedTarget = null;
      return { progress: 0, selected: null };
    }
    if (target !== this.blockedTarget) this.blockedTarget = null;
    if (this.blockedTarget === target) return { progress: 0, selected: null };
    if (this.target !== target || this.enteredAt === null) { this.target = target; this.enteredAt = now; }
    const progress = Math.min(1, Math.max(0, (now - this.enteredAt) / this.dwellMs));
    if (progress >= 1) {
      this.blockedTarget = target; this.target = null; this.enteredAt = null;
      return { progress: 1, selected: target };
    }
    return { progress, selected: null };
  }
}

export function validSession(data) {
  return Boolean(data && typeof data.session_id === 'string' && data.session_id.length > 0 && data.session_id.length <= 100
    && Number.isInteger(data.sequence) && data.sequence >= 0
    && data.incoming && typeof data.incoming.from === 'string' && typeof data.incoming.text === 'string'
    && data.incoming.text.length <= 2000
    && Array.isArray(data.options) && data.options.length > 0 && data.options.length <= 8
    && data.options.every(x => x && typeof x === 'object' && typeof x.id === 'string' && x.id.length > 0 && x.id.length <= 100 && typeof x.text === 'string' && x.text.length <= 500)
    && new Set(data.options.map(x => x.id)).size === data.options.length);
}

/** One explicit, current-session commit in flight. Never queues or resends. */
export class SessionGuard {
  constructor(idFactory = () => globalThis.crypto?.randomUUID?.() || `req-${Date.now()}-${Math.random().toString(16).slice(2)}`) {
    this.idFactory = idFactory; this.connected = false; this.session = null; this.draft = null; this.pending = null; this.lastAccepted = null; this.lastSession = null;
  }
  setConnected(value) { this.connected = Boolean(value); if (!this.connected) this.invalidate(); }
  invalidate() { this.session = null; this.draft = null; this.pending = null; }
  setSession(session) {
    this.invalidate();
    if (!validSession(session)) return false;
    if (this.lastSession?.id === session.session_id && session.sequence <= this.lastSession.sequence) return false;
    this.lastSession = { id: session.session_id, sequence: session.sequence };
    this.session = session; return true;
  }
  select(id) {
    if (!this.connected || !this.session || this.pending || !this.session.options.some(x => x.id === id)) return false;
    this.draft = id; return true;
  }
  cancel() { this.draft = null; }
  beginCommit() {
    if (!this.connected || !this.session || !this.draft || this.pending) return null;
    const request = { type: 'message-response', option_id: this.draft, request_id: this.idFactory(), session_id: this.session.session_id, sequence: this.session.sequence };
    this.pending = request; this.draft = null; return request;
  }
  acceptAck(ack) {
    const p = this.pending;
    if (!this.connected || !this.session || !p || !ack || ack.request_id !== p.request_id || ack.session_id !== p.session_id
        || ack.option_id !== p.option_id || ack.sequence !== p.sequence) return false;
    this.lastAccepted = { ...ack }; this.pending = null; this.session = null;
    return true;
  }
  failRequest(requestId) {
    if (this.pending && (!requestId || requestId === this.pending.request_id)) { this.pending = null; this.draft = null; }
  }
}

const ALLOWED_DETAILS = new Set(['target_id', 'elapsed_ms', 'reason', 'status', 'code']);
export class MetricsLog {
  constructor(clock = () => performance.now()) { this.clock = clock; this.start = clock(); this.events = []; }
  record(event, context, details = {}) {
    const safe = Object.fromEntries(Object.entries(details).filter(([key, value]) => ALLOWED_DETAILS.has(key) && ['string', 'number', 'boolean'].includes(typeof value)));
    this.events.push({ time_ms: Math.round(this.clock() - this.start), event, mode: context.mode, scenario: context.scenario, transport: context.transport, ...safe });
    if (this.events.length > 2000) this.events.shift();
  }
  export(context) {
    return { schema: 'veltrah-local-metrics-v1', recorded_at: new Date().toISOString(), synthetic_conversation: true,
      transport: context.transport, contains_message_content: false, contains_raw_gaze: false,
      note: 'Local exploratory software session; not eye-tracker accuracy, user efficacy, SMS delivery or hardware validation.', events: this.events.slice() };
  }
}
