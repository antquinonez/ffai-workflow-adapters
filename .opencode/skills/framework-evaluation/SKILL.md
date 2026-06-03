---
name: framework-evaluation
description: >
  Use when evaluating, rating, or comparing a codebase against other frameworks
  or libraries. Enforces evidence-based claims verified against source code.
  Triggers when the user asks to "evaluate", "rate", "compare", "score", or
  "assess" a project. Load BEFORE producing any evaluation or comparison.
license: MIT
---

# Framework Evaluation

A disciplined process for evaluating and comparing software frameworks.
Every claim must be traceable to source code.

## When to Use

- Rating a project against competitors
- Writing a comparative analysis
- Assessing maturity, architecture, or feature coverage
- Any task where "I think it does X" is not good enough

## Phase 1: Exhaustive Source Reading

**Before writing a single rating or claim**, read ALL relevant source code:

1. **Every module in the target project.** Not just `__init__.py` and
   README — read every implementation file. Use the Task tool for large
   codebases.
2. **Every test file.** Tests reveal what the code actually does, not
   what the docs say it does.
3. **Every config file.** YAML, TOML, environment variables — these
   reveal operational capabilities.
4. **Dependencies.** Check `pyproject.toml`, `package.json`, or equivalent.
   What hard vs. optional dependencies exist?

### The "did I actually read it?" test

Before claiming a system does or doesn't support a feature, ask:
"Which specific file and function did I read that proves this?" If the
answer is "I didn't read that file," you cannot make the claim.

**Never infer absence.** "I didn't see streaming support" is not the same
as "the system doesn't support streaming." You may not have read the file
that implements it.

## Phase 2: Write the Evaluation

### Required structure

1. **Introduction** — what is being evaluated, against what comparators
2. **Criteria definitions** — define each criterion before scoring
3. **Per-framework analysis** — for EACH criterion, provide:
   - The score (1-10)
   - Specific evidence (file:line references)
   - What the system does, not what you assume it does
4. **Summary table** — scores across all criteria
5. **Weighted scoring** (if requested) — with explicit weights and rationale

### Claim discipline

Every factual claim must be one of:

- **Verified**: "The system supports DAG execution — `AsyncGraphExecutor`
  at `ffai/core/async_executor.py:45` builds a topological level graph
  and executes each level via `asyncio.gather`." (file:line citation)
- **Verified absence**: "No streaming support — grep for 'stream' across
  all source files returns zero results in implementation modules."
  (negative evidence with search methodology)
- **Explicitly uncertain**: "I did not read the agent loop module and
  cannot confirm whether it supports tool calls." (honest boundary)

Never write unverified claims. If you're unsure, say so.

### Rating guidelines

| Score | Meaning |
|-------|---------|
| 1-2 | Non-existent or broken |
| 3-4 | Minimal, significant gaps |
| 5-6 | Adequate, covers basics |
| 7-8 | Strong, competitive |
| 9-10 | Industry-leading |

Scores must be justified by evidence, not vibes. A 7 requires at least
two specific capabilities that push it above a 5.

## Phase 3: Verification and Correction

After writing the evaluation, run a verification pass:

1. **Re-read every file cited** in the evaluation. Confirm line numbers
   and function signatures match what was claimed.
2. **Check for "I assumed" language.** Replace every assumption with a
   verified fact or mark it as uncertain.
3. **Grep for claimed absences.** If you said "no X support," search
   the codebase for X. You may have missed it.
4. **Read files you skipped.** If there are modules you didn't read in
   Phase 1, read them now. They may contain features that change scores.

### Correction protocol

When a user challenges a claim:

1. **Re-read the source** before responding. Do not defend a claim you
   haven't verified against code.
2. **If the challenge is correct**, produce a corrections table:

```
| Original Claim | Verification | Correction |
|---|---|---|
| "Only sequential execution" | `AsyncGraphExecutor` builds DAG with topological levels via `asyncio.gather` | System supports parallel DAG execution |
| Score: 5/10 | `PromptStep` has `condition`, `abort_condition`, `history` fields; `build_execution_graph_with_edges()` creates dependency edges | Score: 7/10 |
```

3. **Recompute all downstream scores** affected by the correction.
4. **Do not be defensive.** Wrong claims corrected early are better
   than wrong claims defended late.

## Anti-Patterns to Avoid

1. **README-driven evaluation.** Reading only docs and README without
   reading source code. Docs describe aspirations; code describes reality.
2. **Star-count bias.** Using GitHub stars or download counts as proxies
   for technical quality. These measure popularity, not capability.
3. **Anchoring on the first draft.** Writing scores quickly and then
   defending them. The first draft is a hypothesis to be tested, not a
   conclusion to be defended.
4. **Selective reading.** Reading only the modules that confirm your
   initial impression and skipping modules that might contradict it.
5. **Comparing against idealized competitors.** Rating the target project
   against its actual flaws while rating competitors against their marketing.
   Apply the same verification standard to all frameworks.

## Weighted Scoring

When the user requests weighted scoring:

1. **Define weights before scoring** — decide what matters most for the
   use case and assign percentages that sum to 100%.
2. **Show the math** — `(score * weight)` for each criterion, summed
   to a final score.
3. **Separate weights from scores** — weights reflect what the user
   cares about; scores reflect what the framework delivers. Do not
   conflate them.
4. **Explain weight choices** — one sentence per weight explaining
   why that criterion matters at that level for this evaluation.
