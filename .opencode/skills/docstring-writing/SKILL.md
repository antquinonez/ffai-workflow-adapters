---
name: docstring-writing
description: Use when writing, reviewing, or adding docstrings to Python source files in ffai-workflow-adapters. Load BEFORE writing or modifying any docstrings. Covers documentation order (outside-in), Google-style conventions, coverage rules, content quality, insertion workflow, and validation.
license: MIT
---

# Docstring Writing Skill

Read this before writing or modifying docstrings. Every docstring must be
accurate, complete, and match the project's conventions.

## Style: Google

The project uses Google-style docstrings. Follow the patterns already in the
codebase. Refer to `ffai_workflow_adapters/config.py` for Pydantic model
docstrings and `ffai_workflow_adapters/_validation.py` for function docstrings
as canonical examples once established.

### Module docstrings

```python
"""Load and validate tabular workflow data for ffai execution.

Shared schema validation used by both the Airtable and Excel adapters.
Checks for required fields (name, prompt) and validates numeric types
(temperature, max_tokens) before ffai's load_workflow_rows is called.
"""

from __future__ import annotations

import os
from typing import Any
```

Module docstrings must be the **first statement** in the file for
`ast.get_docstring()` to detect them. Place them **before**
`from __future__` imports:

```python
"""Short imperative summary of the module.

Extended description.
"""

from __future__ import annotations

import os
```

This project uses `from __future__ import annotations` in all source files.
The module docstring must come before it.

### Class docstrings

```python
class TokenBucket:
    """Token bucket rate limiter with thread-safe acquire.

    Controls request rate to external APIs. Tokens refill at a constant
    rate up to the burst capacity. Blocks when no tokens are available.

    Attributes:
        _rate: Tokens added per second.
        _burst: Maximum token capacity.
        _tokens: Current token count.
        _last: Timestamp of last refill.
        _lock: Thread lock for state mutations.
    """
```

For Pydantic model classes (config.py), list every field in `Attributes:`
with its type and meaning. The type annotation comes from the source — never
restate it; describe the semantic purpose instead.

### Method and function docstrings

```python
def load_workflow_excel(
    path: str | Path,
    *,
    sheet: str | int | None = None,
    adapter: str | None = None,
    name: str = "unnamed",
    description: str = "",
    defaults: dict[str, Any] | None = None,
) -> Any:
    """Load a workflow from an Excel file into a ffai WorkflowSpec.

    Reads the specified sheet, applies field mapping from adapter config,
    validates required columns, and delegates to ffai's load_workflow_rows.

    Args:
        path: Path to the .xlsx file.
        sheet: Sheet name or index. Defaults to the active sheet.
        adapter: Named adapter variant from config/adapters.yaml.
            When provided, overrides field maps and passthrough columns.
        name: Workflow name assigned to the resulting WorkflowSpec.
        description: Workflow description for the resulting WorkflowSpec.
        defaults: Default values merged into each row (model, temperature,
            etc.).

    Returns:
        A ffai WorkflowSpec ready for execution.

    Raises:
        TabularLoadError: If the file cannot be read, required columns are
            missing, or field values have invalid types.
    """
```

Sections in order (omit empty sections):

1. Summary line (imperative mood, one sentence, first Capital)
2. Blank line + extended description (if needed)
3. `Args:` — one entry per parameter (omit `self`, omit if no parameters)
4. `Returns:` — type and meaning (omit if returns `None`)
5. `Raises:` — exception types and conditions (omit if none raised)
6. `Example:` — only when usage is non-obvious (follow `doc-writing` skill rules)

## DS-0: Documentation Order (Outside-In)

When adding or reviewing docstrings across the project, follow this order:

### Layer 1: Module docstrings

Every `.py` file in `ffai_workflow_adapters/` gets a module docstring first.
These are cheap to write and anchor the mental model for everything that
follows. A good module docstring means function docstrings can reference
concepts instead of re-explaining them.

Modules to document:

