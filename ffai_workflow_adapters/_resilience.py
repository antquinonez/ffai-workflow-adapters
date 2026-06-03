"""Resilience primitives for rate limiting, circuit breaking, and retry logic."""
from __future__ import annotations

import logging
import random
import threading
import time
from enum import Enum, auto
from typing import Any, Callable

from ffai.workflow.tabular import TabularLoadError

from ffai_workflow_adapters._spans import adapter_span

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    """States for the circuit breaker state machine."""

    CLOSED = auto()
    OPEN = auto()
    HALF_OPEN = auto()


class TokenBucket:
    """Token bucket rate limiter with thread-safe acquire.

    Tokens refill at a constant rate up to burst capacity. Blocks the
    calling thread when no tokens are available until one becomes
    available or the timeout expires.

    Args:
        rate: Tokens added per second.
        burst: Maximum token capacity (also the initial token count).
    """

    def __init__(self, rate: float, burst: int):
        self._rate = rate
        self._burst = burst
        self._tokens = float(burst)
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self, timeout: float = 30.0) -> None:
        """Block until a token is available or the timeout expires.

        Args:
            timeout: Maximum seconds to wait. Raises TabularLoadError
                if no token becomes available in time.

        Raises:
            TabularLoadError: If the acquire times out.
        """
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
    """Thread-safe circuit breaker with closed/open/half-open states.

    Allows calls while closed. After ``failure_threshold`` consecutive
    failures, transitions to open and rejects calls for
    ``recovery_timeout_seconds``. Then enters half-open, allowing a
    limited number of probe calls before deciding to close or re-open.

    Args:
        failure_threshold: Consecutive failures before opening.
        recovery_timeout_seconds: Seconds to wait in open state before
            transitioning to half-open.
        half_open_max_calls: Number of probe calls allowed in half-open
            state before deciding.
    """

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
        """Check whether a call is allowed under current breaker state.

        Transitions from open to half-open after the recovery timeout.
        Limits calls in half-open state to ``half_open_max_calls``.

        Returns:
            True if the call is allowed, False if rejected.
        """
        with self._lock:
            if self._state == CircuitState.CLOSED:
                return True
            if self._state == CircuitState.OPEN:
                if time.monotonic() - self._opened_at >= self._recovery_timeout:
                    logger.info(
                        "Circuit breaker: OPEN -> HALF_OPEN (recovery timeout elapsed)"
                    )
                    self._state = CircuitState.HALF_OPEN
                    self._half_open_calls = 1
                    return True
                return False
            if self._state == CircuitState.HALF_OPEN:
                if self._half_open_calls < self._half_open_max_calls:
                    self._half_open_calls += 1
                    return True
                logger.info(
                    "Circuit breaker: HALF_OPEN rejected (max probe calls=%d reached)",
                    self._half_open_max_calls,
                )
                return False
        assert False

    def record_success(self) -> None:
        """Record a successful call, closing the breaker if half-open."""
        with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                logger.info(
                    "Circuit breaker: HALF_OPEN -> CLOSED (probe succeeded)"
                )
                self._state = CircuitState.CLOSED
            self._failures = 0

    def record_failure(self) -> None:
        """Record a failed call, opening the breaker if threshold is reached."""
        with self._lock:
            self._failures += 1
            if self._state == CircuitState.HALF_OPEN:
                logger.info(
                    "Circuit breaker: HALF_OPEN -> OPEN (probe failed, failures=%d)",
                    self._failures,
                )
                self._state = CircuitState.OPEN
                self._opened_at = time.monotonic()
            elif self._failures >= self._failure_threshold:
                logger.info(
                    "Circuit breaker: CLOSED -> OPEN (failures=%d, threshold=%d)",
                    self._failures,
                    self._failure_threshold,
                )
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
    """Decorator that retries a function with exponential backoff.

    Only retries on exceptions that carry a ``response.status_code``
    matching one of ``retry_on_status_codes``. Other exceptions are
    re-raised immediately.

    Args:
        max_attempts: Maximum number of attempts including the first call.
        min_wait: Minimum wait in seconds between retries.
        max_wait: Maximum wait in seconds between retries.
        exponential_base: Base for exponential backoff calculation.
        jitter: If True, randomize wait time by +/- 50%.
        retry_on_status_codes: HTTP status codes that trigger a retry.

    Returns:
        A decorator that wraps the target function with retry logic.
    """
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
    """Compose rate limiting, circuit breaking, and retry into one caller.

    Thread-safe. Each call goes through: circuit breaker check, rate
    limit acquire, then retry-wrapped execution. Failures are recorded
    in the circuit breaker; successes reset the failure counter.

    Args:
        bucket: TokenBucket for rate limiting.
        breaker: CircuitBreaker for failure protection.
        retry_max_attempts: Maximum retry attempts per call.
        retry_min_wait: Minimum wait between retries in seconds.
        retry_max_wait: Maximum wait between retries in seconds.
        retry_exponential_base: Base for exponential backoff.
        retry_jitter: If True, randomize retry wait time.
        retry_on_status_codes: HTTP status codes that trigger retry.
        acquire_timeout: Maximum seconds to wait for a rate limit token.
    """

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
        """Execute ``fn`` through rate limiting, circuit breaking, and retry.

        Args:
            fn: Callable to execute.
            *args: Positional arguments forwarded to ``fn``.
            **kwargs: Keyword arguments forwarded to ``fn``.

        Returns:
            The return value of ``fn``.

        Raises:
            TabularLoadError: If the circuit breaker is open or rate
                limit acquire times out.
        """
        with adapter_span("resilience.call") as span:
            if not self._breaker.allow():
                span.set_attribute("circuit_breaker.state", "open")
                span.set_attribute("circuit_breaker.rejected", True)
                raise TabularLoadError("Circuit breaker is open")
            self._bucket.acquire(timeout=self._acquire_timeout)

            try:
                result = self._retry(fn, *args, **kwargs)
                span.set_attribute("call.success", True)
            except Exception:
                self._breaker.record_failure()
                span.set_attribute("call.success", False)
                span.set_attribute("circuit_breaker.failures", self._breaker.failures)
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
                with adapter_span("resilience.retry") as retry_span:
                    retry_span.set_attribute("attempt", attempt)
                    retry_span.set_attribute("max_attempts", self._retry_max_attempts)
                    retry_span.set_attribute("wait_seconds", round(wait, 2))
                    retry_span.record_exception(e)
                time.sleep(wait)
        raise last_exc


def batched(iterable: list[Any], size: int) -> Any:
    """Yield successive chunks of ``size`` from ``iterable``.

    Args:
        iterable: List to split into chunks.
        size: Maximum chunk size.

    Yields:
        Lists of at most ``size`` elements.
    """
    for i in range(0, len(iterable), size):
        yield iterable[i : i + size]
