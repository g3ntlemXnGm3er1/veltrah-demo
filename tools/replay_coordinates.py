#!/usr/bin/env python3
"""Finite SYNTHETIC coordinate replay; never a live-camera or accuracy test."""
from __future__ import annotations
import argparse
import asyncio
import json
import math
from pathlib import Path
import sys
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor'))


def validate_trace(trace):
    if not isinstance(trace, list) or not 2 <= len(trace) <= 20000:
        raise ValueError('Trace must contain 2-20000 records.')
    previous = -1.0
    result = []
    for row in trace:
        if not isinstance(row, dict) or not isinstance(row.get('valid'), bool):
            raise ValueError('Each record needs time_ms and a boolean valid field.')
        t = row.get('time_ms')
        if isinstance(t, bool) or not isinstance(t, (int, float)) or not math.isfinite(t) or not 0 <= t <= 120000 or t < previous:
            raise ValueError('Trace times must be finite, sorted and within 0-120000 ms.')
        previous = t
        if row['valid']:
            for name in ('x', 'y'):
                value = row.get(name)
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
                    raise ValueError('Valid coordinates must be finite and normalized [0,1].')
        result.append({'time_ms': float(t), 'x': row.get('x', 0), 'y': row.get('y', 0), 'valid': row['valid']})
    if result[-1]['valid']:
        result.append({'time_ms': min(120000, previous + 1), 'x': 0, 'y': 0, 'valid': False})
    return result


def built_in_trace(x=.5, y=.5, hold_ms=1200, fps=30):
    records = [{'time_ms': i * 1000 / fps, 'x': x, 'y': y, 'valid': True}
               for i in range(max(2, math.ceil(hold_ms * fps / 1000)))]
    records.append({'time_ms': hold_ms, 'x': x, 'y': y, 'valid': True})
    return validate_trace(records)


async def replay(trace, url, repeat):
    try:
        from websockets.asyncio.client import connect
    except ImportError as exc:
        raise RuntimeError('websockets is missing; use the provided vendor copy or requirements-demo.txt.') from exc
    async with connect(url, max_size=65536, open_timeout=5, proxy=None) as connection:
        await connection.send(json.dumps({'type': 'tracker_hello'}))
        ack = json.loads(await asyncio.wait_for(connection.recv(), timeout=5))
        if ack.get('type') != 'tracker_ack':
            raise RuntimeError('Local server rejected tracker handshake.')
        for _ in range(repeat):
            start = asyncio.get_running_loop().time()
            for record in trace:
                delay = record['time_ms'] / 1000 - (asyncio.get_running_loop().time() - start)
                if delay > 0:
                    await asyncio.sleep(delay)
                await connection.send(json.dumps({'type': 'tracker_coordinates', 'x': record['x'], 'y': record['y'],
                                                  'valid': record['valid'], 'source': 'synthetic'}))
        await connection.send(json.dumps({'type': 'tracker_coordinates', 'x': 0, 'y': 0, 'valid': False, 'source': 'synthetic'}))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='ws://127.0.0.1:8000')
    parser.add_argument('--trace', type=Path, help='Local JSON list with time_ms, x, y, valid; max 2 MB.')
    parser.add_argument('--x', type=float, default=.5)
    parser.add_argument('--y', type=float, default=.5)
    parser.add_argument('--hold-ms', type=int, default=1200)
    parser.add_argument('--repeat', type=int, choices=range(1, 11), default=1)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(argv)
    try:
        url = urlparse(args.url)
        if url.scheme != 'ws' or url.hostname not in ('127.0.0.1', 'localhost', '::1') or url.username or url.password:
            raise ValueError('Replay is restricted to a loopback ws:// endpoint.')
        if not 100 <= args.hold_ms <= 120000:
            raise ValueError('--hold-ms must be between 100 and 120000.')
        if args.trace:
            if args.trace.stat().st_size > 2000000:
                raise ValueError('Trace exceeds 2 MB.')
            trace = validate_trace(json.loads(args.trace.read_text(encoding='utf-8')))
        else:
            trace = built_in_trace(args.x, args.y, args.hold_ms)
        print(json.dumps({'source': 'synthetic', 'frames_per_pass': len(trace), 'repeat': args.repeat,
                          'duration_ms_per_pass': trace[-1]['time_ms'], 'live_camera': False}))
        if not args.dry_run:
            asyncio.run(replay(trace, args.url, args.repeat))
    except Exception as exc:
        parser.exit(2, f'Replay unavailable ({type(exc).__name__}): {exc}\n')


if __name__ == '__main__':
    main()
