import test from 'node:test';
import assert from 'node:assert/strict';
import { BrowserFixtureTransport, SocketTransport } from '../src/recovery/transport.js';

const microtask = () => new Promise(resolve => queueMicrotask(resolve));
function fixture() {
  const messages = []; let opens = 0;
  const t = new BrowserFixtureTransport({ open: () => opens++, message: x => messages.push(x) });
  t.connect(); t.send({ type: 'ready', scenario: 'planning' });
  return { t, messages, opens: () => opens, session: () => messages.findLast(x => x.type === 'session') };
}
const request = (s, option = s.options[0].id, id = 'req-1') => ({ type: 'message-response', session_id: s.session_id, sequence: s.sequence, option_id: option, request_id: id });

test('standalone fixture is explicitly browser-only and opens with shared synthetic scenario', async () => {
  const f = fixture(); await microtask(); assert.equal(f.opens(), 1); assert.equal(f.t.kind, 'browser-fixtures');
  assert.equal(f.session().generation, 'fixture'); assert.equal(f.session().options.length, 4);
});
test('browser fixture gives exactly idempotent acknowledgement for the same request', async () => {
  const f = fixture(); const p = request(f.session()); f.t.send(p); await microtask(); f.t.send(p);
  const acks = f.messages.filter(x => x.type === 'selection_ack'); assert.equal(acks.length, 2); assert.deepEqual(acks[0], acks[1]);
});
test('same request ID cannot select a different option', async () => {
  const f = fixture(); const s = f.session(); f.t.send(request(s)); await microtask(); f.t.send(request(s, s.options[1].id));
  assert.equal(f.messages.at(-1).code, 'request_conflict');
});
test('a second request cannot commit a second choice within one trial', async () => {
  const f = fixture(); const s = f.session(); f.t.send(request(s)); await microtask(); f.t.send(request(s, s.options[1].id, 'req-2'));
  assert.equal(f.messages.at(-1).code, 'already_selected');
});
test('new scenario invalidates old selection requests and old ACK cache', async () => {
  const f = fixture(); const old = request(f.session()); f.t.send(old); await microtask(); f.t.send({ type: 'load_scenario', scenario: 'social' });
  const count = f.messages.filter(x => x.type === 'selection_ack').length; f.t.send(old);
  assert.equal(f.messages.at(-1).code, 'stale_selection'); assert.equal(f.messages.filter(x => x.type === 'selection_ack').length, count);
});
test('generation failure invalidates choices; recovery creates a new sequence', () => {
  const f = fixture(); const s = f.session(); f.t.send({ type: 'simulate', kind: 'generation_failure' });
  assert.equal(f.messages.at(-1).state, 'error'); f.t.send(request(s)); assert.equal(f.messages.at(-1).type, 'error');
  f.t.send({ type: 'simulate', kind: 'recover' }); assert.ok(f.session().sequence > s.sequence);
});
test('invalid scenario and request shapes are rejected without throwing', () => {
  const f = fixture(); assert.equal(f.t.send(null), false); f.t.send({ type: 'ready', scenario: 'unknown' }); assert.equal(f.messages.at(-1).code, 'invalid_scenario');
  f.t.send({ type: 'message-response', sequence: 1 }); assert.equal(f.messages.at(-1).code, 'invalid_request');
});
test('reset cancels a simulated delayed generation so it cannot replace the new trial', () => {
  const jobs = new Map(); let next = 0; const messages = [];
  const t = new BrowserFixtureTransport({ open() {}, message: x => messages.push(x) }, { schedule: fn => { jobs.set(++next, fn); return next; }, unschedule: id => jobs.delete(id) });
  t.connect(); t.send({ type: 'ready' }); t.send({ type: 'simulate', kind: 'delay' }); assert.equal(jobs.size, 1);
  t.send({ type: 'reset', scenario: 'logistics' }); assert.equal(jobs.size, 0); assert.equal(messages.at(-1).scenario, 'logistics');
});
test('closed browser fixture cannot emit or perform delayed actions', async () => {
  const f = fixture(); f.t.close(); const count = f.messages.length; await microtask();
  assert.equal(f.t.send({ type: 'reset' }), false); assert.equal(f.messages.length, count);
});
test('socket transport never queues requests while disconnected or resends after reconnect', () => {
  class Socket {
    constructor() { this.readyState = 0; this.sent = []; Socket.instances.push(this); }
    send(x) { this.sent.push(x); }
    close() { this.readyState = 3; this.onclose?.(); }
    static instances = [];
  }
  const jobs = []; let closed = 0; let opened = 0;
  const t = new SocketTransport({ open: () => opened++, close: () => closed++, message() {} }, 'ws://127.0.0.1:8000', { Socket, schedule: fn => { jobs.push(fn); return jobs.length; }, unschedule() {} });
  t.connect(); const first = Socket.instances[0]; assert.equal(t.send({ type: 'message-response' }), false);
  first.readyState = 1; first.onopen(); assert.equal(opened, 1); t.send({ type: 'ready' }); assert.equal(first.sent.length, 1);
  first.close(); assert.equal(closed, 1); assert.equal(t.send({ type: 'message-response' }), false);
  jobs.shift()(); const second = Socket.instances[1]; second.readyState = 1; second.onopen(); assert.equal(opened, 2); assert.equal(second.sent.length, 0);
  t.close();
});
test('old socket messages are ignored after a fresh connection replaces it', () => {
  class Socket { constructor() { this.readyState = 1; Socket.instances.push(this); } close() {} static instances = []; }
  const messages = []; const t = new SocketTransport({ open() {}, close() {}, message: x => messages.push(x) }, 'ws://127.0.0.1:8000', { Socket });
  t.connect(); const old = Socket.instances[0]; t.connect(); old.onmessage({ data: '{"type":"selection_ack"}' });
  assert.equal(messages.length, 0); t.close();
});
test('default browser timers keep the global receiver for delay, cleanup and reconnect', () => {
  const realSet = globalThis.setTimeout, realClear = globalThis.clearTimeout;
  const jobs = new Map(); let next = 0;
  globalThis.setTimeout = function (fn) {
    assert.equal(this, globalThis, 'native Window timer receiver must remain global');
    jobs.set(++next, fn); return next;
  };
  globalThis.clearTimeout = function (id) {
    assert.equal(this, globalThis, 'native Window clearTimeout receiver must remain global');
    jobs.delete(id);
  };
  try {
    const browser = new BrowserFixtureTransport({ open() {}, message() {} });
    browser.connect(); browser.send({ type: 'ready' }); browser.send({ type: 'simulate', kind: 'delay' });
    assert.equal(jobs.size, 1); browser.close(); assert.equal(jobs.size, 0);
    class Socket { constructor() { this.readyState = 1; } close() { this.readyState = 3; this.onclose?.(); } }
    const socket = new SocketTransport({ open() {}, close() {}, message() {} }, 'ws://127.0.0.1:8000', { Socket });
    socket.connect(); socket.socket.close(); assert.equal(jobs.size, 1); socket.close(); assert.equal(jobs.size, 0);
  } finally { globalThis.setTimeout = realSet; globalThis.clearTimeout = realClear; }
});
