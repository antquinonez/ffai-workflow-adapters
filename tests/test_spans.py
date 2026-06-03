"""Tests for _spans.py — adapter span helpers and SpanRecorder."""
from __future__ import annotations

import pytest

from ffai_workflow_adapters._spans import (
    SpanRecorder,
    _NoOpManager,
    _NoOpSpan,
    _RecordedSpan,
    _SPAN_PREFIX,
    adapter_span,
)


class TestRecordedSpan:
    def test_stores_attributes(self):
        span = _RecordedSpan("test")
        span.set_attribute("key", "value")
        span.set_attribute("count", 42)
        assert span.attributes == {"key": "value", "count": 42}

    def test_overwrites_attribute(self):
        span = _RecordedSpan("test")
        span.set_attribute("key", "old")
        span.set_attribute("key", "new")
        assert span.attributes["key"] == "new"

    def test_stores_exceptions(self):
        span = _RecordedSpan("test")
        exc = ValueError("boom")
        span.record_exception(exc)
        assert span.exceptions == [exc]

    def test_stores_multiple_exceptions(self):
        span = _RecordedSpan("test")
        e1 = ValueError("a")
        e2 = RuntimeError("b")
        span.record_exception(e1)
        span.record_exception(e2)
        assert span.exceptions == [e1, e2]

    def test_is_recording_default_true(self):
        assert _RecordedSpan("test").is_recording() is True

    def test_is_recording_false_after_set(self):
        span = _RecordedSpan("test")
        span._recording = False
        assert span.is_recording() is False


class TestNoOpSpan:
    def test_set_attribute_does_nothing(self):
        span = _NoOpSpan()
        span.set_attribute("key", "value")

    def test_record_exception_does_nothing(self):
        span = _NoOpSpan()
        span.record_exception(ValueError("boom"))

    def test_is_recording_false(self):
        assert _NoOpSpan().is_recording() is False


class TestNoOpManager:
    def test_span_yields_noop_span(self):
        manager = _NoOpManager()
        with manager.span("test") as span:
            assert isinstance(span, _NoOpSpan)


class TestSpanRecorder:
    def test_captures_single_span(self):
        recorder = SpanRecorder()
        with recorder.span("ffai.adapters.airtable.load") as span:
            span.set_attribute("base_id", "app123")

        assert len(recorder.spans) == 1
        assert recorder.spans[0].name == "ffai.adapters.airtable.load"
        assert recorder.spans[0].attributes["base_id"] == "app123"

    def test_captures_initial_attributes(self):
        recorder = SpanRecorder()
        with recorder.span("test", base_id="app123", table="Steps") as span:
            pass

        assert recorder.spans[0].attributes == {
            "base_id": "app123",
            "table": "Steps",
        }

    def test_captures_multiple_spans(self):
        recorder = SpanRecorder()
        with recorder.span("first"):
            pass
        with recorder.span("second"):
            pass

        assert len(recorder.spans) == 2
        assert recorder.spans[0].name == "first"
        assert recorder.spans[1].name == "second"

    def test_records_exception_on_failure(self):
        recorder = SpanRecorder()
        with pytest.raises(ValueError, match="boom"):
            with recorder.span("test") as span:
                raise ValueError("boom")

        assert len(recorder.spans[0].exceptions) == 1
        assert isinstance(recorder.spans[0].exceptions[0], ValueError)
        assert recorder.spans[0]._recording is False


class TestAdapterSpanWithRecorder:
    def test_yields_recorded_span(self):
        recorder = SpanRecorder()
        with adapter_span("airtable.load", _recorder=recorder, base_id="app") as span:
            span.set_attribute("records.count", 5)

        assert len(recorder.spans) == 1
        assert recorder.spans[0].name == f"{_SPAN_PREFIX}airtable.load"
        assert recorder.spans[0].attributes["base_id"] == "app"
        assert recorder.spans[0].attributes["records.count"] == 5

    def test_prefixes_span_name(self):
        recorder = SpanRecorder()
        with adapter_span("excel.write", _recorder=recorder) as span:
            pass

        assert recorder.spans[0].name == "ffai.adapters.excel.write"

    def test_records_exception_on_failure(self):
        recorder = SpanRecorder()
        with pytest.raises(RuntimeError, match="fail"):
            with adapter_span("test", _recorder=recorder) as span:
                raise RuntimeError("fail")

        assert len(recorder.spans[0].exceptions) == 1
        assert isinstance(recorder.spans[0].exceptions[0], RuntimeError)

    def test_exception_re_raised(self):
        recorder = SpanRecorder()
        with pytest.raises(ValueError, match="original"):
            with adapter_span("test", _recorder=recorder):
                raise ValueError("original")

    def test_no_exception_no_recorded_exceptions(self):
        recorder = SpanRecorder()
        with adapter_span("test", _recorder=recorder):
            pass

        assert recorder.spans[0].exceptions == []


class TestAdapterSpanProduction:
    def test_yields_span_without_crashing(self):
        with adapter_span("test.production", key="value") as span:
            span.set_attribute("extra", 42)

    def test_exception_propagates_without_crashing(self):
        with pytest.raises(ValueError, match="prod error"):
            with adapter_span("test.production"):
                raise ValueError("prod error")
