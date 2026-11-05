#!/usr/bin/env python3
"""Experimental LOCAL camera adapter; no webcam accuracy is established here.

This module is never imported by the default demo. No dependency, model or image
is downloaded. The user must explicitly provide optional dependencies/model.
"""
from __future__ import annotations
import argparse
import asyncio
import importlib.util
import json
import math
from pathlib import Path
import sys
import time
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor'))
try:
    from .recovery_calibration import (CalibrationError, CoordinateSmoother, TargetCollector,
                                       fit_affine, validation_report)
except ImportError:
    from recovery_calibration import (CalibrationError, CoordinateSmoother, TargetCollector,
                                      fit_affine, validation_report)

TRAIN_TARGETS = tuple((x, y) for y in (.12, .5, .88) for x in (.12, .5, .88))
VALIDATION_TARGETS = ((.3, .3), (.7, .3), (.3, .7), (.7, .7))


def iris_features(landmarks):
    """Two averaged within-eye iris ratios; invalid/closed-eye samples return None.

    Landmark positions follow the recovered MediaPipe iris approach. This is a
    feature heuristic, not a validated gaze model or a head-motion correction.
    """
    if landmarks is None or len(landmarks) < 478:
        return None
    def xy(index):
        point = landmarks[index]
        return (float(point.x), float(point.y)) if hasattr(point, 'x') else (float(point[0]), float(point[1]))
    try:
        ratios = []
        for left, right, top, bottom, iris in (
            (33, 133, 159, 145, (469, 470, 471, 472)),
            (362, 263, 386, 374, (474, 475, 476, 477))):
            lx, _ = xy(left)
            rx, _ = xy(right)
            _, ty = xy(top)
            _, by = xy(bottom)
            width, height = rx - lx, by - ty
            if abs(width) < 1e-5 or abs(height) / abs(width) < .06:
                return None
            ix = sum(xy(i)[0] for i in iris) / len(iris)
            iy = sum(xy(i)[1] for i in iris) / len(iris)
            pair = ((ix - lx) / width, (iy - ty) / height)
            if any(not math.isfinite(v) or not -.2 <= v <= 1.2 for v in pair):
                return None
            ratios.append(pair)
        return tuple(sum(pair[i] for pair in ratios) / 2 for i in (0, 1))
    except (TypeError, ValueError, IndexError, AttributeError, ZeroDivisionError):
        return None


def check_environment(model: Path | None = None):
    return {'experimental': True, 'live_camera_tested': False,
            'dependencies': {name: importlib.util.find_spec(name) is not None for name in ('cv2', 'mediapipe', 'numpy', 'websockets')},
            'model_supplied': bool(model and model.is_file()),
            'automatic_downloads': False,
            'note': 'This check does not open a camera or prove model/platform compatibility.'}


