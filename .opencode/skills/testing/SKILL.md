---
name: testing
description: Use when writing, reviewing, or enhancing tests for the ffai-workflow-adapters project. Triggers on test-related tasks including writing new tests, fixing test failures, improving test quality, or auditing test coverage. Load BEFORE writing or modifying any test file.
license: MIT
---

# Testing Principles

Read this before writing or reviewing tests. Tests must verify **correct behavior**, not exercise code paths for coverage. A test that passes without asserting anything meaningful is worse than no test.

## Organization

- Use pytest with class-based test organization
- Place shared fixtures in `conftest.py` — do not copy-paste fixtures across test classes
- Name test files as `test_<module>.py`, classes as `Test<Feature>`, methods as `test_<description>`
- Import modules inside test methods when mocking is needed

## Test Commands

```bash
source .venv/bin/activate

pytest                                       # Unit tests (excludes integration)
pytest -m ''                                 # All tests (including integration — needs .env)
pytest tests/test_excel.py -v                # Single test file
pytest tests/test_excel.py::TestLoadWorkflowExcel -v  # Single test class
pytest tests/test_excel.py::TestLoadWorkflowExcel::test_basic_load -v  # Single test method
```

## Principles

### TP-1: Assert specific values, not just types

Every test must assert at least one specific, predictable value. `isinstance(result, float)`, `isinstance(result, list)`, and `result is not None` are not sufficient assertions on their own.

Bad:
```python
spec = load_workflow_excel(filepath)
assert isinstance(spec, object)
```

Good:
```python
spec = load_workflow_excel(filepath, name="test")
assert spec.name == "test"
assert len(spec.prompts) == 2
assert spec.prompts[0].name == "topic"
```

### TP-2: Assert the semantics, not the implementation

Tests should verify *what* the code computes, not *how* it computes it. If the test would need to change after a correct refactoring, the test is coupled to the wrong thing.

- For field mapping: assert the mapped output contains expected canonical names — not that a specific dict method was called.
- For write operations: assert the written records contain expected field values — not the internal construction of the fields dict.
- For validation: assert the correct exception type and message — not which validation function ran first.

### TP-3: Do not enshrine bugs as expected behavior

If a function returns a wrong result, write the test to assert the **correct** behavior and let it fail. Then fix the source code. Never write a passing test that asserts incorrect output just to gain coverage.

### TP-4: Every edge-case test needs a justification

When testing an edge case (empty table, missing columns, malformed temperature, empty fields dict), document *why* this edge case matters and what the correct behavior should be. Do not construct pathological inputs just because a code path exists.

### TP-5: Test error paths by asserting the error

Assert the specific exception type and error message content. Do not catch the exception and assert `True`.

Good:
```python
with pytest.raises(TabularLoadError, match="missing required columns"):
    load_workflow_excel(filepath)
```

### TP-6: Coverage is a finding tool, not a target

Use coverage reports to identify untested code paths, then write tests that verify correct behavior on those paths. Do not write tests whose only purpose is to move the coverage number upward.

### TP-7: Avoid compound weak assertions

Prefer one strong assertion over several weak ones. Use `==` when the input deterministically produces a known result. Use `>=` only when the exact count depends on non-deterministic ordering.

Never use `or` in assertions — `assert "name" in row or "prompt" in row` passes if either is present, testing nothing specific.

### TP-8: Test observable behavior over internal state

Prefer testing through the public API. Directly accessing private attributes (`_source_metadata`) is acceptable for coverage of internal logic that cannot be observed through public methods, but the test must still assert specific values on those internals, not just their existence or type.

### TP-9: Use exact assertions on deterministic outputs

When the test input fully determines the output, use `==` not `<=` or `>=`. Use `>=` or `<=` only when the output is genuinely non-deterministic (LLM response content, token counts that vary by provider).

Bad:
```python
assert mock_table.all.call_count >= 1
```

Good:
```python
mock_table.all.assert_called_once_with()
```

### TP-10: Verify expected values empirically

Before writing an exact assertion, run the code in isolation to confirm the expected value. Guessing at counts, lengths, or numeric results leads to test failures that waste review time.

### TP-11: Correctness over coverage

