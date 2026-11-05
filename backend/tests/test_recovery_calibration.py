import json
import asyncio
import importlib.util
import math
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
sys.path.insert(0, str(ROOT / 'vendor'))
from recovery_calibration import (AffineCalibration, CalibrationError, CalibrationSample,
                                  CoordinateSmoother, TargetCollector, fit_affine,
                                  validation_report)
from recovery_gaze import iris_features, monotonic_ms
import recovery_gaze

replay_spec = importlib.util.spec_from_file_location('coordinate_replay', ROOT / 'tools/replay_coordinates.py')
coordinate_replay = importlib.util.module_from_spec(replay_spec)
replay_spec.loader.exec_module(coordinate_replay)


def features_for(target):
    x, y = target
    return (0.25 + x * 0.4 + y * 0.03, 0.28 + y * 0.3 - x * 0.02)


def training_samples():
    return [CalibrationSample(features_for((x, y)), (x, y))
            for x in (0.1, 0.5, 0.9) for y in (0.1, 0.5, 0.9) for _ in range(4)]


class CalibrationTests(unittest.TestCase):
    def test_affine_intercept_and_independent_validation(self):
        model = fit_affine(training_samples())
        for p in ((0.3, 0.3), (0.7, 0.3), (0.3, 0.7), (0.7, 0.7)):
            result = model.predict(features_for(p), clip=False)
            self.assertLess(math.dist(result, p), 1e-6)
        held = [CalibrationSample(features_for(p), p)
                for p in ((0.3, 0.3), (0.7, 0.3), (0.3, 0.7), (0.7, 0.7))]
        self.assertLess(validation_report(model, held)['rmse_normalized'], 1e-6)

    def test_rank_deficient_and_nonvarying_features_rejected(self):
        samples = training_samples()
        with self.assertRaisesRegex(CalibrationError, 'rank deficient'):
            fit_affine([CalibrationSample((s.features[0], s.features[0]), s.target) for s in samples])
        with self.assertRaisesRegex(CalibrationError, 'vary sufficiently'):
            fit_affine([CalibrationSample((0.4, 0.4), s.target) for s in samples])

    def test_inadequate_coverage_invalid_numbers_and_dimensions(self):
        with self.assertRaises(CalibrationError):
            fit_affine(training_samples()[:4])
        with self.assertRaises(CalibrationError):
            fit_affine([CalibrationSample((x, y), (x / 10, y / 10)) for x in (.1, .5, .9) for y in (.1, .5, .9)])
        bad = training_samples()
        bad[0] = CalibrationSample((float('nan'), .4), (.1, .1))
        with self.assertRaises(CalibrationError):
            fit_affine(bad)
        bad[0] = CalibrationSample((.3, .4, .5), (.1, .1))
        with self.assertRaises(CalibrationError):
            fit_affine(bad)

    def test_validation_preserves_out_of_screen_error_and_requires_distinct_targets(self):
        model = fit_affine(training_samples())
        held = [CalibrationSample(features_for((p[0] + 2, p[1] + 2)), p)
                for p in ((.2, .2), (.8, .2), (.2, .8), (.8, .8))]
        self.assertGreater(validation_report(model, held)['rmse_normalized'], 2)
        self.assertIsNone(model.tracked_point(features_for((2, 2))))
        self.assertEqual(model.predict(features_for((2, 2))), (1.0, 1.0))
        with self.assertRaises(CalibrationError):
            validation_report(model, held[:3])
        with self.assertRaises(CalibrationError):
            validation_report(model, [held[0]] * 4)

    def test_each_target_requires_presentation_confirmation_and_multiple_frames(self):
        collector = TargetCollector(((.1, .1), (.9, .1), (.5, .9)), min_samples=3,
                                    settle_seconds=.5, min_capture_seconds=.3)
        self.assertFalse(collector.add((.4, .4), 0))
        with self.assertRaises(CalibrationError):
            collector.start_capture(.5)
        self.assertEqual(collector.present(0), (.1, .1))
        with self.assertRaises(CalibrationError):
            collector.start_capture(.49)
        collector.start_capture(.5)
        self.assertFalse(collector.add((.3, .4), .5))
        self.assertFalse(collector.add((.3, .4), .5))  # duplicate not another frame
        self.assertFalse(collector.add((float('nan'), .4), .6))
        self.assertFalse(collector.add((.3, .4), .65))
        self.assertTrue(collector.add((.3, .4), .81))
        self.assertEqual(collector.index, 1)
        self.assertFalse(collector.add((.8, .4), .9))  # next target not presented yet
        self.assertEqual(len(collector.samples), 3)

    def test_retry_drops_partial_target_and_loss_does_not_advance(self):
        collector = TargetCollector(((.1, .1), (.9, .1), (.5, .9)), min_samples=3)
        collector.present(0)
        collector.start_capture(.6)
        collector.add((.4, .4), .6)
        self.assertFalse(collector.add(None, .8))
        collector.retry()
        self.assertEqual(collector.index, 0)
        self.assertEqual(collector.current, [])
        self.assertEqual(collector.samples, [])
        with self.assertRaises(CalibrationError):
            collector.start_capture(1)

    def test_smoothing_duplicate_reversed_time_loss_and_long_gap(self):
        smoother = CoordinateSmoother()
        self.assertEqual(smoother.update((.1, .2), 1), (.1, .2))
        self.assertEqual(smoother.update((.9, .9), 1), (.1, .2))
        self.assertEqual(smoother.update((.9, .9), .9), (.1, .2))
        p = smoother.update((.9, .9), 1.1)
        self.assertTrue(.1 < p[0] < .9)
        self.assertIsNone(smoother.update(None, 1.2))
        self.assertEqual(smoother.update((.9, .9), 1.3), (.9, .9))
        self.assertIsNone(smoother.update((2, .1), 1.4))
        self.assertEqual(smoother.update((.1, .1), 2), (.1, .1))
        self.assertEqual(smoother.update((.7, .8), 3), (.7, .8))

    def test_feature_extraction_rejects_lost_closed_eyes_and_invalid_landmarks(self):
        self.assertIsNone(iris_features(None))
        self.assertIsNone(iris_features([]))
        landmarks = [[.5, .5] for _ in range(478)]
        for left, right, top, bottom, iris in ((33, 133, 159, 145, (469, 470, 471, 472)),
                                             (362, 263, 386, 374, (474, 475, 476, 477))):
            landmarks[left] = [.3, .5]
            landmarks[right] = [.5, .5]
            landmarks[top] = [.4, .48]
            landmarks[bottom] = [.4, .52]
            for index in iris:
                landmarks[index] = [.4, .5]
        pair = iris_features(landmarks)
        self.assertAlmostEqual(pair[0], .5)
        self.assertAlmostEqual(pair[1], .5)
        landmarks[145] = [.4, .4801]
        self.assertIsNone(iris_features(landmarks))
        landmarks[145] = [.4, .52]
        landmarks[469] = [float('nan'), .5]
        self.assertIsNone(iris_features(landmarks))

    def test_mediapipe_timestamps_are_strictly_increasing(self):
        previous = 10 ** 20
        self.assertEqual(monotonic_ms(previous), previous + 1)

    def test_replay_validation_finishes_with_loss_and_rejects_bad_data(self):
        trace = coordinate_replay.built_in_trace(.2, .3, 1200)
        self.assertFalse(trace[-1]['valid'])
        self.assertGreaterEqual(trace[-1]['time_ms'], 1200)
        with self.assertRaises(ValueError):
            coordinate_replay.validate_trace([{'time_ms': 0, 'valid': True, 'x': 2, 'y': .5},
                                             {'time_ms': 10, 'valid': False}])
        with self.assertRaises(ValueError):
            coordinate_replay.validate_trace([{'time_ms': 20, 'valid': False},
                                             {'time_ms': 10, 'valid': False}])
        with self.assertRaises(ValueError):
            coordinate_replay.validate_trace([{'time_ms': float('nan'), 'valid': False},
                                             {'time_ms': 10, 'valid': False}])

    def test_cli_checks_do_not_open_camera_or_require_model(self):
        check = subprocess.run([sys.executable, str(ROOT / 'backend/recovery_gaze.py'), '--check'],
                               capture_output=True, text=True, check=True, timeout=10)
        result = json.loads(check.stdout)
        self.assertFalse(result['live_camera_tested'])
        self.assertFalse(result['automatic_downloads'])
        missing = subprocess.run([sys.executable, str(ROOT / 'backend/recovery_gaze.py')],
                                 capture_output=True, text=True, timeout=10)
        self.assertEqual(missing.returncode, 2)
        self.assertIn('Provide --model', missing.stderr)
        self.assertNotIn('Traceback', missing.stderr)
        dry = subprocess.run([sys.executable, str(ROOT / 'tools/replay_coordinates.py'), '--dry-run'],
                             capture_output=True, text=True, check=True, timeout=10)
        self.assertEqual(json.loads(dry.stdout)['source'], 'synthetic')

    def test_replay_transport_declares_synthetic_and_ends_with_loss(self):
        async def exercise():
            from websockets.asyncio.server import serve
            from websockets.asyncio.client import connect as real_connect
            received = []
            calls = []
            def direct_connect(*args, **kwargs):
                calls.append(kwargs)
                return real_connect(*args, **kwargs)
            async def handler(connection):
                hello = json.loads(await connection.recv())
                self.assertEqual(hello, {'type': 'tracker_hello'})
                await connection.send(json.dumps({'type': 'tracker_ack'}))
                async for frame in connection:
                    received.append(json.loads(frame))
            async with serve(handler, '127.0.0.1', 0) as server:
                port = server.sockets[0].getsockname()[1]
                with mock.patch('websockets.asyncio.client.connect', side_effect=direct_connect):
                    await coordinate_replay.replay(coordinate_replay.built_in_trace(.4, .6, 100),
                                                   f'ws://127.0.0.1:{port}', 1)
                await asyncio.sleep(.02)
            self.assertGreater(len(received), 2)
            self.assertTrue(all(p['source'] == 'synthetic' for p in received))
            self.assertFalse(received[-1]['valid'])
            self.assertTrue(calls)
            self.assertTrue(all(call.get('proxy', 'absent') is None for call in calls))
        asyncio.run(exercise())

    def test_camera_connection_disables_environment_proxy_without_camera_or_network(self):
        class StopBeforeConnection(RuntimeError):
            pass
        camera = mock.Mock()
        camera.isOpened.return_value = True
        cv2 = SimpleNamespace(VideoCapture=mock.Mock(return_value=camera),
                              CAP_PROP_FRAME_WIDTH=1, CAP_PROP_FRAME_HEIGHT=2,
                              destroyAllWindows=mock.Mock())
        context = mock.MagicMock()
        context.__enter__.return_value = object()
        vision = SimpleNamespace(FaceLandmarkerOptions=mock.Mock(return_value=object()),
                                 RunningMode=SimpleNamespace(VIDEO='video'),
                                 FaceLandmarker=SimpleNamespace(create_from_options=mock.Mock(return_value=context)))
        mp = SimpleNamespace(tasks=SimpleNamespace(BaseOptions=mock.Mock(return_value=object()), vision=vision))
        args = SimpleNamespace(camera=0, model=ROOT / 'not-opened.task', url='ws://127.0.0.1:8000')
        # Native camera/vision modules and the socket constructor are mocked;
        # no actual camera, model inference or external connection is possible.
        with mock.patch.dict(sys.modules, {'cv2': cv2, 'mediapipe': mp, 'numpy': object()}):
            with mock.patch('websockets.asyncio.client.connect', side_effect=StopBeforeConnection) as connection:
                with self.assertRaises(StopBeforeConnection):
                    asyncio.run(recovery_gaze.camera_loop(args))
        self.assertIs(connection.call_args.kwargs.get('proxy', 'absent'), None)
        camera.release.assert_called_once()
        cv2.destroyAllWindows.assert_called_once()


if __name__ == '__main__':
    unittest.main()