- `ffai_workflow_adapters/__init__.py` — re-export module (skip per DS-1)
- `ffai_workflow_adapters/config.py` — Pydantic-settings configuration
- `ffai_workflow_adapters/_validation.py` — Shared schema validation
- `ffai_workflow_adapters/_resilience.py` — Rate limiting, circuit breaker, retry
- `ffai_workflow_adapters/_templates.py` — Template variable resolution
- `ffai_workflow_adapters/airtable.py` — Airtable load/write adapter
- `ffai_workflow_adapters/excel.py` — Excel load/write adapter

### Layer 2: Core public functions

Document the six public API functions next. These form the primary API surface
that consumers interact with:

- `load_workflow_airtable` — Load workflow from Airtable
- `write_workflow_results` — Write results back to Airtable
- `load_workflow_excel` — Load workflow from Excel
- `write_workflow_results_excel` — Write results to Excel
- `get_config` — Access the config singleton
- `reload_config` — Force re-read YAML config files

### Layer 3: Core config classes

Document the Pydantic config models that define the configuration system:

- `Config` — Root config model
- `RetryConfig` — Retry behavior
- `ResilienceConfig` — Rate limit, circuit breaker, batch settings
- `AdaptersConfig` — Per-adapter field maps and settings
- `AirtableAdapterConfig` — Airtable-specific configuration
- `ExcelAdapterConfig` — Excel-specific configuration

### Layer 4: Supporting classes and functions

Leaf modules, utility functions, and internal classes:

- `TokenBucket` — Rate limiter
- `CircuitBreaker` — Failure protection
- `ResilientCaller` — Composed resilience wrapper
- `validate_schema` — Schema validation
- `_resolve_extra_value` — Template resolution
- `_get_api_key` — API key resolution

### Layer 5: Review pass

After all docstrings are in place, run `ruff check ffai_workflow_adapters/`
and `pyright ffai_workflow_adapters/` and verify no regressions.

### Exception: feature-branch documentation

When working on a specific feature, document what you touch regardless of
its layer. Don't leave undocumented code behind because it's "out of order."
This rule overrides the layering for incremental work.

## DS-1: Coverage Rules

### Must have docstrings

- Every module (top-level `"""..."""`)
- Every public class
- Every public method of a public class
- Every standalone public function
- Every public dataclass/Pydantic field (via `Attributes:` in the class docstring)

### May omit docstrings

- `__init__` — only when the class docstring already documents construction
- Private methods (names starting with `_`, excluding dunder methods)
- Trivial methods whose behavior is obvious from the name (`to_dict`,
  `from_dict`, `__repr__`, `__len__`)
- Properties that simply return a stored attribute

### Never add docstrings to

- Test files
- `__init__.py` re-export modules (the source modules are documented)
- Type aliases and `TypeVar` declarations

## DS-2: Content Quality

### Describe contracts, not implementation

```python
# Bad — describes the code
def validate_schema(rows, source_label):
    """Loops through rows and checks for required fields and numeric types."""

# Good — describes the contract
def validate_schema(rows, source_label):
    """Verify that workflow rows contain required fields and valid numeric types.

    Raises TabularLoadError with row-level detail identifying the offending
    field and its actual value.
    """
```

### Derive types from signatures, not memory

Read the actual function signature before writing `Args:` or `Returns:`.
The parameter names, types, and defaults in the docstring must match the
signature exactly. A mismatch between `path: str | Path` in the signature
and `path (str)` in the docstring is a documentation bug.

### Be specific about defaults

When a parameter has a default value, state what it means:

```python
# Bad
    adapter: Named adapter variant. Defaults to None.

# Good
    adapter: Named adapter variant from config/adapters.yaml.
        When None, uses the base adapter configuration.
```

### Document side effects

If a method modifies state, makes network calls, writes to disk, or logs
warnings, mention it in the extended description.

### Document thread safety

For classes used across threads (TokenBucket, CircuitBreaker, ResilientCaller),
note whether they are thread-safe and what synchronization mechanism they use.

## DS-3: Mechanical Insertion

### Single docstring — direct edit

For one-off additions, use the `edit` tool to insert the docstring as the
first statement of the function/class body. Match the indentation of the
existing body.

