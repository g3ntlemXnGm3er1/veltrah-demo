"""Small, dependency-free calibration primitives for the recovery experiment.

These functions establish software behavior on synthetic inputs. They do not
establish webcam gaze accuracy. Coordinates are normalized viewport positions.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import statistics
from typing import Iterable, Sequence


class CalibrationError(ValueError):
    """The collected data cannot support the requested mapping."""


def finite_vector(values: Sequence[float], dimension: int | None = None) -> tuple[float, ...]:
    if not isinstance(values, (tuple, list)) or not 1 <= len(values) <= 8:
        raise CalibrationError("Expected 1-8 finite feature values.")
    if dimension is not None and len(values) != dimension:
        raise CalibrationError("Inconsistent feature dimension.")
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in values):
        raise CalibrationError("Non-finite or non-numeric input.")
    return tuple(float(v) for v in values)


def normalized_point(values: Sequence[float]) -> tuple[float, float]:
    point = finite_vector(values, 2)
    if any(not 0.0 <= v <= 1.0 for v in point):
        raise CalibrationError("Target must be within normalized [0,1] coordinates.")
    return point[0], point[1]


@dataclass(frozen=True)
class CalibrationSample:
    features: tuple[float, ...]
    target: tuple[float, float]


def _rank(matrix: list[list[float]], tolerance: float = 1e-9) -> int:
    work = [row[:] for row in matrix]
    if not work:
        return 0
    rows, cols, rank = len(work), len(work[0]), 0
    for column in range(cols):
        pivot = max(range(rank, rows), key=lambda row: abs(work[row][column]), default=None)
        if pivot is None or abs(work[pivot][column]) <= tolerance:
            continue
        work[rank], work[pivot] = work[pivot], work[rank]
        scale = work[rank][column]
        for c in range(column, cols):
            work[rank][c] /= scale
        for row in range(rank + 1, rows):
            factor = work[row][column]
            for c in range(column, cols):
                work[row][c] -= factor * work[rank][c]
        rank += 1
        if rank == rows:
            break
    return rank


def _solve(matrix: list[list[float]], output: list[float]) -> tuple[float, ...]:
    n = len(output)
    rows = [matrix[i][:] + [output[i]] for i in range(n)]
    for column in range(n):
        pivot = max(range(column, n), key=lambda row: abs(rows[row][column]))
        if abs(rows[pivot][column]) < 1e-12:
            raise CalibrationError("Singular calibration matrix.")
        rows[column], rows[pivot] = rows[pivot], rows[column]
        scale = rows[column][column]
        rows[column] = [v / scale for v in rows[column]]
        for row in range(n):
            if row != column:
                scale = rows[row][column]
                rows[row] = [a - scale * b for a, b in zip(rows[row], rows[column])]
    return tuple(rows[i][-1] for i in range(n))


@dataclass(frozen=True)
class AffineCalibration:
    means: tuple[float, ...]
    scales: tuple[float, ...]
    x_weights: tuple[float, ...]
    y_weights: tuple[float, ...]
    training_rmse: float
    sample_count: int
    target_count: int

    def predict(self, features: Sequence[float], *, clip: bool = True) -> tuple[float, float]:
        features = finite_vector(features, len(self.means))
        row = (1.0,) + tuple((x - mean) / scale for x, mean, scale in zip(features, self.means, self.scales))
        prediction = (sum(a * b for a, b in zip(row, self.x_weights)),
                      sum(a * b for a, b in zip(row, self.y_weights)))
        if not all(math.isfinite(v) for v in prediction):
            raise CalibrationError("Non-finite predicted position.")
        return tuple(max(0.0, min(1.0, v)) for v in prediction) if clip else prediction

    def tracked_point(self, features: Sequence[float], margin: float = 0.15) -> tuple[float, float] | None:
        """Reject distant extrapolation rather than pinning lost gaze to an edge."""
        x, y = self.predict(features, clip=False)
        if not -margin <= x <= 1.0 + margin or not -margin <= y <= 1.0 + margin:
            return None
        return max(0.0, min(1.0, x)), max(0.0, min(1.0, y))


def fit_affine(samples: Iterable[CalibrationSample], *, ridge: float = 1e-6,
               min_feature_span: float = 0.015) -> AffineCalibration:
    records = list(samples)
    if len(records) < 6:
        raise CalibrationError("At least six calibration samples are required.")
    if not math.isfinite(ridge) or not 0.0 < ridge <= 1.0:
        raise CalibrationError("Regularization must be finite and greater than zero.")
    if not math.isfinite(min_feature_span) or min_feature_span <= 0:
        raise CalibrationError("Minimum feature span must be finite and positive.")
    dimension = len(finite_vector(records[0].features))
    features = [finite_vector(s.features, dimension) for s in records]
    targets = [normalized_point(s.target) for s in records]
    target_count = len(set(targets))
    if target_count < max(3, dimension + 1):
        raise CalibrationError("Too few distinct targets for the feature dimension.")
    if any(max(p[i] for p in targets) - min(p[i] for p in targets) < 0.5 for i in (0, 1)):
        raise CalibrationError("Targets must cover both screen axes.")
    if any(max(f[i] for f in features) - min(f[i] for f in features) < min_feature_span for i in range(dimension)):
        raise CalibrationError("Features do not vary sufficiently across targets.")
    means = tuple(statistics.fmean(f[i] for f in features) for i in range(dimension))
    scales = tuple(statistics.pstdev(f[i] for f in features) for i in range(dimension))
    rows = [[1.0] + [(f[i] - means[i]) / scales[i] for i in range(dimension)] for f in features]
    n = dimension + 1
    if _rank(rows) != n:
        raise CalibrationError("Features are rank deficient; recollect calibration.")
    gram = [[sum(row[a] * row[b] for row in rows) for b in range(n)] for a in range(n)]
    for i in range(1, n):
        gram[i][i] += ridge  # Do not regularize the intercept.
    weights = []
    for axis in (0, 1):
        rhs = [sum(row[j] * target[axis] for row, target in zip(rows, targets)) for j in range(n)]
        weights.append(_solve(gram, rhs))
    squared = [sum((sum(row[j] * weights[a][j] for j in range(n)) - target[a]) ** 2
                   for a in (0, 1)) for row, target in zip(rows, targets)]
    return AffineCalibration(means, scales, weights[0], weights[1],
                             math.sqrt(statistics.fmean(squared)), len(records), target_count)


def validation_report(model: AffineCalibration, held_out: Iterable[CalibrationSample]) -> dict:
    """Evaluate separate samples without clipping errors to the screen boundary."""
    samples = list(held_out)
    if len(samples) < 4 or len({tuple(s.target) for s in samples}) < 4:
        raise CalibrationError("Use at least four distinct held-out validation targets.")
    distances = []
    for s in samples:
        prediction = model.predict(s.features, clip=False)
        target = normalized_point(s.target)
        distances.append(math.dist(prediction, target))
    return {"samples": len(samples), "targets": len({tuple(s.target) for s in samples}),
            "rmse_normalized": math.sqrt(statistics.fmean(d * d for d in distances)),
            "mean_error_normalized": statistics.fmean(distances),
            "max_error_normalized": max(distances),
            "unit": "Euclidean distance in normalized screen coordinates; not degrees of visual angle"}


class TargetCollector:
    """Requires target presentation, settling, deliberate capture and multiple frames."""
    def __init__(self, targets: Sequence[Sequence[float]], *, min_samples: int = 20,
                 settle_seconds: float = 0.5, min_capture_seconds: float = 0.35):
        self.targets = tuple(normalized_point(p) for p in targets)
        if len(self.targets) < 3 or min_samples < 3:
            raise CalibrationError("Need at least three targets and three samples per target.")
        if any(not math.isfinite(t) or t < 0 for t in (settle_seconds, min_capture_seconds)):
            raise CalibrationError("Durations must be finite and nonnegative.")
        self.min_samples, self.settle_seconds = min_samples, settle_seconds
        self.min_capture_seconds = min_capture_seconds
        self.index, self.phase = 0, "unpresented"
        self.presented_at = self.capture_at = self.last_time = None
        self.current: list[CalibrationSample] = []
        self.samples: list[CalibrationSample] = []
        self.dimension = None

    @property
    def complete(self) -> bool:
        return self.index >= len(self.targets)

    def present(self, now: float) -> tuple[float, float]:
        if self.complete:
            raise CalibrationError("Calibration already complete.")
        if self.phase != "unpresented":
            return self.targets[self.index]
        if not math.isfinite(now):
            raise CalibrationError("Invalid timestamp.")
        self.presented_at, self.phase = now, "settling"
        return self.targets[self.index]

    def start_capture(self, now: float) -> None:
        if not math.isfinite(now) or self.phase != "settling" or now - self.presented_at < self.settle_seconds:
            raise CalibrationError("Present the target and wait before confirming capture.")
        self.phase, self.capture_at, self.last_time = "capturing", now, None

    def add(self, features: Sequence[float] | None, now: float) -> bool:
        if self.phase != "capturing" or features is None:
            return False
        if not math.isfinite(now) or now < self.capture_at or (self.last_time is not None and now <= self.last_time):
            return False
        try:
            vector = finite_vector(features, self.dimension)
        except CalibrationError:
            return False
        if self.dimension is None:
            self.dimension = len(vector)
        self.last_time = now
        self.current.append(CalibrationSample(vector, self.targets[self.index]))
        if len(self.current) >= self.min_samples and now - self.capture_at >= self.min_capture_seconds:
            self.samples.extend(self.current)
            self.current = []
            self.index += 1
            self.phase = "complete" if self.complete else "unpresented"
            self.presented_at = self.capture_at = self.last_time = None
            return True
        return False

    def retry(self) -> None:
        """Lost face must not quietly advance or mix target samples."""
        if self.complete:
            return
        self.current = []
        self.phase = "unpresented"
        self.presented_at = self.capture_at = self.last_time = None


class CoordinateSmoother:
    """Time-based smoothing with safe duplicate timestamps and explicit loss reset."""
    def __init__(self, time_constant: float = 0.06, max_gap: float = 0.3):
        if time_constant <= 0 or max_gap <= 0:
            raise ValueError("Smoothing durations must be positive.")
        self.time_constant, self.max_gap = time_constant, max_gap
        self.previous = self.timestamp = None

    def update(self, point: Sequence[float] | None, now: float) -> tuple[float, float] | None:
        if point is None or not math.isfinite(now):
            self.previous = self.timestamp = None
            return None
        try:
            point = normalized_point(point)
        except CalibrationError:
            self.previous = self.timestamp = None
            return None
        if self.timestamp is not None and now <= self.timestamp:
            return self.previous
        if self.previous is None or now - self.timestamp > self.max_gap:
            self.previous, self.timestamp = point, now
            return point
        alpha = 1.0 - math.exp(-(now - self.timestamp) / self.time_constant)
        self.previous = tuple(a + alpha * (b - a) for a, b in zip(self.previous, point))
        self.timestamp = now
        return self.previous
