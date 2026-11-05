import test from 'node:test';
import assert from 'node:assert/strict';
import { DwellTracker, SessionGuard, MetricsLog, validSession } from '../src/recovery/interaction.js';

const session = (sequence = 1, id = 'session-a') => ({ type: 'session', session_id: id, sequence, scenario: 'planning',
  incoming: { from: 'Fixture', text: 'A synthetic question.' }, options: [{ id: 'one', text: 'First reply' }, { id: 'two', text: 'Second reply' }] });
const frame = (target, now, extra = {}) => ({ target, now, sessionKey: 'trial-1', ...extra });

test('stationary dwell completes from clock ticks without additional mouse movement', () => {
  const d = new DwellTracker({ dwellMs: 700 });
  assert.equal(d.tick(frame('one', 0)).selected, null);
  assert.equal(d.tick(frame('one', 699)).selected, null);
  assert.equal(d.tick(frame('one', 700)).selected, 'one');
  assert.equal(d.tick(frame('one', 1500)).selected, null);
});
test('moving to another target starts its own dwell, with no carryover', () => {
  const d = new DwellTracker(); d.tick(frame('one', 0));
  assert.equal(d.tick(frame('two', 600)).progress, 0);
  assert.equal(d.tick(frame('two', 1299)).selected, null);
  assert.equal(d.tick(frame('two', 1300)).selected, 'two');
});
test('a real exit cancels a partial dwell and reentry starts from zero', () => {
  const d = new DwellTracker(); d.tick(frame('one', 0)); d.tick(frame(null, 600));
  assert.equal(d.tick(frame('one', 650)).progress, 0);
  assert.equal(d.tick(frame('one', 1349)).selected, null);
  assert.equal(d.tick(frame('one', 1350)).selected, 'one');
});
test('cancel blocks repeat activation until an actual exit/reentry', () => {
  const d = new DwellTracker(); d.tick(frame('one', 0)); d.cancel();
  assert.equal(d.tick(frame('one', 2000)).selected, null);
  d.tick(frame(null, 2100)); d.tick(frame('one', 2200));
  assert.equal(d.tick(frame('one', 2900)).selected, 'one');
});
test('invalid/lost gaze resets partial dwell and never completes from stale samples', () => {
  const d = new DwellTracker(); d.tick(frame('one', 0, { sampleAt: 0, requireFresh: true }));
  assert.equal(d.tick(frame('one', 700, { sampleAt: 0, requireFresh: true })).selected, null);
  assert.equal(d.tick(frame('one', 750, { sampleAt: 750, requireFresh: true })).progress, 0);
  d.tick(frame('one', 1000, { valid: false, sampleAt: 1000, requireFresh: true }));
  assert.equal(d.tick(frame('one', 1500, { sampleAt: 1500, requireFresh: true })).selected, null);
});
test('future or missing camera timestamps cannot complete dwell', () => {
  const d = new DwellTracker();
  assert.equal(d.tick(frame('one', 100, { sampleAt: 1000, requireFresh: true })).progress, 0);
  assert.equal(d.tick(frame('one', 2000, { requireFresh: true })).selected, null);
});
test('session or mode change discards accumulated dwell', () => {
  const d = new DwellTracker(); d.tick(frame('one', 0));
  assert.equal(d.tick(frame('one', 650, { sessionKey: 'trial-2' })).progress, 0);
  assert.equal(d.tick(frame('one', 700, { sessionKey: 'trial-2' })).selected, null);
});
test('a non-finite clock cannot select', () => { const d = new DwellTracker(); assert.equal(d.tick(frame('one', NaN)).selected, null); });
test('invalid sessions including null options fail safely', () => {
  assert.equal(validSession(session()), true);
  for (const value of [null, {}, { ...session(), options: [null] }, { ...session(), options: [1] }, { ...session(), options: [session().options[0], session().options[0]] }, { ...session(), sequence: NaN }]) assert.equal(validSession(value), false);
});
test('a selection needs both a connection and a valid current session', () => {
  const g = new SessionGuard(); assert.equal(g.select('one'), false); g.setSession(session());
  assert.equal(g.select('one'), false); g.setConnected(true); assert.equal(g.select('missing'), false);
  assert.equal(g.select('one'), true);
});
test('draft selection cannot commit automatically; only explicit commit produces one request', () => {
  const g = new SessionGuard(() => 'req-1'); g.setConnected(true); g.setSession(session());
  assert.equal(g.beginCommit(), null); g.select('one'); assert.equal(g.pending, null);
  const p = g.beginCommit(); assert.equal(p.option_id, 'one'); assert.equal(p.request_id, 'req-1');
  assert.equal(g.beginCommit(), null); assert.equal(g.select('two'), false);
});
test('cancelled draft cannot be confirmed', () => {
  const g = new SessionGuard(); g.setConnected(true); g.setSession(session()); g.select('one'); g.cancel(); assert.equal(g.beginCommit(), null);
});
test('ACK must match every current request field and can be accepted only once', () => {
  const g = new SessionGuard(() => 'req-1'); g.setConnected(true); g.setSession(session()); g.select('one'); const p = g.beginCommit();
  for (const field of ['request_id', 'session_id', 'option_id', 'sequence']) assert.equal(g.acceptAck({ ...p, [field]: field === 'sequence' ? 20 : 'wrong' }), false);
  assert.equal(g.acceptAck({ ...p, text: 'First reply' }), true);
  assert.equal(g.acceptAck({ ...p, text: 'First reply' }), false);
  assert.equal(g.select('two'), false);
});
test('disconnect discards the draft and pending request; reconnect never resends it', () => {
  const g = new SessionGuard(() => 'req-1'); g.setConnected(true); g.setSession(session()); g.select('one'); const old = g.beginCommit();
  g.setConnected(false); assert.equal(g.pending, null); g.setConnected(true); g.setSession(session(1, 'new-connection'));
  assert.equal(g.acceptAck(old), false); assert.equal(g.beginCommit(), null);
});
test('new session or input-context invalidation discards pending ACK', () => {
  const g = new SessionGuard(() => 'req-1'); g.setConnected(true); g.setSession(session()); g.select('one'); const old = g.beginCommit();
  g.setSession(session(2)); assert.equal(g.acceptAck(old), false); g.select('two'); const current = g.beginCommit();
  g.invalidate(); assert.equal(g.acceptAck(current), false);
});
test('regressing or duplicate session sequence is rejected', () => {
  const g = new SessionGuard(); g.setConnected(true); assert.equal(g.setSession(session(2)), true);
  assert.equal(g.setSession(session(1)), false); assert.equal(g.setSession(session(2)), false); assert.equal(g.setSession(session(3)), true);
});
test('metrics export excludes message bodies, raw gaze and unapproved fields', () => {
  let now = 0; const log = new MetricsLog(() => now); now = 120;
  log.record('draft_selected', { mode: 'camera', scenario: 'planning', transport: 'python-websocket' }, { target_id: 'one', x: .5, y: .2, text: 'private message', raw_gaze: [1, 2], elapsed_ms: 120 });
  const exported = log.export({ transport: 'python-websocket' });
  assert.equal(exported.contains_message_content, false); assert.equal(exported.contains_raw_gaze, false);
  assert.equal(JSON.stringify(exported).includes('private message'), false); assert.equal('x' in exported.events[0], false); assert.equal(exported.events[0].elapsed_ms, 120);
});
