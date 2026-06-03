"""Airtable load/write adapter for ffai workflow execution."""
from __future__ import annotations

import os
from typing import Any

from ffai.workflow.tabular import TabularLoadError, load_workflow_rows

from ffai_workflow_adapters._resilience import CircuitBreaker, ResilientCaller, TokenBucket, batched
from ffai_workflow_adapters._spans import adapter_span
from ffai_workflow_adapters._templates import _generate_run_id, _resolve_extra_value
from ffai_workflow_adapters._validation import validate_schema
from ffai_workflow_adapters.config import get_config


def _get_api_key(api_key: str | None = None, env_var: str | None = None) -> str:
    if api_key:
        return api_key

    key_env = env_var or get_config().adapters.airtable.api_key_env

    key = os.environ.get(key_env)
    if not key:
        raise TabularLoadError(
            f"Airtable API key not provided. Pass api_key parameter or set {key_env} environment variable."
        )
    return key


_last_config_id: int = 0
_caller: ResilientCaller | None = None


def _make_caller() -> ResilientCaller:
    global _caller, _last_config_id
    cfg = get_config()
    cfg_id = id(cfg)
    if _caller is not None and cfg_id == _last_config_id:
        return _caller
    rl = cfg.resilience.rate_limit
    cb = cfg.resilience.circuit_breaker
    retry = cfg.retry
    _caller = ResilientCaller(
        bucket=TokenBucket(rate=rl.requests_per_second, burst=rl.burst),
        breaker=CircuitBreaker(
            failure_threshold=cb.failure_threshold,
            recovery_timeout_seconds=cb.recovery_timeout_seconds,
            half_open_max_calls=cb.half_open_max_calls,
        ),
        retry_max_attempts=retry.max_attempts,
        retry_min_wait=retry.min_wait_seconds,
        retry_max_wait=retry.max_wait_seconds,
        retry_exponential_base=retry.exponential_base,
        retry_jitter=retry.exponential_jitter,
        retry_on_status_codes=retry.retry_on_status_codes,
        acquire_timeout=30.0,
    )
    _last_config_id = cfg_id
    return _caller


def _reset_caller() -> None:
    global _caller, _last_config_id
    _caller = None
    _last_config_id = 0


def load_workflow_airtable(
    base_id: str,
    table_name: str,
    *,
    adapter: str | None = None,
    api_key: str | None = None,
    api_key_env: str | None = None,
    view: str | None = None,
    name: str = "unnamed",
    description: str = "",
    defaults: dict[str, Any] | None = None,
    clients: dict[str, dict[str, Any] | str] | None = None,
    tools: dict[str, dict[str, Any]] | None = None,
) -> Any:
    """Load a workflow from an Airtable table into a ffai WorkflowSpec.

    Reads all records from the specified table, applies field mapping from
    the resolved adapter config, validates required columns, and delegates
    to ffai's load_workflow_rows. Includes rate limiting, circuit breaking,
    and retry with exponential backoff.

    Args:
        base_id: Airtable base ID.
        table_name: Table name within the base.
        adapter: Named adapter variant from config/adapters.yaml.
            When provided, overrides field maps and passthrough columns.
        api_key: Airtable API key. Falls back to the environment variable
            named by ``api_key_env``.
        api_key_env: Environment variable name holding the API key.
            Defaults to the adapter config's ``api_key_env``.
        view: Airtable view name to filter records. Defaults to the
            adapter config's ``default_view``.
        name: Workflow name assigned to the resulting WorkflowSpec.
        description: Workflow description for the resulting WorkflowSpec.
        defaults: Default values merged into each row (model, temperature,
            etc.).
        clients: Client definitions passed through to ffai.
        tools: Tool definitions passed through to ffai.

    Returns:
        A ffai WorkflowSpec ready for execution.

    Raises:
        TabularLoadError: If pyairtable is not installed, the API key is
            missing, the table is empty, or required columns are absent.
    """
    try:
        from pyairtable.api import Api
    except ImportError as e:
        raise TabularLoadError(
            "pyairtable is required for Airtable loading. Install with: pip install ffai-workflow-adapters[airtable]"
        ) from e

    cfg = get_config().adapters.airtable.resolve(adapter)

    if not view:
        view = cfg.default_view or None

    field_map = cfg.input_field_map or None
    passthrough = cfg.passthrough_columns or []

    key = _get_api_key(api_key, api_key_env)

    with adapter_span(
        "airtable.load",
        adapter=adapter or "default",
        base_id=base_id,
        table=table_name,
        view=view or "",
    ) as span:
        api = Api(key)
        table = api.table(base_id, table_name)

        kwargs: dict[str, Any] = {}
        if view:
            kwargs["view"] = view

        caller = _make_caller()
        records = caller.call(table.all, **kwargs)

        span.set_attribute("records.raw_count", len(records))

        source_metadata: dict[str, dict[str, Any]] = {}
        rows: list[dict[str, Any]] = []

        for record in records:
            fields = record.get("fields", {})
            if not fields:
                continue

            if field_map:
                mapped: dict[str, Any] = {}
                for col, val in fields.items():
                    canonical = field_map.get(col, col)
                    if canonical is not None:
                        mapped[canonical] = val
                rows.append(mapped)
                step_name = str(mapped.get("name", ""))
            else:
                rows.append(dict(fields))
                step_name = str(fields.get("name", ""))

            if passthrough and step_name:
                pt_data = {col: fields[col] for col in passthrough if col in fields}
                if pt_data:
                    source_metadata[step_name] = pt_data

        if not rows:
            raise TabularLoadError(
                f"Airtable table '{table_name}' in base '{base_id}' contains no records"
            )

        validate_schema(rows, f"Airtable table '{table_name}' in base '{base_id}'")

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


