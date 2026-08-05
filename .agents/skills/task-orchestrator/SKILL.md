---
name: task-orchestrator
description: Use when a request should be decomposed into fresh-context worker briefs, especially broad PRDs, multi-module features, bug batches, or explicit parallel/subagent requests.
---

# Task Orchestrator Skill

Use this skill to split large work into bounded tasks. It coordinates; it does not implement feature code itself.

## Core Principle

Split by source ownership and verification boundary, not by ticket count alone.

Baseline worker read pack:

- `AGENTS.md`
- `docs/agent-context/task-routing.md`
- one relevant cache or runtime agent doc
- exact source files only after routing identifies them

## Split When

- Tasks touch different modules or owned files.
- Each worker can verify independently.
- One task is research-only and another is implementation.
- Parallel workers have disjoint write scopes.
- The user explicitly asks for subagents, parallel agents, or worker briefs.

## Do Not Split When

- Tasks edit the same function, class, config, schema, or shared helper.
- UI/API/schema/runtime invariants must stay coherent in one change.
- Two workers would likely edit the same file.
- A subtask requires broad context already loaded by the parent.

## Role Profiles

| Profile | Agent type | Assigned skill |
|---------|------------|----------------|
| `intake-triage-agent` | explorer | `prd-analyzer` |
| `codebase-explorer-agent` | explorer | `feature-researcher` |
| `feature-research-agent` | explorer | `feature-researcher` |
| `bug-fix-worker` | worker | `bug-solver` |
| `implementation-worker` | worker | `dev-executor` |
| `review-worker` | explorer | `code-reviewer` |
| `verification-worker` | worker | `python-verifier` |
| `cache-maintainer-worker` | worker | `context-cache-maintainer` |

## Spawn Policy

Use real subagents only when both are true:

- The runtime exposes `multi_agent_v1.spawn_agent`.
- The user explicitly asks for subagents, delegation, parallel agents, worker agents, agentic fan-out, or tells the workflow router to use agents for the task.

If either condition is false, do not simulate isolation. Produce the same bounded briefs under a `Fresh Session Briefs` section so the user can run them in separate sessions.

When spawning real subagents:

1. Create the task manifest first unless the user already approved immediate delegation.
2. Spawn only tasks with disjoint write scopes or read-only scopes.
3. Use `agent_type: "worker"` for bounded code edits.
4. Use `agent_type: "explorer"` for bounded read-only code questions.
5. Set `fork_context: false` by default so each worker starts from the brief, not the parent's loaded context.
6. Omit model overrides unless the user explicitly requested one or the task has a clear need.
7. Tell coding workers to edit files directly in their forked workspace and list changed paths in their final response.
8. Tell every worker that other agents or the user may be editing the repo, so it must not revert unrelated changes.
9. Do not spawn two workers that may edit the same file, function, config entry, schema, route, or shared helper.
10. After a worker finishes, review its result before trusting it.
11. Close completed agents when they are no longer needed.

## Spawn Prompt Template

Use this shape for `multi_agent_v1.spawn_agent` messages:

```text
You are a fresh-context worker in the news-scrapping repo.

Task:
<one bounded task>

Use skill:
<skill name>

Role profile:
<profile name>

Read only:
- AGENTS.md
- docs/agent-context/task-routing.md
- <one relevant module cache or runtime agent doc>
- <specific source files after routing identifies them>

Allowed write scope:
- <paths or "read-only">

Out of scope:
- <paths, modules, behavior, or live services not included>

Coordination:
- Other workers or the user may edit different files in parallel.
- Do not revert unrelated changes.
- Do not edit outside the allowed scope. If the fix requires that, stop and report the needed scope change.

Verification:
- <python -m pytest, workflow checker, targeted test, or documented live smoke>

Return:
- Root cause or approach
- Files changed
- Verification run and result
- Risks or blockers
```

## Task Manifest Format

```markdown
## Task Manifest

### Grouping Decision
- Strategy: <module/source-owner/workstream>
- Parallel-safe workers: <count>
- Sequential workers: <count and reason>
- Shared files requiring merge caution:
  - <path or none>

### Worker 1: <workstream>
- Role profile:
- Agent type:
- Skill to use:
- Primary module:
- Goal:
- Context read pack:
- Allowed write scope:
- Out of scope:
- Verification:
- Return format:
  - root cause or approach
  - files changed
  - verification result
  - risks/blockers
```

## Parent Responsibilities

- Keep worker briefs bounded.
- Avoid overlapping write scopes.
- Integrate worker results.
- Review diffs before trusting summaries.
- Run final verification or document why it could not run.

## Parent Integration Flow

1. Keep parent context limited to the manifest, spawned agent IDs, worker summaries, final diff review, and verification results.
2. While subagents run, do non-overlapping parent work only.
3. Do not redo delegated tasks unless a worker fails, returns an unsafe result, or reports a blocker.
4. When a worker completes code changes, inspect the diff for its allowed write scope.
5. Resolve conflicts in the parent only after confirming no unrelated user changes are being reverted.
6. Run `code-reviewer` on the combined result.
7. Run `python-verifier` or the documented verification plan.
8. Run `context-cache-maintainer` only when reusable source-backed findings were discovered or workflow docs changed.
