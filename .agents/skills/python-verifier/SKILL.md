---
name: python-verifier
description: Use when selecting and running verification for Python code, docs, workflow changes, API routes, scraper changes, or pipeline behavior.
---

# Python Verifier Skill

## Standard Commands

```bash
python -m pytest
python scripts/check_agent_workflow.py
```

## Optional Live Smoke Checks

Run only when required and dependencies are available:

```bash
python validate_filter.py
python test_date_range.py --start-date 2025-02-01 --end-date 2025-02-28 --max-pages 3
python main.py --start-date 2025-01-01 --end-date 2025-01-02
python api_server.py
```

## Workflow

1. Pick the smallest useful verification.
2. Prefer offline tests for normal development.
3. Do not invent passing live checks when env vars, network, the LLM API, or Neo4j are unavailable.
4. If pytest is missing, report it and install only with user/network approval.
5. For failures, classify syntax/import, unit assertion, env, network, or dependency issue.

## Required Output

- Commands run
- Result
- Skipped checks with reasons
- Remaining risk
