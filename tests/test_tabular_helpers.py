from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ffai_workflow_adapters._tabular_helpers import (
    CANONICAL_OUTPUT_FIELDS,
    build_output_records,
    process_tabular_rows,
)


class TestProcessTabularRows:
    def test_no_field_map_returns_rows_unchanged(self):
        raw = [
            {"name": "step1", "prompt": "Go"},
            {"name": "step2", "prompt": "Stop"},
        ]
        rows, meta = process_tabular_rows(raw)
        assert len(rows) == 2
        assert rows[0] == {"name": "step1", "prompt": "Go"}
        assert meta == {}

    def test_field_map_translates_columns(self):
        raw = [{"Task": "step1", "Instructions": "Go"}]
        rows, meta = process_tabular_rows(
            raw, field_map={"Task": "name", "Instructions": "prompt"}
        )
        assert len(rows) == 1
        assert rows[0] == {"name": "step1", "prompt": "Go"}

    def test_field_map_with_unmapped_columns_passes_through(self):
        raw = [{"Task": "step1", "Instructions": "Go", "Extra": "data"}]
        rows, _ = process_tabular_rows(
            raw, field_map={"Task": "name", "Instructions": "prompt"}
        )
        assert rows[0]["Extra"] == "data"

    def test_field_map_with_none_value_skips_column(self):
        raw = [{"Task": "step1", "Skip": "data"}]
        rows, _ = process_tabular_rows(
            raw, field_map={"Task": "name", "Skip": None}
        )
        assert "Skip" not in rows[0]
        assert rows[0]["name"] == "step1"

    def test_passthrough_columns_populates_metadata(self):
        raw = [
            {"name": "step1", "prompt": "Go", "Comments": "Check refs"},
            {"name": "step2", "prompt": "Stop", "Comments": None},
        ]
        rows, meta = process_tabular_rows(raw, passthrough_columns=["Comments"])
        assert len(rows) == 2
        assert meta["step1"]["Comments"] == "Check refs"
        assert meta["step2"]["Comments"] is None

    def test_passthrough_skips_missing_columns(self):
        raw = [{"name": "step1", "prompt": "Go"}]
        rows, meta = process_tabular_rows(raw, passthrough_columns=["Comments"])
        assert meta == {}

    def test_passthrough_with_field_map_uses_original_keys(self):
        raw = [{"Task": "step1", "Notes": "important"}]
        rows, meta = process_tabular_rows(
            raw,
            field_map={"Task": "name"},
            passthrough_columns=["Notes"],
        )
        assert rows[0]["name"] == "step1"
        assert meta["step1"]["Notes"] == "important"

    def test_skips_empty_rows(self):
        raw = [
            {"name": "step1", "prompt": "Go"},
            {"name": None, "prompt": None},
            {"name": "step3", "prompt": "Run"},
        ]
        rows, _ = process_tabular_rows(raw)
        assert len(rows) == 2
        assert rows[0]["name"] == "step1"
        assert rows[1]["name"] == "step3"

    def test_defaults_no_field_map_no_passthrough(self):
        raw = [{"name": "step1", "prompt": "Go"}]
        rows, meta = process_tabular_rows(raw, field_map=None, passthrough_columns=None)
        assert len(rows) == 1
        assert meta == {}

    def test_empty_input(self):
        rows, meta = process_tabular_rows([])
        assert rows == []
        assert meta == {}


class TestCanonicalOutputFields:
    def test_contains_expected_fields(self):
        assert "workflow" in CANONICAL_OUTPUT_FIELDS
        assert "step" in CANONICAL_OUTPUT_FIELDS
        assert "status" in CANONICAL_OUTPUT_FIELDS
        assert "response" in CANONICAL_OUTPUT_FIELDS
        assert "model" in CANONICAL_OUTPUT_FIELDS
        assert "timestamp" in CANONICAL_OUTPUT_FIELDS


@dataclass
class _FakeUsage:
    input_tokens: int = 10
    output_tokens: int = 20


@dataclass
class _FakeStepResult:
    response: str = "ok"
    model: str = "test-model"
    status: str = "success"
    usage: _FakeUsage | None = field(default_factory=_FakeUsage)
    cost_usd: float | None = 0.001
    duration_ms: float | None = 100.0


@dataclass
class _FakeWorkflowResult:
    results: dict = field(default_factory=lambda: {
        "step1": _FakeStepResult(),
        "step2": _FakeStepResult(response="done", cost_usd=None, duration_ms=None),
    })
    spec_name: str = "test_workflow"


