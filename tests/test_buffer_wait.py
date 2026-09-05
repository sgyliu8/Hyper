import time
from types import SimpleNamespace

import pytest

from hyperlab.adapters.gentl import GenTLBackend


def test_buffer_wait_bounds_silence_and_does_not_swallow_transport_failure():
    backend = object.__new__(GenTLBackend)
    polls = []
    def silent(*, timeout):
        polls.append(timeout)
        return None
    backend.camera = SimpleNamespace(try_fetch=silent)
    start = time.monotonic()
    with pytest.raises(TimeoutError, match='fetch deadline'):
        backend._wait_for_buffer(.025)
    assert .025 <= time.monotonic()-start < .5
    assert polls and max(polls) <= .003

    def broken(*, timeout):
        raise RuntimeError('device disconnected')
    backend.camera.try_fetch = broken
    with pytest.raises(RuntimeError, match='device disconnected'):
        backend._wait_for_buffer(.025)


def test_buffer_after_empty_polls_is_returned_without_requeue_or_copy():
    backend = object.__new__(GenTLBackend)
    buffer = object()
    results = iter([None, None, buffer])
    backend.camera = SimpleNamespace(try_fetch=lambda **_: next(results))
    assert backend._wait_for_buffer(.25) is buffer