def monotonic_ms(previous):
    """MediaPipe VIDEO calls require strictly increasing timestamps."""
    return max(previous + 1, time.monotonic_ns() // 1_000_000)


async def send_status(connection, state, message):
    await connection.send(json.dumps({'type': 'tracker_status', 'source': 'camera', 'state': state, 'message': message[:240]}))


async def send_point(connection, point):
    await connection.send(json.dumps({'type': 'tracker_coordinates', 'x': point[0] if point else 0,
                                      'y': point[1] if point else 0, 'valid': point is not None, 'source': 'camera'}))


async def camera_loop(args):
    # All heavyweight imports are explicit and delayed until this opt-in path.
    try:
        import cv2
        import mediapipe as mp
        import numpy as np
        from websockets.asyncio.client import connect
    except ImportError as exc:
        raise RuntimeError('Optional camera dependency missing. See requirements-camera.txt and docs/CAMERA_VALIDATION.txt.') from exc
    camera = cv2.VideoCapture(args.camera)
    if not camera.isOpened():
        camera.release()
        raise RuntimeError('Camera unavailable or permission denied. Default synthetic demo still works.')
    camera.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    options = mp.tasks.vision.FaceLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(model_asset_path=str(args.model.resolve())),
        running_mode=mp.tasks.vision.RunningMode.VIDEO,
        num_faces=1,
        min_face_detection_confidence=.6,
        min_face_presence_confidence=.6,
        min_tracking_confidence=.6)
    timestamp = -1
    window = 'Veltrah EXPERIMENTAL calibration - Space captures / Esc aborts'

    def capture_feature(landmarker):
        nonlocal timestamp
        ok, frame = camera.read()
        if not ok or frame is None:
            return None
        timestamp = monotonic_ms(timestamp)
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        result = landmarker.detect_for_video(image, timestamp)
        faces = result.face_landmarks
        return iris_features(faces[0]) if len(faces) == 1 else None

    async def collect_targets(landmarker, targets, label):
        collector = TargetCollector(targets, min_samples=args.samples,
                                    settle_seconds=.6, min_capture_seconds=.6)
        started_target = time.monotonic()
        last_index = -1
        while not collector.complete:
            now = time.monotonic()
            if collector.index != last_index:
                started_target, last_index = now, collector.index
            if now - started_target > 90:
                raise RuntimeError('Target capture timed out; no calibration was accepted.')
            point = collector.present(now)
            features = capture_feature(landmarker)
            if features is None and collector.phase == 'capturing':
                collector.retry()
                collector.present(time.monotonic())
            canvas = np.zeros((args.height, args.width, 3), dtype=np.uint8)
            marker = (int(point[0] * args.width), int(point[1] * args.height))
            cv2.circle(canvas, marker, 18, (60, 220, 210), 3)
            cv2.circle(canvas, marker, 3, (255, 255, 255), -1)
            progress = f'{label} {collector.index + 1}/{len(targets)} - {collector.phase}'
            instruction = 'Keep looking at the point. SPACE starts a multi-frame capture.'
            if features is None:
                instruction = 'No usable eyes/face. Adjust lighting/position. SPACE will not advance.'
            elif collector.phase == 'capturing':
                instruction = f'Capturing {len(collector.current)}/{args.samples}; keep head still.'
            cv2.putText(canvas, 'EXPERIMENTAL webcam mapping - not validated product gaze', (20, 34), cv2.FONT_HERSHEY_SIMPLEX, .65, (170, 170, 180), 1)
            cv2.putText(canvas, progress, (20, args.height - 66), cv2.FONT_HERSHEY_SIMPLEX, .6, (230, 230, 230), 1)
            cv2.putText(canvas, instruction, (20, args.height - 36), cv2.FONT_HERSHEY_SIMPLEX, .53, (150, 210, 210), 1)
            cv2.imshow(window, canvas)
            key = cv2.waitKey(1) & 0xff
            if key == 27:
                raise RuntimeError('Calibration cancelled by user.')
            if key == 32 and features is not None and collector.phase == 'settling':
                try:
                    collector.start_capture(time.monotonic())
                except CalibrationError:
                    pass  # Visible target must settle before capture is accepted.
            if collector.phase == 'capturing':
                collector.add(features, time.monotonic())
            await asyncio.sleep(0)  # Keep WebSocket ping/close handling alive during manual capture.
        return collector.samples

    try:
        with mp.tasks.vision.FaceLandmarker.create_from_options(options) as landmarker:
            async with connect(args.url, max_size=65536, open_timeout=5, proxy=None) as connection:
                await connection.send(json.dumps({'type': 'tracker_hello'}))
                ack = json.loads(await asyncio.wait_for(connection.recv(), timeout=5))
                if ack.get('type') != 'tracker_ack':
                    raise RuntimeError('Tracker handshake rejected by local server.')
                await send_status(connection, 'calibrating', 'Experimental camera calibration; gaze unavailable until held-out checks finish.')
                await send_point(connection, None)
                cv2.namedWindow(window, cv2.WINDOW_NORMAL)
                cv2.setWindowProperty(window, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
                training = await collect_targets(landmarker, TRAIN_TARGETS, 'Training')
                model = fit_affine(training)
                validation = await collect_targets(landmarker, VALIDATION_TARGETS, 'Held-out validation')
                report = validation_report(model, validation)
                print(json.dumps({'experimental_camera_calibration': report, 'training_rmse_normalized': model.training_rmse,
                                  'accuracy_claim': 'None. In-session held-out check only; needs independent physical task validation.'}))
                if report['rmse_normalized'] > args.max_validation_error or report['max_error_normalized'] > 2 * args.max_validation_error:
                    await send_status(connection, 'error', 'Held-out mapping error exceeds the configured experimental gate. No gaze sent.')
                    raise RuntimeError('Calibration rejected by held-out error gate. Recalibrate; do not use for actions.')
                cv2.destroyAllWindows()
                print('Focus the full-screen browser on the SAME display. Experimental tracking starts in 3 seconds. Ctrl+C stops it.')
                await send_status(connection, 'ready', 'Experimental mapping passed only the configured in-session check; real task accuracy remains unverified.')
                await asyncio.sleep(3)
                smoother = CoordinateSmoother()
                end = time.monotonic() + args.duration if args.duration else None
                previous_valid = None
                while end is None or time.monotonic() < end:
                    tick = time.monotonic()
                    features = capture_feature(landmarker)
                    point = model.tracked_point(features) if features is not None else None
                    point = smoother.update(point, time.monotonic())
                    await send_point(connection, point)
                    if (point is not None) != previous_valid:
                        previous_valid = point is not None
                        await send_status(connection, 'tracking' if point else 'lost',
                                          'Experimental camera coordinates.' if point else 'Face/eye sample lost or mapping extrapolated; pending dwell must cancel.')
                    await asyncio.sleep(max(0, 1 / args.fps - (time.monotonic() - tick)))
                await send_point(connection, None)
                await send_status(connection, 'stopped', 'Camera adapter stopped.')
    finally:
        camera.release()
        cv2.destroyAllWindows()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Check dependencies/model only; does not open a camera.')
    parser.add_argument('--model', type=Path, help='Existing local official face_landmarker.task file. No automatic download.')
    parser.add_argument('--url', default='ws://127.0.0.1:8000')
    parser.add_argument('--camera', type=int, default=0)
    parser.add_argument('--width', type=int, default=1280, help='Calibration canvas width; use same display/browser fullscreen.')
    parser.add_argument('--height', type=int, default=720)
    parser.add_argument('--samples', type=int, default=25)
    parser.add_argument('--fps', type=int, default=30)
    parser.add_argument('--duration', type=int, default=60, help='Tracking seconds after calibration; 0 continues until Ctrl+C.')
    parser.add_argument('--max-validation-error', type=float, default=.12,
                        help='Experimental normalized RMSE gate; not a proven acceptable product threshold.')
    args = parser.parse_args(argv)
    if args.check:
        print(json.dumps(check_environment(args.model)))
        return 0
    try:
        if args.model is None or not args.model.is_file():
            raise ValueError('Provide --model /path/to/face_landmarker.task. No model was downloaded; see docs/CAMERA_VALIDATION.txt.')
        url = urlparse(args.url)
        if url.scheme != 'ws' or url.hostname not in ('127.0.0.1', 'localhost', '::1') or url.username or url.password:
            raise ValueError('Camera adapter is restricted to loopback ws:// endpoints.')
        if not 640 <= args.width <= 7680 or not 480 <= args.height <= 4320:
            raise ValueError('Calibration canvas dimensions are outside supported bounds.')
        if not 10 <= args.samples <= 200 or not 5 <= args.fps <= 60 or not 0 <= args.duration <= 3600:
            raise ValueError('Invalid samples, fps or duration limit.')
        if not math.isfinite(args.max_validation_error) or not .01 <= args.max_validation_error <= .25:
            raise ValueError('Validation error gate must be finite between .01 and .25 normalized units.')
        asyncio.run(camera_loop(args))
    except KeyboardInterrupt:
        print('Experimental camera adapter stopped. The server marks the tracker disconnected/lost.')
        return 0
    except Exception as exc:
        parser.exit(2, f'Experimental camera unavailable ({type(exc).__name__}): {exc}\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
