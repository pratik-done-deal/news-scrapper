# Skills

Use this directory for development workflow playbooks. Product-specific runtime playbooks remain in `skills/`.

## Shared Baseline

Every skill inherits this baseline unless it says otherwise:

1. Read `AGENTS.md` unless it is already present in the active context.
2. Read `docs/agent-context/task-routing.md`.
3. Read one relevant context/cache file, then stop cache reading once the owner is known.
4. Read the exact source or workflow file before editing it.
5. Search only narrowed paths from the cache or owner docs.
6. Do not revert unrelated user changes.
7. Verify with `python -m pytest` for code changes and `python scripts/check_agent_workflow.py` for workflow-doc changes.

## Ownership

- `prd-analyzer`: task/ticket/source-material understanding. No code edits.
- `feature-researcher`: source-backed implementation plan. No code edits.
- `dev-executor`: scoped implementation after requirements, owner files, and verification are known.
- `bug-solver`: root-cause debugging and fix.
- `code-reviewer`: diff review. Findings first.
- `python-verifier`: test and smoke-check selection.
- `task-orchestrator`: decomposition and worker briefs for broad work.
- `context-cache-maintainer`: source-backed cache updates.

## Subagent Delegation

Use `task-orchestrator` before spawning any subagents. Real subagents may be spawned only when the runtime exposes `multi_agent_v1.spawn_agent` and the user explicitly asks for subagents, delegation, parallel agents, worker agents, or agentic fan-out.

Default delegation rules:

- Split by source ownership and verification boundary.
- Give each coding worker a disjoint write scope.
- Use worker agents for bounded edits and explorer agents for bounded read-only questions.
- Use `fork_context: false` by default.
- Do not spawn workers that may edit the same file, config entry, schema, route, helper, or function.
- If real subagents are unavailable or not explicitly authorized, produce Fresh Session Briefs instead.
