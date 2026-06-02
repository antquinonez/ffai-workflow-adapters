# AGENTS.md

## Project

External workflow adapters for [ffai](https://pypi.org/project/ffai/) — load and execute LLM workflows from Airtable, Excel, and other tabular sources. Each row in a spreadsheet becomes a workflow step (name, prompt, model, temperature, etc.).

## Commands

```bash
source .venv/bin/activate

# Lint
ruff check ffai_workflow_adapters/

# Type check
pyright ffai_workflow_adapters/

# Unit tests (excludes integration)
pytest

# All tests (including integration — calls real APIs, needs .env)
pytest -m ''

# Single test file
pytest tests/test_excel.py

# Docs (HTML, text, JSON)
cd docs && make html
cd docs && make text
cd docs && make json
```

## Architecture

```
ffai_workflow_adapters/
  __init__.py          # Public API re-exports
  _validation.py       # Shared schema validation (required fields, type checks)
  config.py            # Pydantic-settings config from YAML + env vars
  airtable.py          # Airtable load/write adapter
  excel.py             # Excel load/write adapter

config/
  main.yaml            # Retry settings
  adapters.yaml        # Per-adapter field maps, passthrough columns, named variants
  clients.yaml         # LLM client definitions (LiteLLM providers)
  logging.yaml         # Logging config

tests/
  test_airtable.py     # Airtable unit tests (mocked)
  test_excel.py        # Excel unit tests (real openpyxl, mock ffai)
  test_config.py       # Config loading/resolution tests
  integration/         # Real API calls — needs credentials in .env

docs/
  conf.py              # Sphinx configuration
  index.md             # Root toctree
  Makefile             # Build targets: html, text, json
  api/index.rst        # Autodoc API reference
  README.md            # Project overview and quickstart
  airtable.md          # Airtable adapter guide
  excel.md             # Excel adapter guide
```

## Key patterns

- **Optional deps** — `pyairtable` and `openpyxl` are lazily imported with clear error messages. Never import at module top level.
- **Field mapping** — Adapters use `input_field_map` / `output_field_map` dicts to translate between user column names and canonical field names (`name`, `prompt`, `temperature`, etc.).
- **Named adapters** — `adapters.yaml` supports `named:` variants that inherit/override base config per adapter. Accessed via `adapter="custom"` kwarg.
- **Config priority** — constructor kwargs > env vars (delimiter `__`) > YAML files.
- **Shared validation** — `_validation.validate_schema()` checks required fields (`name`, `prompt`) and numeric types (`temperature`, `max_tokens`). Called by both `airtable.py` and `excel.py` before `load_workflow_rows`.
- **Passthrough columns** — Columns listed in `passthrough_columns` are preserved from input to output (e.g. Comments, Priority).
- **Extra output columns** — Template strings like `{{run_id}}`, `{{date}}`, `{{timestamp}}` in `extra_output_columns` are resolved at write time.
