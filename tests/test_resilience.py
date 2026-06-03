from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, patch

from typing import Any

import pytest

from ffai.workflow.tabular import TabularLoadError


class TestTokenBucket:
    def test_allows_burst_immediately(self) -> None:
        from ffai_workflow_adapters._resilience import TokenBucket

        bucket = TokenBucket(rate=1.0, burst=5)
        for _ in range(5):
            bucket.acquire(timeout=0.0)

    def test_rejects_when_empty(self) -> None:
        from ffai_workflow_adapters._resilience import TokenBucket

        bucket = TokenBucket(rate=1.0, burst=2)
        bucket.acquire(timeout=0.0)
        bucket.acquire(timeout=0.0)
        with pytest.raises(TabularLoadError, match="timed out"):
            bucket.acquire(timeout=0.0)

    def test_refills_over_time(self) -> None:
        from ffai_workflow_adapters._resilience import TokenBucket

        bucket = TokenBucket(rate=1000.0, burst=1)
        bucket.acquire(timeout=0.0)
        time.sleep(0.01)
        bucket.acquire(timeout=0.0)

    def test_thread_safety_stress(self) -> None:
        from ffai_workflow_adapters._resilience import TokenBucket

        bucket = TokenBucket(rate=1000.0, burst=50)
        acquired = []
        barrier = threading.Barrier(10)

        def worker():
            barrier.wait()
            try:
                bucket.acquire(timeout=5.0)
                acquired.append(1)
            except TabularLoadError:
                pass

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(acquired) >= 10


class TestCircuitBreaker:
    def test_starts_closed(self) -> None:
        from ffai_workflow_adapters._resilience import CircuitBreaker, CircuitState

        breaker = CircuitBreaker(failure_threshold=3, recovery_timeout_seconds=1.0)
        assert breaker.state == CircuitState.CLOSED
        assert breaker.allow() is True

    def test_transitions_to_open_after_threshold(self) -> None:
        from ffai_workflow_adapters._resilience import CircuitBreaker, CircuitState

        breaker = CircuitBreaker(failure_threshold=3, recovery_timeout_seconds=60.0)
        for _ in range(3):
            breaker.record_failure()
        assert breaker.state == CircuitState.OPEN
        assert breaker.allow() is False

    def test_transitions_to_half_open_after_timeout(self) -> None:
        from ffai_workflow_adapters._resilience import CircuitBreaker, CircuitState

        breaker = CircuitBreaker(failure_threshold=1, recovery_timeout_seconds=0.05)
        breaker.record_failure()
        assert breaker.state == CircuitState.OPEN
        time.sleep(0.1)
        assert breaker.allow() is True
        assert breaker.state == CircuitState.HALF_OPEN

    def test_half_open_success_resets_to_closed(self) -> None:
        from ffai_workflow_adapters._resilience import CircuitBreaker, CircuitState

        breaker = CircuitBreaker(failure_threshold=1, recovery_timeout_seconds=0.05)
        breaker.record_failure()
        time.sleep(0.1)
        breaker.allow()
        breaker.record_success()
        assert breaker.state == CircuitState.CLOSED
        assert breaker.failures == 0

    def test_half_open_failure_reopens(self) -> None:
        from ffai_workflow_adapters._resilience import CircuitBreaker, CircuitState

        breaker = CircuitBreaker(failure_threshold=1, recovery_timeout_seconds=0.05)
        breaker.record_failure()
        time.sleep(0.1)
        breaker.allow()
        breaker.record_failure()
        assert breaker.state == CircuitState.OPEN

    def test_half_open_respects_max_calls(self) -> None:
        from ffai_workflow_adapters._resilience import CircuitBreaker

        breaker = CircuitBreaker(
            failure_threshold=1, recovery_timeout_seconds=0.05, half_open_max_calls=2
        )
        breaker.record_failure()
        time.sleep(0.1)
        assert breaker.allow() is True
        assert breaker.allow() is True
        assert breaker.allow() is False

    def test_success_resets_failure_count(self) -> None:
        from ffai_workflow_adapters._resilience import CircuitBreaker

        breaker = CircuitBreaker(failure_threshold=5, recovery_timeout_seconds=60.0)
        for _ in range(4):
            breaker.record_failure()
        assert breaker.failures == 4
        breaker.record_success()
        assert breaker.failures == 0


