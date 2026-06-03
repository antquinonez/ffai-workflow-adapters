"""CSV/TSV load/write adapter for ffai workflow execution."""
from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Any

from ffai.workflow.tabular import TabularLoadError, load_workflow_rows

from ffai_workflow_adapters._spans import adapter_span
from ffai_workflow_adapters._tabular_helpers import build_output_records, process_tabular_rows
from ffai_workflow_adapters._validation import validate_schema
from ffai_workflow_adapters.config import get_config

logger = logging.getLogger(__name__)

CANONICAL_FIELDS = frozenset({
    "name", "prompt", "client", "model", "history",
    "temperature", "max_tokens", "system_instructions",
    "condition", "abort_condition", "response_format",
    "response_model", "strict", "tools", "tool_choice",
})


def load_workflow_csv(
    path: str | Path,
    *,
    delimiter: str = ",",
    adapter: str | None = None,
    name: str = "unnamed",
    description: str = "",
    defaults: dict[str, Any] | None = None,
    clients: dict[str, dict[str, Any] | str] | None = None,
    tools: dict[str, dict[str, Any]] | None = None,
) -> Any:
    """Load a workflow from a CSV or TSV file into a ffai WorkflowSpec.

    Reads the file using ``csv.DictReader``, applies field mapping from the
    resolved adapter config, validates required columns, and delegates to
    ffai's load_workflow_rows. Warns about unrecognized columns.

    Args:
        path: Path to the CSV/TSV file.
        delimiter: Field delimiter. ``","`` for CSV, ``"\\t"`` for TSV.
        adapter: Named adapter variant from config/adapters.yaml.
        name: Workflow name assigned to the resulting WorkflowSpec.
        description: Workflow description for the resulting WorkflowSpec.
        defaults: Default values merged into each row.
        clients: Client definitions passed through to ffai.
        tools: Tool definitions passed through to ffai.

    Returns:
        A ffai WorkflowSpec ready for execution.

    Raises:
        TabularLoadError: If the file is not found, has no data rows,
            or required columns are missing.
    """
    filepath = Path(path)
    if not filepath.exists():
        raise TabularLoadError(f"CSV file not found: {filepath}")

    with adapter_span(
        "csv.load",
        adapter=adapter or "default",
        path=str(filepath),
        delimiter=delimiter,
    ) as span:
        with filepath.open(newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f, delimiter=delimiter)
            headers = reader.fieldnames or []
            raw_records = list(reader)

        span.set_attribute("columns.count", len(headers))

        cfg = get_config().adapters.csv_adapter.resolve(adapter)
        field_map = cfg.input_field_map or None
        passthrough = cfg.passthrough_columns or []

        valid_columns = CANONICAL_FIELDS | set(passthrough)
        if field_map:
            recognized = set(field_map.keys()) | valid_columns
            unmapped = [h for h in headers if h and h not in recognized]
        else:
            unmapped = [h for h in headers if h and h not in valid_columns]
        if unmapped:
            logger.warning(
                "Unrecognized columns in '%s': %s. "
                "These will be passed through unless they match a canonical field.",
                filepath,
                unmapped,
            )

        rows, source_metadata = process_tabular_rows(
            raw_records, field_map=field_map, passthrough_columns=passthrough
        )

        if not rows:
            raise TabularLoadError(f"CSV file '{filepath}' contains no data rows")

        validate_schema(rows, str(filepath))

        spec = load_workflow_rows(
            rows,
            name=name,
            description=description,
            defaults=defaults,
            clients=clients,
            tools=tools,
        )

        span.set_attribute("rows.count", len(rows))
        span.set_attribute("workflow.name", name)

        if source_metadata:
            object.__setattr__(spec, "_source_metadata", source_metadata)

        return spec


def load_workflow_tsv(
    path: str | Path,
    *,
    adapter: str | None = None,
    name: str = "unnamed",
    description: str = "",
    defaults: dict[str, Any] | None = None,
    clients: dict[str, dict[str, Any] | str] | None = None,
    tools: dict[str, dict[str, Any]] | None = None,
) -> Any:
    """Load a workflow from a TSV file. Equivalent to ``load_workflow_csv`` with ``delimiter='\\t'``."""
    return load_workflow_csv(
        path,
        delimiter="\t",
        adapter=adapter,
        name=name,
        description=description,
        defaults=defaults,
        clients=clients,
        tools=tools,
    )


def write_workflow_results_csv(
    result: Any,
    path: str | Path | None = None,
    *,
    delimiter: str = ",",
    adapter: str | None = None,
    spec: Any | None = None,
    run_id: str | None = None,
) -> str:
    """Write workflow execution results to a CSV or TSV file.

    Creates one row per workflow step with columns for status, response,
    model, token usage, cost, and duration. If the file exists, appends
    data rows without duplicating the header. Supports passthrough columns
    from the source spec and extra output columns with template resolution.

    Args:
        result: A ffai WorkflowResult containing step results.
        path: Output file path. Falls back to the adapter config's
            ``output_path``.
        delimiter: Field delimiter. ``","`` for CSV, ``"\\t"`` for TSV.
        adapter: Named adapter variant for output field mapping.
        spec: The original WorkflowSpec (used for passthrough column data).
        run_id: Unique run identifier. Auto-generated if not provided.

    Returns:
        The file path written to, as a string.

    Raises:
        ValueError: If no output path is specified.
    """
    cfg = get_config().adapters.csv_adapter.resolve(adapter)

    filepath = Path(path) if path else Path(cfg.output_path) if cfg.output_path else None
    if not filepath:
        raise ValueError("No output path specified: pass path= or set output_path in config")

    source_metadata = getattr(spec, "_source_metadata", None) if spec else None

    with adapter_span(
        "csv.write",
        adapter=adapter or "default",
        path=str(filepath),
        delimiter=delimiter,
    ) as span:
        records, column_names, resolved_run_id = build_output_records(
            result,
            output_field_map=cfg.output_field_map or None,
            passthrough_columns=cfg.passthrough_columns or None,
            extra_output_columns=cfg.extra_output_columns or None,
            source_metadata=source_metadata,
            run_id=run_id,
        )

        span.set_attribute("records.count", len(records))

        write_header = not filepath.exists()
        filepath.parent.mkdir(parents=True, exist_ok=True)

        with filepath.open("a" if not write_header else "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f, delimiter=delimiter)
            if write_header:
                writer.writerow(column_names)
            for rec in records:
                writer.writerow([rec.get(col) for col in column_names])

        return str(filepath)


def write_workflow_results_tsv(
    result: Any,
    path: str | Path | None = None,
    *,
    adapter: str | None = None,
    spec: Any | None = None,
    run_id: str | None = None,
) -> str:
    """Write results to a TSV file. Equivalent to ``write_workflow_results_csv`` with ``delimiter='\\t'``."""
    return write_workflow_results_csv(
        result,
        path,
        delimiter="\t",
        adapter=adapter,
        spec=spec,
        run_id=run_id,
    )