### Module docstring — insert before `from __future__`

For module docstrings, insert the triple-quoted string as the very first
line of the file, before any `from __future__` imports:

```python
# Before:
from __future__ import annotations
import os

# After:
"""Short imperative summary of the module.

Extended description.
"""

from __future__ import annotations

import os
```

### Audit coverage

Before starting a docstring pass, run the audit to see what's missing:

```bash
# Full coverage report
.venv/bin/python scripts/add_docstrings.py --audit

# Only undocumented targets
.venv/bin/python scripts/add_docstrings.py --audit --audit-missing
```

### Batch docstrings — single-line via --map

```bash
.venv/bin/python scripts/add_docstrings.py \
    --map "_validation.py:module=Shared schema validation for required fields and type checks." \
    --map "_validation.py:validate_schema=Verify workflow rows contain required fields and valid numeric types." \
    --dry-run
```

Target syntax:
- `file.py:module` — module-level docstring
- `file.py:ClassName` — class docstring
- `file.py:ClassName.method` — method docstring
- `file.py:function_name` — standalone function docstring

Always run with `--dry-run` first. Verify the output, then re-run without it.

### Batch docstrings — multi-line via --map-file

For docstrings with Args/Returns sections, use a JSON file:

```json
{
    "airtable.py:load_workflow_airtable": "Load a workflow from an Airtable table.\n\nArgs:\n    base_id: Airtable base ID.\n    table_name: Table name within the base.",
    "excel.py:load_workflow_excel": "Load a workflow from an Excel file.\n\nArgs:\n    path: Path to the .xlsx file."
}
```

```bash
.venv/bin/python scripts/add_docstrings.py --map-file docstrings.json --dry-run
```

You can combine `--map` and `--map-file` in the same invocation.

### Batch workflow

When adding docstrings to multiple symbols in one session:

1. Start with module docstrings (Layer 1) — these are fastest
2. Move to public functions (Layer 2) — highest visibility
3. Then config classes (Layer 3)
4. Finally supporting internals (Layer 4)
5. Run `ruff check ffai_workflow_adapters/` and `pyright ffai_workflow_adapters/`
   after each layer

## DS-4: Validation Workflow

After adding or modifying docstrings, run these checks in order:

1. **Syntax** — `ast.parse` (the `add_docstrings.py` script does this automatically
   for batch inserts; for direct edits, the linter will catch it)
2. **Lint** — `ruff check ffai_workflow_adapters/` (catches D-series docstring
   violations if enabled, plus general issues)
3. **Type check** — `pyright ffai_workflow_adapters/` (ensures edits didn't
   break types)
4. **Tests** — `pytest` (ensures no runtime regressions)
5. **API docs** — `/update-docs` or `scripts/generate_api_docs.py` (regenerates
   the API reference from the updated docstrings)

If the doc build produces errors about a module (import failure, missing file),
fix the source or the module list in `generate_api_docs.py`.

## DS-5: Common Mistakes

| Mistake | Example | Fix |
|---------|---------|-----|
| Wrong parameter name | `filepath` in doc but `path` in sig | Read the actual signature |
| Missing `Args:` for non-trivial params | Omitting args because they seem "obvious" | Every non-self parameter gets documented |
| Duplicating type in prose | ``path (str): The file path`` | Just ``path: Path to the .xlsx file`` |
| Summary in third person | `Loads the workflow` | `Load the workflow` (imperative) |
| Closing triple-quote misaligned | `"""text\n  """` at wrong indent | Match body indentation exactly |
| Markdown formatting in docstrings | ``**bold**``, ``# Header`` in docstrings | Use plain text or reStructuredText only |

## DS-6: Interaction with Other Skills

- When a docstring contains a **code example**, follow the `doc-writing` skill
  (DW-1 through DW-14) for validating it.
- When writing docstrings as part of a **new feature**, follow the
  `layered-design` skill for the implementation, then add docstrings as the
  final layer.
- When writing tests for docstring-validated behavior, follow the `testing`
  skill principles.