class TestWithRetry:
    def _make_error(self, status_code: int) -> Exception:
        resp = MagicMock()
        resp.status_code = status_code
        exc: Any = Exception(f"HTTP {status_code}")
        exc.response = resp
        return exc

    def test_succeeds_on_first_attempt(self) -> None:
        from ffai_workflow_adapters._resilience import with_retry

        fn = MagicMock(return_value="ok")

        @with_retry(max_attempts=3, min_wait=0.01, jitter=False)
        def call():
            return fn()

        result = call()
        assert result == "ok"
        fn.assert_called_once()

    def test_retries_on_retryable_status(self) -> None:
        from ffai_workflow_adapters._resilience import with_retry

        fn = MagicMock(
            side_effect=[
                self._make_error(429),
                self._make_error(429),
                "ok",
            ]
        )

        @with_retry(max_attempts=3, min_wait=0.01, max_wait=0.01, exponential_base=1.0, jitter=False)
        def call():
            return fn()

        result = call()
        assert result == "ok"
        assert fn.call_count == 3

    def test_raises_after_max_attempts(self) -> None:
        from ffai_workflow_adapters._resilience import with_retry

        fn = MagicMock(side_effect=self._make_error(429))

        @with_retry(max_attempts=2, min_wait=0.01, max_wait=0.01, exponential_base=1.0, jitter=False)
        def call():
            return fn()

        with pytest.raises(Exception, match="HTTP 429"):
            call()
        assert fn.call_count == 2

    def test_does_not_retry_non_retryable_status(self) -> None:
        from ffai_workflow_adapters._resilience import with_retry

        fn = MagicMock(side_effect=self._make_error(400))

        @with_retry(max_attempts=3, min_wait=0.01, jitter=False)
        def call():
            return fn()

        with pytest.raises(Exception, match="HTTP 400"):
            call()
        fn.assert_called_once()

    def test_jitter_varies_wait(self) -> None:
        from ffai_workflow_adapters._resilience import with_retry

        waits: list[float] = []

        def mock_sleep(w: float) -> None:
            waits.append(w)

        fn = MagicMock(
            side_effect=[self._make_error(429), self._make_error(429), "ok"]
        )

        with patch("ffai_workflow_adapters._resilience.time.sleep", side_effect=mock_sleep):
            with patch("ffai_workflow_adapters._resilience.random.uniform", return_value=1.0):

                @with_retry(max_attempts=3, min_wait=1.0, max_wait=60.0, exponential_base=2.0, jitter=True)
                def call():
                    return fn()

                call()

        assert len(waits) == 2
        assert waits[0] > 0
        assert waits[1] > 0


class TestResilientCaller:
    def _make_error(self, status_code: int) -> Exception:
        resp = MagicMock()
        resp.status_code = status_code
        exc: Any = Exception(f"HTTP {status_code}")
        exc.response = resp
        return exc

    def test_happy_path(self) -> None:
        from ffai_workflow_adapters._resilience import CircuitBreaker, ResilientCaller, TokenBucket

        caller = ResilientCaller(
            bucket=TokenBucket(rate=100.0, burst=100),
            breaker=CircuitBreaker(failure_threshold=5, recovery_timeout_seconds=30.0),
            retry_max_attempts=1,
            acquire_timeout=5.0,
        )
        fn = MagicMock(return_value="result")
        result = caller.call(fn, "a", b=1)
        assert result == "result"
        fn.assert_called_once_with("a", b=1)

    def test_rejects_when_circuit_open(self) -> None:
        from ffai_workflow_adapters._resilience import CircuitBreaker, CircuitState, ResilientCaller, TokenBucket

        breaker = CircuitBreaker(failure_threshold=1, recovery_timeout_seconds=60.0)
        breaker.record_failure()
        assert breaker.state == CircuitState.OPEN

        caller = ResilientCaller(
            bucket=TokenBucket(rate=100.0, burst=100),
            breaker=breaker,
            retry_max_attempts=1,
            acquire_timeout=5.0,
        )
        fn = MagicMock(return_value="result")
        with pytest.raises(TabularLoadError, match="Circuit breaker is open"):
            caller.call(fn)
        fn.assert_not_called()

    def test_records_failure_on_exception(self) -> None:
        from ffai_workflow_adapters._resilience import CircuitBreaker, ResilientCaller, TokenBucket

        breaker = CircuitBreaker(failure_threshold=5, recovery_timeout_seconds=30.0)
        caller = ResilientCaller(
            bucket=TokenBucket(rate=100.0, burst=100),
            breaker=breaker,
            retry_max_attempts=1,
            retry_on_status_codes=[500],
            acquire_timeout=5.0,
        )
        fn = MagicMock(side_effect=self._make_error(500))
        with pytest.raises(Exception, match="HTTP 500"):
            caller.call(fn)
        assert breaker.failures == 1

    def test_records_success_on_happy_path(self) -> None:
        from ffai_workflow_adapters._resilience import CircuitBreaker, CircuitState, ResilientCaller, TokenBucket

        breaker = CircuitBreaker(failure_threshold=1, recovery_timeout_seconds=0.05)
        breaker.record_failure()
        time.sleep(0.1)
        breaker.allow()
        assert breaker.state == CircuitState.HALF_OPEN

        caller = ResilientCaller(
            bucket=TokenBucket(rate=100.0, burst=100),
            breaker=breaker,
            retry_max_attempts=1,
            acquire_timeout=5.0,
        )
        caller.call(MagicMock(return_value="ok"))
        assert breaker.state == CircuitState.CLOSED
        assert breaker.failures == 0

    def test_rate_limits(self) -> None:
        from ffai_workflow_adapters._resilience import CircuitBreaker, ResilientCaller, TokenBucket

        bucket = TokenBucket(rate=0.5, burst=1)
        caller = ResilientCaller(
            bucket=bucket,
            breaker=CircuitBreaker(failure_threshold=5, recovery_timeout_seconds=30.0),
            retry_max_attempts=1,
            acquire_timeout=0.1,
        )
        caller.call(MagicMock(return_value="ok"))
        with pytest.raises(TabularLoadError, match="timed out"):
            caller.call(MagicMock(return_value="ok"))