- **Invariants**: Test bounds, identities, and conservation laws. If token counts must be non-negative, assert it. If record counts match step counts, assert it.
- **Consistency**: Two adapters computing the same thing must agree. If both Excel and Airtable map "Task" → "name", they should produce the same canonical output.
- **Independent verification**: Verify against independent calculation — not by running the code under test and copying its output.
- **Property tests over single-value tests**: Prefer testing structural properties (ordering, containment, idempotency) when the output has natural invariants.

### TP-12: Mock at the boundary, not the internals

Prefer mocking at the external API boundary (`pyairtable.api.Api`, `openpyxl.load_workbook`) over setting private attributes directly. When public API is not available for configuration needed in tests, prefer adding a constructor parameter to the production code rather than bypassing it with private attribute assignment.

### TP-13: Assert record/row content, not just structure

Tests that verify written records must check actual field values, not just that the record is non-empty or has expected keys.

Bad:
```python
records = mock_table.batch_create.call_args[0][0]
assert len(records) > 0
assert "step" in records[0]
```

Good:
```python
records = mock_table.batch_create.call_args[0][0]
assert records[0]["step"] == "topic"
assert records[0]["workflow"] == "test_workflow"
assert records[0]["status"] == "success"
assert records[0]["input_tokens"] == 41
```

When exact values depend on LLM output (integration tests), assert structural properties instead: field existence, non-negative counts, expected status values, or that specific expected fields contain non-null values.

### TP-14: No vacuous tests

Every test must contain at least one `assert` statement. A test that calls methods without asserting anything is worse than no test — it inflates the test count without verifying behavior.

### TP-15: Eliminate copy-paste test setup

Use helper functions or shared fixtures for repeated test setup patterns. The following patterns appear repeatedly and must be extracted:

- **FakeWorkflowResult** — the `@dataclass class FakeWorkflowResult` with `ResponseResult` and `TokenUsage` is defined multiple times across test files. Extract to a `conftest.py` fixture.
- **Config save/restore** — the pattern of saving/restoring adapter config in `setup_method`/`teardown_method` is repeated in every test class that modifies config. Extract to a fixture or context manager.
- **Mock Airtable API setup** — `mock_api_cls.return_value.table.return_value = mock_table` boilerplate appears in every Airtable load test. Use a class-level fixture.

### TP-16: Verify the behavior you claim to test

If a test is named `test_input_field_mapping`, it must verify that field mapping actually transformed the column names — not just that `spec.prompts` is non-empty. If a test is named `test_write_without_usage`, it must verify that usage fields are absent — not just that the write succeeded.

### TP-17: Every fix needs a regression test

Every bug fix or review fix must include at least one test that reproduces the original failure. If the fix is a defensive change (e.g., `None` default instead of empty string, or adding shared validation), the test must exercise the edge case that motivated it. A fix without a regression test is incomplete — a future refactor could silently revert the fix and the suite would not catch it.

### TP-18: Fix all lint and typecheck issues found, not just new ones

When `ruff check` or `pyright` is run, every reported issue must be fixed regardless of whether it was introduced in the current session or was pre-existing. Leaving known issues unfixed normalizes a broken baseline and makes it harder to catch regressions. If fixing a pre-existing issue is genuinely risky or out of scope, add a `# noqa` or `# type: ignore` comment with a brief justification — but silence intentionally, never by inaction.

## Adapter-Specific Patterns

### Config save/restore in unit tests

Many unit tests modify the global config singleton. Always save and restore in `setup_method`/`teardown_method`:

```python
def setup_method(self):
    from ffai_workflow_adapters.config import reload_config
    cfg = reload_config()
    self._saved = dict(cfg.adapters.excel.output_field_map)
    cfg.adapters.excel.output_field_map = {}

def teardown_method(self):
    from ffai_workflow_adapters.config import get_config
    get_config().adapters.excel.output_field_map = self._saved
```

Or use `try/finally` for one-off config changes within a single test.

### Mocking optional dependencies

`pyairtable` and `openpyxl` are optional. Mock their absence with:

```python
with patch.dict("sys.modules", {"pyairtable.api": None, "pyairtable": None}):
    with pytest.raises(TabularLoadError, match="pyairtable is required"):
        load_workflow_airtable("appBase", "Steps", api_key="key")
```

