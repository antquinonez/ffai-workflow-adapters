from __future__ import annotations

import logging
import random
import threading
import time
from enum import Enum, auto
from typing import Any, Callable

from ffai.workflow.tabular import TabularLoadError

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    CLOSED = auto()
    OPEN = auto()
    HALF_OPEN = auto()


class TokenBucket:
    def __init__(self, rate: float, burst: int):
        self._rate = rate
        self._burst = burst
        self._tokens = float(burst)
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self, timeout: float = 30.0) -> None:
        deadline = time.monotonic() + timeout
        while True:
            with self._lock:
                now = time.monotonic()
                self._tokens = min(
                    self._burst,
                    self._tokens + (now - self._last) * self._rate,
                )
                self._last = now
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TabularLoadError("Rate limit acquire timed out")
            time.sleep(min(remaining, 0.1))


class CircuitBreaker:
    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout_seconds: float = 30.0,
        half_open_max_calls: int = 3,
    ):
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout_seconds
        self._half_open_max_calls = half_open_max_calls
        self._state = CircuitState.CLOSED
        self._failures = 0
        self._half_open_calls = 0
        self._opened_at: float = 0.0
        self._lock = threading.Lock()

    @property
    def state(self) -> CircuitState:
        with self._lock:
            return self._state

    @property
    def failures(self) -> int:
        with self._lock:
            return self._failures

    def allow(self) -> bool:
        with self._lock:
            if self._state == CircuitState.CLOSED:
                return True
            if self._state == CircuitState.OPEN:
                if time.monotonic() - self._opened_at >= self._recovery_timeout:
                    self._state = CircuitState.HALF_OPEN
                    self._half_open_calls = 1
                    return True
                return False
            if self._state == CircuitState.HALF_OPEN:
                if self._half_open_calls < self._half_open_max_calls:
                    self._half_open_calls += 1
                    return True
                return False
        assert False

    def record_success(self) -> None:
        with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.CLOSED
            self._failures = 0

    def record_failure(self) -> None:
        with self._lock:
            self._failures += 1
            if self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.OPEN
                self._opened_at = time.monotonic()
            elif self._failures >= self._failure_threshold:
                self._state = CircuitState.OPEN
                self._opened_at = time.monotonic()


def with_retry(
    max_attempts: int = 3,
    min_wait: float = 1.0,
    max_wait: float = 60.0,
    exponential_base: float = 2.0,
    jitter: bool = True,
    retry_on_status_codes: list[int] | None = None,
) -> Callable[..., Any]:
    codes = retry_on_status_codes if retry_on_status_codes is not None else [429, 503, 502, 504]

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exc: Exception = TabularLoadError("no attempts made")
            for attempt in range(1, max_attempts + 1):
                try:
                    return fn(*args, **kwargs)
                except Exception as e:
                    status: int | None = None
                    resp = getattr(e, "response", None)
                    if resp is not None:
                        status = getattr(resp, "status_code", None)
                    if status is not None and status not in codes:
                        raise
                    last_exc = e
                    if attempt == max_attempts:
                        raise
                    wait = min(
                        exponential_base**attempt * min_wait,
                        max_wait,
                    )
                    if jitter:
                        wait *= random.uniform(0.5, 1.5)
                    logger.warning(
                        "Attempt %d/%d failed (%s), retrying in %.1fs",
                        attempt,
                        max_attempts,
                        e,
                        wait,
                    )
                    time.sleep(wait)
            raise last_exc

        return wrapper

    return decorator


class ResilientCaller:
    def __init__(
        self,
        bucket: TokenBucket,
        breaker: CircuitBreaker,
        retry_max_attempts: int = 3,
        retry_min_wait: float = 1.0,
        retry_max_wait: float = 60.0,
        retry_exponential_base: float = 2.0,
        retry_jitter: bool = True,
        retry_on_status_codes: list[int] | None = None,
        acquire_timeout: float = 30.0,
    ):
        self._bucket = bucket
        self._breaker = breaker
        self._retry_max_attempts = retry_max_attempts
        self._retry_min_wait = retry_min_wait
        self._retry_max_wait = retry_max_wait
        self._retry_exponential_base = retry_exponential_base
        self._retry_jitter = retry_jitter
        self._retry_on_status_codes = (
            retry_on_status_codes if retry_on_status_codes is not None else [429, 503, 502, 504]
        )
        self._acquire_timeout = acquire_timeout

    def call(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        if not self._breaker.allow():
            raise TabularLoadError("Circuit breaker is open")
        self._bucket.acquire(timeout=self._acquire_timeout)

        try:
            result = self._retry(fn, *args, **kwargs)
        except Exception:
            self._breaker.record_failure()
            raise
        self._breaker.record_success()
        return result

    def _retry(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        last_exc: Exception = TabularLoadError("no attempts made")
        for attempt in range(1, self._retry_max_attempts + 1):
            try:
                return fn(*args, **kwargs)
            except Exception as e:
                status: int | None = None
                resp = getattr(e, "response", None)
                if resp is not None:
                    status = getattr(resp, "status_code", None)
                if status is not None and status not in self._retry_on_status_codes:
                    raise
                last_exc = e
                if attempt == self._retry_max_attempts:
                    raise
                wait = min(
                    self._retry_exponential_base**attempt * self._retry_min_wait,
                    self._retry_max_wait,
                )
                if self._retry_jitter:
                    wait *= random.uniform(0.5, 1.5)
                logger.warning(
                    "Attempt %d/%d failed (%s), retrying in %.1fs",
                    attempt,
                    self._retry_max_attempts,
                    e,
                    wait,
                )
                time.sleep(wait)
        raise last_exc


def batched(iterable: list[Any], size: int) -> Any:
    for i in range(0, len(iterable), size):
        yield iterable[i : i + size]
