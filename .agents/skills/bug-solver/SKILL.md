---
name: bug-solver
description: Use when debugging broken behavior, stack traces, regressions, API errors, scraper failures, extraction issues, or pipeline hangs.
---

# Bug Solver Skill

## Workflow

1. Follow `.agents/skills/README.md` shared baseline.
2. Inspect current diff first with `git status --short`.
3. Classify the bug: scraper, filter, extractor, storage, API, pipeline, config, env, or test harness.
4. Trace root cause from entry point to failing function.
5. Map blast radius with scoped `rg`.
6. Add or identify a regression test first when practical.
7. Fix the root cause, not just the symptom.
8. Verify with `python -m pytest` and any targeted smoke check required by the bug.

## Required Output

- Root cause
- Files changed
- Blast radius checked
- Regression coverage or manual check
- Verification result
- Similar patterns found or not found
