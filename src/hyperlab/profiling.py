"""Bounded host-stage duration observations; never an optical latency model."""
from collections import deque
from contextlib import contextmanager
from threading import Lock
from time import perf_counter_ns


class StageTimings:
    def __init__(self, capacity=240):
        if not isinstance(capacity, int) or isinstance(capacity, bool) or capacity < 1:
            raise ValueError('Timing capacity must be a positive integer')
        self.capacity = capacity
        self._samples = {}
        self._counts = {}
        self._exceptions = {}
        self._lock = Lock()

    def record(self, name, elapsed_ns, *, exception=False):
        with self._lock:
            self._samples.setdefault(name, deque(maxlen=self.capacity)).append(
                (int(elapsed_ns), perf_counter_ns(), bool(exception)))
            self._counts[name] = self._counts.get(name, 0) + 1
            self._exceptions[name] = self._exceptions.get(name, 0) + int(exception)

    @contextmanager
    def measure(self, name):
        started = perf_counter_ns()
        exception = False
        try:
            yield
        except BaseException:
            exception = True
            raise
        finally:
            self.record(name, perf_counter_ns() - started, exception=exception)

    def snapshot(self):
        with self._lock:
            samples = {name: list(values) for name, values in self._samples.items()}
            counts, exceptions = dict(self._counts), dict(self._exceptions)
        stages = {}
        for name, samples in samples.items():
            values = sorted(sample[0] / 1e6 for sample in samples)
            def percentile(fraction):
                position = (len(values) - 1) * fraction
                lower = int(position)
                upper = min(lower + 1, len(values) - 1)
                return values[lower] + (values[upper] - values[lower]) * (position - lower)
            stages[name] = {'n': len(values), 'total_count': counts[name],
                'min_ms': values[0], 'median_ms': percentile(.5),
                'p95_ms': percentile(.95), 'max_ms': values[-1],
                'sample_window_s': (samples[-1][1] - samples[0][1]) / 1e9,
                'latest_observation_ns': samples[-1][1],
                'exception_count': exceptions[name],
                'window_exception_count': sum(sample[2] for sample in samples)}
        return {'clock': 'host perf_counter_ns', 'capacity_per_stage': self.capacity,
            'scope': 'collector lifetime; latest bounded duration observations per stage',
            'interpretation': 'Host call durations, including exceptional calls; overlapping stages are not additive. '
                              'No exposure-to-screen latency or device-clock calibration.',
            'stages': stages}
