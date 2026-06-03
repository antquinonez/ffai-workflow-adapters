"""ODS (OpenDocument Spreadsheet) load/write adapter for ffai workflow execution."""
from __future__ import annotations

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


def _cell_value(cell: Any) -> Any:
    from odf.text import P

    ps = cell.getElementsByType(P)
    if not ps:
        return None
    text_parts: list[str] = []
    for p in ps:
        if p.firstChild is not None:
            text_parts.append(str(p.firstChild))
    text = "".join(text_parts).strip()
    if not text:
        return None
    try:
        return float(text) if "." in text else int(text)
    except ValueError:
        return text


def load_workflow_ods(
    path: str | Path,
    *,
    sheet: str | int | None = None,
    adapter: str | None = None,
    name: str = "unnamed",
    description: str = "",
    defaults: dict[str, Any] | None = None,
    clients: dict[str, dict[str, Any] | str] | None = None,
    tools: dict[str, dict[str, Any]] | None = None,
) -> Any:
    """Load a workflow from an ODS file into a ffai WorkflowSpec.

    Reads the specified sheet, applies field mapping from the resolved
    adapter config, validates required columns, and delegates to ffai's
    load_workflow_rows. Warns about unrecognized columns.

    Args:
        path: Path to the .ods file.
        sheet: Sheet name or index. Defaults to the first sheet.
        adapter: Named adapter variant from config/adapters.yaml.
        name: Workflow name assigned to the resulting WorkflowSpec.
        description: Workflow description for the resulting WorkflowSpec.
        defaults: Default values merged into each row.
        clients: Client definitions passed through to ffai.
        tools: Tool definitions passed through to ffai.

    Returns:
        A ffai WorkflowSpec ready for execution.

    Raises:
        TabularLoadError: If odfpy is not installed, the file is not
            found, the sheet has no header row, there are no data rows,
            or required columns are missing.
    """
    try:
        from odf.opendocument import load as odf_load
        from odf.table import Table as OdsTable
        from odf.table import TableCell as OdsTableCell
        from odf.table import TableRow as OdsTableRow
    except ImportError as e:
        raise TabularLoadError(
            "odfpy is required for ODS loading. Install with: pip install ffai-workflow-adapters[ods]"
        ) from e

    filepath = Path(path)
    if not filepath.exists():
        raise TabularLoadError(f"ODS file not found: {filepath}")

    with adapter_span(
        "ods.load",
        adapter=adapter or "default",
        path=str(filepath),
        sheet=str(sheet) if sheet else "first",
    ) as span:
        doc = odf_load(str(filepath))
        sheets = doc.spreadsheet.getElementsByType(OdsTable)  # type: ignore[union-attr]
        if not sheets:
            raise TabularLoadError(f"ODS file '{filepath}' has no sheets")

        if sheet is None:
            table = sheets[0]
        elif isinstance(sheet, int):
            table = sheets[sheet]
        else:
            table = None
            for s in sheets:
                if getattr(s, "getAttribute", lambda *a: None)("name") == sheet:
                    table = s
                    break
            if table is None:
                raise TabularLoadError(f"Sheet '{sheet}' not found in '{filepath}'")

        rows_el = table.getElementsByType(OdsTableRow)
        if not rows_el:
            raise TabularLoadError(f"ODS file '{filepath}' has no rows")

        header_cells = rows_el[0].getElementsByType(OdsTableCell)
        headers = [str(_cell_value(c) or "").strip() for c in header_cells]

        span.set_attribute("columns.count", len(headers))

        cfg = get_config().adapters.ods.resolve(adapter)
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

        raw_records: list[dict[str, Any]] = []
        for row_el in rows_el[1:]:
            cells = row_el.getElementsByType(OdsTableCell)
            record: dict[str, Any] = {}
            for i, cell in enumerate(cells):
                if i < len(headers) and headers[i]:
                    record[headers[i]] = _cell_value(cell)
            raw_records.append(record)

        rows, source_metadata = process_tabular_rows(
            raw_records, field_map=field_map, passthrough_columns=passthrough
        )

        if not rows:
            raise TabularLoadError(f"ODS file '{filepath}' contains no data rows")

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


def write_workflow_results_ods(
    result: Any,
    path: str | Path | None = None,
    *,
    sheet: str | None = None,
    adapter: str | None = None,
    spec: Any | None = None,
    run_id: str | None = None,
) -> str:
    """Write workflow execution results to an ODS file.

    Creates one row per workflow step with columns for status, response,
    model, token usage, cost, and duration. Always creates a new file.
    Supports passthrough columns from the source spec and extra output
    columns with template resolution.

    Args:
        result: A ffai WorkflowResult containing step results.
        path: Output file path. Falls back to the adapter config's
            ``output_path``.
        sheet: Sheet name for results. Defaults to the adapter config's
            ``output_sheet`` or "Results".
        adapter: Named adapter variant for output field mapping.
        spec: The original WorkflowSpec (used for passthrough column data).
        run_id: Unique run identifier. Auto-generated if not provided.

    Returns:
        The file path written to, as a string.

    Raises:
        TabularLoadError: If odfpy is not installed.
        ValueError: If no output path is specified.
    """
    try:
        from odf.opendocument import OpenDocumentSpreadsheet
        from odf.table import Table as OdsTable, TableCell, TableRow
        from odf.text import P
    except ImportError as e:
        raise TabularLoadError(
            "odfpy is required for ODS output. Install with: pip install ffai-workflow-adapters[ods]"
        ) from e

    cfg = get_config().adapters.ods.resolve(adapter)

    filepath = Path(path) if path else Path(cfg.output_path) if cfg.output_path else None
    if not filepath:
        raise ValueError("No output path specified: pass path= or set output_path in config")

    sheet_name = sheet or cfg.output_sheet or "Results"
    source_metadata = getattr(spec, "_source_metadata", None) if spec else None

    with adapter_span(
        "ods.write",
        adapter=adapter or "default",
        path=str(filepath),
        sheet=sheet_name,
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

        doc = OpenDocumentSpreadsheet()
        table: Any = OdsTable(name=sheet_name)

        def _text_cell(text: str) -> Any:
            cell = TableCell()
            p = P()
            p.addText(text)
            cell.addElement(p)
            return cell

        header_row = TableRow()
        for col_name in column_names:
            header_row.addElement(_text_cell(col_name))
        table.addElement(header_row)

        for rec in records:
            row = TableRow()
            for col_name in column_names:
                val = rec.get(col_name)
                if val is not None:
                    row.addElement(_text_cell(str(val)))
                else:
                    row.addElement(TableCell())
            table.addElement(row)

        doc.spreadsheet.addElement(table)  # type: ignore[union-attr]
        filepath.parent.mkdir(parents=True, exist_ok=True)
        doc.save(str(filepath))

        return str(filepath)