### Creating test Excel files

Use the `_create_xlsx` helper (or similar) to create test workbooks:

```python
def _create_xlsx(path: Path, headers: list[str], rows: list[list], sheet: str | None = None) -> None:
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    if sheet:
        ws.title = sheet
    ws.append(headers)
    for row in rows:
        ws.append(row)
    wb.save(path)
    wb.close()
```

### Mocking ffai types

For unit tests, construct ffai result types directly:

```python
from ffai.core.response_result import ResponseResult, TokenUsage
from dataclasses import dataclass, field

@dataclass
class FakeWorkflowResult:
    results: dict = field(default_factory=dict)
    spec_name: str = "test_workflow"
    # ... other fields as needed
```

## Integration Tests

Integration tests live in `tests/integration/` and are marked with `@pytest.mark.integration`. They:

- Call real APIs (Airtable, LLM providers)
- Require credentials in `.env`
- Are excluded from default `pytest` runs (see `pyproject.toml` markers)
- Are included when running `pytest -m ''`

Integration tests should assert structural properties (status, field existence, non-empty responses) rather than exact LLM output content, since responses are non-deterministic.

## Testing Observability / Spans

When testing code that emits OpenTelemetry spans via `_spans.adapter_span()`, use the `SpanRecorder` spy. It captures span names, attributes, and exceptions without requiring OTEL packages.

### SpanRecorder basics

```python
from ffai_workflow_adapters._spans import SpanRecorder, adapter_span

recorder = SpanRecorder()
with adapter_span("airtable.load", _recorder=recorder, base_id="app") as span:
    span.set_attribute("records.count", 5)

assert recorder.spans[0].name == "ffai.adapters.airtable.load"
assert recorder.spans[0].attributes["base_id"] == "app"
assert recorder.spans[0].attributes["records.count"] == 5
```

### ContextVar propagation for nested spans

`adapter_span` uses a `ContextVar` internally. When you pass `_recorder` to an outer span, all **nested** `adapter_span()` calls within that context automatically route to the same recorder — even if the inner code is production code that doesn't accept `_recorder` as a parameter.

This is critical for integration-style tests where a public function (e.g., `load_workflow_airtable`) calls internal functions (e.g., `ResilientCaller.call()`) that also emit spans:

```python
recorder = SpanRecorder()
with adapter_span("test_parent", _recorder=recorder):
    # load_workflow_airtable() internally calls ResilientCaller.call()
    # which calls adapter_span("resilience.call") — no _recorder param
    # But the ContextVar propagates, so the span IS captured
    load_workflow_airtable("appBase", "Steps", api_key="key")

# Both spans are captured:
load_spans = [s for s in recorder.spans if "airtable.load" in s.name]
call_spans = [s for s in recorder.spans if "resilience.call" in s.name]
assert len(load_spans) == 1
assert len(call_spans) == 1
```

### Asserting exception recording

When an exception propagates through a `SpanRecorder` span, it is recorded automatically:

```python
recorder = SpanRecorder()
with pytest.raises(ValueError):
    with adapter_span("test", _recorder=recorder):
        raise ValueError("boom")

assert len(recorder.spans[0].exceptions) == 1
assert isinstance(recorder.spans[0].exceptions[0], ValueError)
```

### Production path (no OTEL)

When `adapter_span` is called without `_recorder` and OTEL is disabled, it yields a `NoOpSpan`. Tests that don't need to inspect spans can simply call production code — spans are no-ops with zero overhead. Only use `SpanRecorder` when you need to assert span attributes.

## Known Anti-Patterns in the Current Suite

When enhancing tests, watch for these patterns that already exist:

1. **`test_airtable.py`**: `FakeWorkflowResult` is defined inline in multiple test classes instead of using a shared fixture. Config save/restore is duplicated across `TestLoadWorkflowAirtable`, `TestWriteWorkflowResults`, and `TestNamedAdapterIntegration`.
2. **`test_excel.py`**: Same `FakeWorkflowResult` pattern repeated. Config save/restore uses inconsistent patterns (some `setup_method`, some `try/finally`).
3. **Both files**: Integration tests and unit tests mock at different levels — ensure unit tests mock the external API boundary and integration tests mock nothing.