class TestBatched:
    def test_even_split(self) -> None:
        from ffai_workflow_adapters._resilience import batched

        chunks = list(batched([1, 2, 3, 4], 2))
        assert chunks == [[1, 2], [3, 4]]

    def test_uneven_split(self) -> None:
        from ffai_workflow_adapters._resilience import batched

        chunks = list(batched([1, 2, 3, 4, 5], 2))
        assert chunks == [[1, 2], [3, 4], [5]]

    def test_empty_list(self) -> None:
        from ffai_workflow_adapters._resilience import batched

        chunks = list(batched([], 10))
        assert chunks == []

    def test_size_larger_than_list(self) -> None:
        from ffai_workflow_adapters._resilience import batched

        chunks = list(batched([1, 2], 10))
        assert chunks == [[1, 2]]


class TestResilienceSpans:
    """Integration tests verifying L3 (resilience) spans work with L1 (_spans)."""

    def test_call_emits_success_span(self) -> None:
        from ffai_workflow_adapters._resilience import CircuitBreaker, ResilientCaller, TokenBucket
        from ffai_workflow_adapters._spans import SpanRecorder, adapter_span

        recorder = SpanRecorder()
        caller = ResilientCaller(
            bucket=TokenBucket(rate=100.0, burst=100),
            breaker=CircuitBreaker(failure_threshold=5),
            retry_max_attempts=1,
            acquire_timeout=5.0,
        )

        with adapter_span("test_parent", _recorder=recorder):
            caller.call(MagicMock(return_value="ok"))

        call_spans = [s for s in recorder.spans if s.name == "ffai.adapters.resilience.call"]
        assert len(call_spans) == 1
        assert call_spans[0].attributes["call.success"] is True

    def test_call_emits_failure_span_on_exception(self) -> None:
        from ffai_workflow_adapters._resilience import CircuitBreaker, ResilientCaller, TokenBucket
        from ffai_workflow_adapters._spans import SpanRecorder, adapter_span

        recorder = SpanRecorder()
        breaker = CircuitBreaker(failure_threshold=5)
        caller = ResilientCaller(
            bucket=TokenBucket(rate=100.0, burst=100),
            breaker=breaker,
            retry_max_attempts=1,
            acquire_timeout=5.0,
        )

        with pytest.raises(RuntimeError):
            with adapter_span("test_parent", _recorder=recorder):
                caller.call(MagicMock(side_effect=RuntimeError("boom")))

        call_spans = [s for s in recorder.spans if s.name == "ffai.adapters.resilience.call"]
        assert len(call_spans) == 1
        assert call_spans[0].attributes["call.success"] is False
        assert call_spans[0].attributes["circuit_breaker.failures"] == 1

    def test_circuit_breaker_rejection_emits_span(self) -> None:
        from ffai_workflow_adapters._resilience import CircuitBreaker, CircuitState, ResilientCaller, TokenBucket
        from ffai_workflow_adapters._spans import SpanRecorder, adapter_span

        recorder = SpanRecorder()
        breaker = CircuitBreaker(failure_threshold=1, recovery_timeout_seconds=300.0)
        breaker.record_failure()
        assert breaker.state == CircuitState.OPEN

        caller = ResilientCaller(
            bucket=TokenBucket(rate=100.0, burst=100),
            breaker=breaker,
            retry_max_attempts=1,
            acquire_timeout=5.0,
        )

        with pytest.raises(TabularLoadError, match="Circuit breaker is open"):
            with adapter_span("test_parent", _recorder=recorder):
                caller.call(MagicMock(return_value="ok"))

        call_spans = [s for s in recorder.spans if s.name == "ffai.adapters.resilience.call"]
        assert len(call_spans) == 1
        assert call_spans[0].attributes["circuit_breaker.state"] == "open"
        assert call_spans[0].attributes["circuit_breaker.rejected"] is True

    def test_retry_emits_retry_spans(self) -> None:
        from ffai_workflow_adapters._resilience import CircuitBreaker, ResilientCaller, TokenBucket
        from ffai_workflow_adapters._spans import SpanRecorder, adapter_span

        recorder = SpanRecorder()
        caller = ResilientCaller(
            bucket=TokenBucket(rate=100.0, burst=100),
            breaker=CircuitBreaker(failure_threshold=5),
            retry_max_attempts=3,
            retry_min_wait=0.01,
            retry_max_wait=0.01,
            retry_jitter=False,
            acquire_timeout=5.0,
        )

        error = Exception("retryable")
        error.response = MagicMock()
        error.response.status_code = 429

        with pytest.raises(Exception, match="retryable"):
            with adapter_span("test_parent", _recorder=recorder):
                caller.call(MagicMock(side_effect=error))

        retry_spans = [s for s in recorder.spans if s.name == "ffai.adapters.resilience.retry"]
        assert len(retry_spans) == 2
        assert retry_spans[0].attributes["attempt"] == 1
        assert retry_spans[0].attributes["max_attempts"] == 3
        assert retry_spans[1].attributes["attempt"] == 2
        assert len(retry_spans[0].exceptions) == 1

    def test_non_retryable_error_emits_no_retry_span(self) -> None:
        from ffai_workflow_adapters._resilience import CircuitBreaker, ResilientCaller, TokenBucket
        from ffai_workflow_adapters._spans import SpanRecorder, adapter_span

        recorder = SpanRecorder()
        caller = ResilientCaller(
            bucket=TokenBucket(rate=100.0, burst=100),
            breaker=CircuitBreaker(failure_threshold=5),
            retry_max_attempts=3,
            retry_min_wait=0.01,
            retry_max_wait=0.01,
            acquire_timeout=5.0,
        )

        error = Exception("bad request")
        error.response = MagicMock()
        error.response.status_code = 400

        with pytest.raises(Exception, match="bad request"):
            with adapter_span("test_parent", _recorder=recorder):
                caller.call(MagicMock(side_effect=error))

        retry_spans = [s for s in recorder.spans if s.name == "ffai.adapters.resilience.retry"]
        assert len(retry_spans) == 0

    def test_circuit_breaker_transitions_logged(self, caplog) -> None:
        import logging
        from ffai_workflow_adapters._resilience import CircuitBreaker

        breaker = CircuitBreaker(failure_threshold=2, recovery_timeout_seconds=0.05)

        with caplog.at_level(logging.INFO, logger="ffai_workflow_adapters._resilience"):
            breaker.record_failure()
            breaker.record_failure()

        assert any("CLOSED -> OPEN" in r.message for r in caplog.records)

        caplog.clear()
        time.sleep(0.1)

        with caplog.at_level(logging.INFO, logger="ffai_workflow_adapters._resilience"):
            breaker.allow()

        assert any("OPEN -> HALF_OPEN" in r.message for r in caplog.records)

        caplog.clear()

        with caplog.at_level(logging.INFO, logger="ffai_workflow_adapters._resilience"):
            breaker.record_success()

        assert any("HALF_OPEN -> CLOSED" in r.message for r in caplog.records)
