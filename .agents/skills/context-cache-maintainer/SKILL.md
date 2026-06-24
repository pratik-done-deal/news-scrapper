---
name: context-cache-maintainer
description: Use when updating, pruning, or correcting docs/agent-context after source-backed findings or workflow-doc changes.
---

# Context Cache Maintainer Skill

## Update Rules

Update cache only when the finding is reusable:

- owner file or route changed
- API, schema, Cypher, queue, payload, config, or prompt convention changed
- repeated debugging path or gotcha was discovered
- verification command changed
- cache entry was proven stale by source

Do not cache one-off bug notes, temporary branch assumptions, speculation, or task logs.

## Workflow

1. Read the smallest affected cache file.
2. Read exact source evidence.
3. Patch the smallest useful entry.
4. Refresh `Last refreshed: YYYY-MM-DD`.
5. Run `python scripts/check_agent_workflow.py`.

## Required Output

- Cache file changed
- Source evidence used
- What future duplicate search this prevents
- Verification performed
