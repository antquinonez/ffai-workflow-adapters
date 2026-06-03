"""Span helpers for adapter observability via FFAI's TelemetryManager."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Generator

_active_recorder: ContextVar[SpanRecorder | None] = ContextVar(
    "_active_recorder", default=None
)


class _NoOpSpan:
    """Fallback span when ffai.observability is unavailable."""

    def set_attribute(self, key: str, value: Any) -> None:
        pass

    def record_exception(self, exception: Exception) -> None:
        pass

    def is_recording(self) -> bool:
        return False


class _NoOpManager:
    """Fallback manager when ffai.observability import fails."""

    @contextmanager
    def span(self, name: str) -> Generator[_NoOpSpan, None, None]:
        yield _NoOpSpan()


_manager: Any | None = None


def _get_manager() -> Any:
    global _manager
    if _manager is not None:
        return _manager
    try:
        from ffai.observability import get_telemetry_manager

        _manager = get_telemetry_manager()
    except ImportError:
        _manager = _NoOpManager()
    return _manager


class _RecordedSpan:
    """Spy span that captures all events for test assertions."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.attributes: dict[str, Any] = {}
        self.exceptions: list[Exception] = []
        self._recording = True

    def set_attribute(self, key: str, value: Any) -> None:
        self.attributes[key] = value

    def record_exception(self, exception: Exception) -> None:
        self.exceptions.append(exception)

    def is_recording(self) -> bool:
        return self._recording


class SpanRecorder:
    """Collects _RecordedSpan instances for test assertions.

    Usage::

        recorder = SpanRecorder()
        with adapter_span("test", _recorder=recorder) as span:
            span.set_attribute("key", "value")

        assert recorder.spans[0].name == "ffai.adapters.test"
        assert recorder.spans[0].attributes["key"] == "value"
    """

    def __init__(self) -> None:
        self.spans: list[_RecordedSpan] = []

    @contextmanager
    def span(
        self, name: str, **attributes: Any
    ) -> Generator[_RecordedSpan, None, None]:
        recorded = _RecordedSpan(name)
        for k, v in attributes.items():
            recorded.set_attribute(k, v)
        self.spans.append(recorded)
        try:
            yield recorded
        except Exception as exc:
            recorded._recording = False
            recorded.record_exception(exc)
            raise


_SPAN_PREFIX = "ffai.adapters."


@contextmanager
def adapter_span(
    name: str,
    _recorder: SpanRecorder | None = None,
    **attributes: Any,
) -> Generator[Any, None, None]:
    """Create an observability span for an adapter operation.

    When OTEL is disabled (the default), yields a NoOpSpan with zero
    overhead. When enabled, yields a real OTEL span via FFAI's
    TelemetryManager.

    In tests, pass ``_recorder=SpanRecorder()`` to capture spans
    for assertions without OTEL installed.

    Args:
        name: Operation name (e.g. ``"airtable.load"``). Prefixed
            with ``"ffai.adapters."`` automatically.
        _recorder: Test spy to capture spans. None in production.
        **attributes: Span attributes set at creation time.
    """
    full_name = f"{_SPAN_PREFIX}{name}"

    if _recorder is not None:
        token = _active_recorder.set(_recorder)
        try:
            with _recorder.span(full_name, **attributes) as span:
                yield span
        finally:
            _active_recorder.reset(token)
        return

    active = _active_recorder.get()
    if active is not None:
        with active.span(full_name, **attributes) as span:
            yield span
        return

    manager = _get_manager()
    with manager.span(full_name) as span:
        for k, v in attributes.items():
            span.set_attribute(k, v)
        yield span