class TestBuildOutputRecords:
    def test_produces_one_record_per_step(self):
        result = _FakeWorkflowResult()
        records, _, _ = build_output_records(result)
        assert len(records) == 2

    def test_includes_canonical_fields(self):
        result = _FakeWorkflowResult()
        records, _, _ = build_output_records(result)
        rec = records[0]
        assert rec["workflow"] == "test_workflow"
        assert rec["step"] == "step1"
        assert rec["status"] == "success"
        assert rec["response"] == "ok"
        assert rec["model"] == "test-model"
        assert "timestamp" in rec

    def test_includes_usage_when_present(self):
        result = _FakeWorkflowResult()
        records, _, _ = build_output_records(result)
        assert records[0]["input_tokens"] == 10
        assert records[0]["output_tokens"] == 20

    def test_omits_usage_when_absent(self):
        result = _FakeWorkflowResult(results={"step1": _FakeStepResult(usage=None)})
        records, _, _ = build_output_records(result)
        assert "input_tokens" not in records[0]
        assert "output_tokens" not in records[0]

    def test_includes_cost_and_duration_when_present(self):
        result = _FakeWorkflowResult()
        records, _, _ = build_output_records(result)
        assert records[0]["cost_usd"] == 0.001
        assert records[0]["duration_ms"] == 100.0

    def test_omits_cost_and_duration_when_absent(self):
        result = _FakeWorkflowResult(results={
            "step1": _FakeStepResult(cost_usd=None, duration_ms=None)
        })
        records, _, _ = build_output_records(result)
        assert "cost_usd" not in records[0]
        assert "duration_ms" not in records[0]

    def test_applies_output_field_map(self):
        result = _FakeWorkflowResult(results={"step1": _FakeStepResult(usage=None, cost_usd=None, duration_ms=None)})
        records, column_names, _ = build_output_records(
            result, output_field_map={"step": "Task", "response": "Output"}
        )
        assert records[0]["Task"] == "step1"
        assert records[0]["Output"] == "ok"
        assert "step" not in records[0]
        assert "response" not in records[0]
        assert "Task" in column_names
        assert "Output" in column_names

    def test_includes_passthrough_columns(self):
        result = _FakeWorkflowResult(results={"step1": _FakeStepResult(usage=None, cost_usd=None, duration_ms=None)})
        meta = {"step1": {"Comments": "see above"}}
        records, _, _ = build_output_records(
            result,
            passthrough_columns=["Comments"],
            source_metadata=meta,
        )
        assert records[0]["Comments"] == "see above"

    def test_passthrough_absent_from_metadata_omits_value(self):
        result = _FakeWorkflowResult(results={"step1": _FakeStepResult(usage=None, cost_usd=None, duration_ms=None)})
        records, column_names, _ = build_output_records(
            result,
            passthrough_columns=["Comments"],
            source_metadata={},
        )
        assert "Comments" in column_names
        assert records[0].get("Comments") is None

    def test_resolves_extra_output_columns(self):
        import re
        result = _FakeWorkflowResult(results={"step1": _FakeStepResult(usage=None, cost_usd=None, duration_ms=None)})
        records, column_names, _ = build_output_records(
            result,
            extra_output_columns={"run_date": "{{date}}"},
        )
        assert re.match(r"\d{4}-\d{2}-\d{2}", records[0]["run_date"])
        assert "run_date" in column_names

    def test_generates_run_id_if_not_provided(self):
        import re
        result = _FakeWorkflowResult(results={"step1": _FakeStepResult(usage=None, cost_usd=None, duration_ms=None)})
        _, _, run_id = build_output_records(result)
        assert re.match(r"\d{8}-\d{6}", run_id)

    def test_uses_provided_run_id(self):
        result = _FakeWorkflowResult(results={"step1": _FakeStepResult(usage=None, cost_usd=None, duration_ms=None)})
        records, _, run_id = build_output_records(
            result,
            extra_output_columns={"run_id": "{{run_id}}"},
            run_id="batch-42",
        )
        assert run_id == "batch-42"
        assert records[0]["run_id"] == "batch-42"

    def test_column_names_order(self):
        result = _FakeWorkflowResult(results={"step1": _FakeStepResult(usage=None, cost_usd=None, duration_ms=None)})
        _, column_names, _ = build_output_records(
            result,
            passthrough_columns=["Comments"],
            extra_output_columns={"run_id": "{{run_id}}"},
        )
        canonical_end = len(CANONICAL_OUTPUT_FIELDS)
        assert column_names[canonical_end] == "Comments"
        assert column_names[canonical_end + 1] == "run_id"

    def test_run_id_consistent_across_records(self):
        result = _FakeWorkflowResult()
        records, _, run_id = build_output_records(
            result,
            extra_output_columns={"run_id": "{{run_id}}"},
        )
        assert records[0]["run_id"] == records[1]["run_id"] == run_id
