"""Shared row processing and record building for tabular adapters."""
from __future__ import annotations

from typing import Any

from ffai_workflow_adapters._templates import _generate_run_id, _resolve_extra_value

CANONICAL_OUTPUT_FIELDS: list[str] = [
    "workflow", "step", "status", "response", "model",
    "input_tokens", "output_tokens", "cost_usd", "duration_ms", "timestamp",
]


def process_tabular_rows(
    raw_records: list[dict[str, Any]],
    *,
    field_map: dict[str, str] | None = None,
    passthrough_columns: list[str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Apply field mapping and collect passthrough metadata from raw records.

    Each dict in raw_records maps column names to values (already parsed
    from the source format). Applies input_field_map to translate user
    column names to canonical field names. Collects passthrough column
    values keyed by step name into source_metadata.

    Args:
        raw_records: List of {column_name: value} dicts from the source.
        field_map: Maps user column names to canonical names. None = identity.
        passthrough_columns: Column names to preserve in source_metadata.

    Returns:
        Tuple of (mapped_rows, source_metadata).
        mapped_rows: List of {canonical_name: value} dicts.
        source_metadata: {step_name: {passthrough_col: value}} dict.
    """
    rows: list[dict[str, Any]] = []
    source_metadata: dict[str, dict[str, Any]] = {}

    for record in raw_records:
        if not any(v is not None for v in record.values()):
            continue

        if field_map:
            mapped: dict[str, Any] = {}
            for col, val in record.items():
                canonical = field_map.get(col, col)
                if canonical is not None:
                    mapped[canonical] = val
            rows.append(mapped)
            step_name = str(mapped.get("name", ""))
        else:
            rows.append(record)
            step_name = str(record.get("name", ""))

        if passthrough_columns and step_name:
            pt_data = {col: record[col] for col in passthrough_columns if col in record}
            if pt_data:
                source_metadata[step_name] = pt_data

    return rows, source_metadata


def build_output_records(
    result: Any,
    *,
    output_field_map: dict[str, str] | None = None,
    passthrough_columns: list[str] | None = None,
    extra_output_columns: dict[str, str] | None = None,
    source_metadata: dict[str, dict[str, Any]] | None = None,
    run_id: str | None = None,
) -> tuple[list[dict[str, Any]], list[str], str]:
    """Build output records from a workflow result.

    Constructs one record per step with canonical fields, passthrough
    columns, and extra output columns. Applies output_field_map to
    rename columns for the target format.

    Args:
        result: A ffai WorkflowResult with step results.
        output_field_map: Maps canonical names to output column names.
        passthrough_columns: Columns preserved from source_metadata.
        extra_output_columns: {column_name: template_string} for extras.
        source_metadata: {step_name: {col: value}} from load phase.
        run_id: Unique run identifier. Auto-generated if None.

    Returns:
        Tuple of (records, column_names, resolved_run_id).
        records: List of {output_col: value} dicts, one per step.
        column_names: Ordered list of output column names.
        resolved_run_id: The run_id used (generated or passed).
    """
    resolved_run_id = run_id or _generate_run_id()

    resolved_extras = (
        {col: _resolve_extra_value(tmpl, resolved_run_id) for col, tmpl in extra_output_columns.items()}
        if extra_output_columns
        else {}
    )

    timestamp = _resolve_extra_value("{{timestamp}}", resolved_run_id)
    records: list[dict[str, Any]] = []

    for step_name, step_result in result.results.items():
        fields: dict[str, Any] = {
            "workflow": result.spec_name or "",
            "step": step_name,
            "status": step_result.status,
            "response": step_result.response or "",
            "model": step_result.model or "",
            "timestamp": timestamp,
        }
        if step_result.usage:
            fields["input_tokens"] = step_result.usage.input_tokens
            fields["output_tokens"] = step_result.usage.output_tokens
        if step_result.cost_usd:
            fields["cost_usd"] = step_result.cost_usd
        if step_result.duration_ms:
            fields["duration_ms"] = round(step_result.duration_ms, 1)

        if source_metadata and step_name in source_metadata:
            for col in passthrough_columns or []:
                if col in source_metadata[step_name]:
                    fields[col] = source_metadata[step_name][col]

        for col_name, value in resolved_extras.items():
            fields[col_name] = value

        if output_field_map:
            fields = {output_field_map.get(k, k): v for k, v in fields.items()}

        records.append(fields)

    passthrough_cols = passthrough_columns or []
    extra_cols = list((extra_output_columns or {}).keys())

    def _map_col(c: str) -> str:
        return output_field_map.get(c, c) if output_field_map else c

    column_names = (
        [_map_col(f) for f in CANONICAL_OUTPUT_FIELDS]
        + [_map_col(c) for c in passthrough_cols]
        + [_map_col(c) for c in extra_cols]
    )

    return records, column_names, resolved_run_id
