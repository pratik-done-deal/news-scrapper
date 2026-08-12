# Agent Context

This directory stores compact, repo-local context for development agents. `AGENTS.md` owns the policy; `task-routing.md` owns first-hop routing and stop rules. Deep architecture references live in `docs/reference/` and should not be part of the default read path.

Good entries answer routing questions, not whole-directory summaries:

- source or task wording -> first context file
- module -> owner files and gotchas
- high-risk file -> blast radius
- verification need -> command

Current files:

- `task-routing.md`: first-stop task-to-context lookup and stop rules.
- `codebase-map.md`: repository structure, runtime pipeline, and trace order.
- `development-guidelines.md`: Python style, testing expectations, and safety rules.
- `high-risk-files.md`: files with broad blast radius.
- `agent-workflow-cheatsheet.md`: quick paths for feature, bug, review, and docs tasks.
- `module-cache/`: mutable module-specific findings.

Scaling rule:

- New runtime module -> add one small `module-cache/<module>.md`.
- New repeated task -> add one focused playbook under `skills/`.
- New high-blast-radius file -> update `high-risk-files.md`.
- New runtime/domain role -> add or update one `agents/*-agent.md`.
- Cross-module architecture change -> update `docs/reference/project-context.md`.

Useful future agents/skills for this product:

- `source-health-agent`: scraper layout drift, empty extraction, date parser failures.
- `extraction-eval-agent`: golden article set, LLM prompt/schema quality checks.
- `graph-quality-agent`: Neo4j duplicates, missing relationships, company normalization regressions.
- `source-onboarding-skill`: source config, registry, parser tests, and live smoke checklist.
- `api-contract-agent`: route/schema/query compatibility and response contract review.
- `pipeline-ops-agent`: queue lifecycle, retries, reprocess scripts, and operational failure modes.

Use `scripts/check_agent_workflow.py` after workflow-doc or context-cache structure changes.