def write_workflow_results(
    base_id: str,
    table_name: str,
    result: Any,
    *,
    adapter: str | None = None,
    api_key: str | None = None,
    api_key_env: str | None = None,
    spec: Any | None = None,
    run_id: str | None = None,
) -> list[dict[str, Any]]:
    """Write workflow execution results back to an Airtable table.

    Creates one record per workflow step with fields for status, response,
    model, token usage, cost, and duration. Supports passthrough columns
    from the source spec and extra output columns with template resolution.

    Args:
        base_id: Airtable base ID.
        table_name: Target table name for writing results.
        result: A ffai WorkflowResult containing step results.
        adapter: Named adapter variant for output field mapping.
        api_key: Airtable API key. Falls back to environment variable.
        api_key_env: Environment variable name holding the API key.
        spec: The original WorkflowSpec (used for passthrough column data).
        run_id: Unique run identifier. Auto-generated if not provided.

    Returns:
        List of created Airtable records as dicts.

    Raises:
        TabularLoadError: If pyairtable is not installed, the API key is
            missing, or the circuit breaker is open.
    """
    try:
        from pyairtable.api import Api
    except ImportError as e:
        raise TabularLoadError(
            "pyairtable is required for Airtable output. Install with: pip install ffai-workflow-adapters[airtable]"
        ) from e

    cfg = get_config().adapters.airtable.resolve(adapter)
    output_map = cfg.output_field_map
    passthrough_cols = cfg.passthrough_columns or []
    extra_cols = cfg.extra_output_columns or {}

    key = _get_api_key(api_key, api_key_env)
    api = Api(key)
    table = api.table(base_id, table_name)

    source_metadata = getattr(spec, "_source_metadata", None) if spec else None

    resolved_run_id = run_id or _generate_run_id()

    with adapter_span(
        "airtable.write",
        adapter=adapter or "default",
        base_id=base_id,
        table=table_name,
        run_id=resolved_run_id,
    ) as span:
        resolved_extras = {col: _resolve_extra_value(tmpl, resolved_run_id) for col, tmpl in extra_cols.items()}

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
                for col in passthrough_cols:
                    if col in source_metadata[step_name]:
                        fields[col] = source_metadata[step_name][col]

            for col_name, value in resolved_extras.items():
                fields[col_name] = value

            if output_map:
                fields = {output_map.get(k, k): v for k, v in fields.items()}

            records.append(fields)

        span.set_attribute("records.count", len(records))

        cfg = get_config()
        chunk_size = cfg.resilience.batch.chunk_size
        max_concurrency = cfg.resilience.batch.max_concurrency
        span.set_attribute("batch.chunk_size", chunk_size)
        span.set_attribute("batch.max_concurrency", max_concurrency)
        caller = _make_caller()

        created: list[dict[str, Any]] = []

        if max_concurrency <= 1:
            for chunk in batched(records, chunk_size):
                result = caller.call(table.batch_create, list(chunk), typecast=True)
                created.extend(result)
        else:
            from concurrent.futures import ThreadPoolExecutor

            chunks = list(batched(records, chunk_size))

            def _write_chunk(chunk: list[dict[str, Any]]) -> list[dict[str, Any]]:
                thread_table = Api(key).table(base_id, table_name)
                return caller.call(thread_table.batch_create, chunk, typecast=True)

            with ThreadPoolExecutor(max_workers=max_concurrency) as pool:
                futures = [pool.submit(_write_chunk, list(c)) for c in chunks]
                try:
                    for future in futures:
                        created.extend(future.result())
                except Exception:
                    for f in futures:
                        f.cancel()
                    raise

        span.set_attribute("records.created", len(created))
        return [dict(r) for r in created]
