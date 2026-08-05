# Agent Workflow Cheat Sheet

Last refreshed: 2026-06-23

## Default Funnel

```text
AGENTS.md -> task-routing.md -> one cache/doc -> exact source files -> pytest/checker -> optional live smoke -> optional cache update
```

If the first cache/doc gives the owner file and verification path, skip the paired runtime doc. Pull deep references from `docs/reference/` only for cross-module or architecture-level questions.

## Feature Path

```text
task-routing.md -> prd-analyzer -> feature-researcher Approved Plan -> dev-executor -> python-verifier -> code-reviewer
```

## Bug Path

```text
task-routing.md -> one module cache -> bug-solver -> source trace -> root-cause fix -> python-verifier -> code-reviewer
```

## Review Path

```text
git diff/status -> one relevant cache -> code-reviewer -> findings first
```

## Workflow Docs Path

```text
task-routing.md -> exact workflow files -> context-cache-maintainer -> python scripts/check_agent_workflow.py
```

## Cache Update Decision

Update cache when a task proves a reusable source-backed fact:

- owner file changed
- API, schema, query, payload, or queue convention changed
- repeated debugging path or gotcha was discovered
- documented cache entry was stale
- verification command changed

Do not cache one-off task logs or speculation.
