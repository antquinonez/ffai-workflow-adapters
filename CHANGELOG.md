# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2026-06-03

### Added

- CSV/TSV adapter — `load_workflow_csv`, `load_workflow_tsv`, `write_workflow_results_csv`, `write_workflow_results_tsv`. No external dependencies (uses stdlib `csv`).
- ODS adapter — `load_workflow_ods`, `write_workflow_results_ods`. Requires `odfpy` (`pip install ffai-workflow-adapters[ods]`).
- Google Sheets adapter — `load_workflow_google_sheets`, `write_workflow_results_google_sheets`. Requires `gspread` (`pip install ffai-workflow-adapters[google_sheets]`).
- Multi-auth support for Google Sheets — service account (default), OAuth, and API key authentication methods.
- Shared tabular helpers (`_tabular_helpers.py`) — `process_tabular_rows` and `build_output_records` used by all file-based adapters.
- Shared schema validation (`_validation.py`) — `validate_schema` checks required fields and numeric types before workflow loading.
- OpenTelemetry span helpers (`_spans.py`) — `adapter_span` wraps all adapter I/O in OTEL spans. Zero overhead when observability is disabled.
- Resilience primitives (`_resilience.py`) — token bucket rate limiter, circuit breaker, retry with exponential backoff, and `ResilientCaller`.
- Observability instrumentation for Airtable, Excel, CSV, ODS, and Google Sheets adapters.
- Adapter guides for [CSV](docs/csv.md), [Google Sheets](docs/google-sheets.md), and [ODS](docs/ods.md).
- Example notebooks for CSV, Excel, Google Sheets, and ODS workflows.
- PyPI, Read the Docs, and CI badges to README.

### Changed

- Google Sheets write now includes a header row when creating a new worksheet.
- Response serialization uses `str()` to handle non-string response types in output records.

## [0.1.1] - 2025-05-18

### Added

- PyPI, Read the Docs, and CI badges to README.
- `pip` and `uv` install instructions.

## [0.1.0] - 2025-05-18

### Added

- Airtable adapter — `load_workflow_airtable`, `write_workflow_results`.
- Excel adapter — `load_workflow_excel`, `write_workflow_results_excel`.
- Pydantic-settings configuration system with YAML files and environment variable overrides.
- Named adapter configs with inheritance for per-base overrides.
- Passthrough columns and extra output columns with template resolution.
- Shared validation for required fields and numeric types.
- Field mapping between user column names and canonical field names.
- Client definitions in `config/clients.yaml` with LiteLLM provider support.
- Sphinx documentation with Read the Docs integration.
- CI and PyPI publish GitHub Actions workflows.
- MIT license.

[0.2.0]: https://github.com/antquinonez/ffai-workflow-adapters/releases/tag/v0.2.0
[0.1.1]: https://github.com/antquinonez/ffai-workflow-adapters/releases/tag/v0.1.1
[0.1.0]: https://github.com/antquinonez/ffai-workflow-adapters/releases/tag/v0.1.0
