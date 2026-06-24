---
name: dev-executor
description: Use when implementing an approved feature or scoped code change after requirements, approach, target files, and verification are known.
---

# Dev Executor Skill

Use this skill for implementation.

## Fast Path

Skip a full approved plan only when:

- target files are already known
- requested behavior is explicit
- change stays inside one module
- no schema, API, env, migration, or prompt-policy decision is needed
- verification is clear

State the fix path before editing.

## Workflow

1. Follow `.agents/skills/README.md` shared baseline.
2. Run `git status --short`.
3. Read target files before editing.
4. Keep edits inside the approved scope.
5. Add or update offline tests for changed behavior when practical.
6. Run `python -m pytest`.
7. Run targeted live smoke checks only when needed and env/network dependencies are available.

## Implementation Order

1. Constants/config/schema.
2. Pure helpers and validators.
3. Runtime module behavior.
4. DB/API boundary.
5. CLI or route wiring.
6. Tests.
7. Docs/cache updates if reusable findings changed.

## Required Output

- Files changed and why
- Behavior implemented
- Verification command and result
- Out-of-scope items
- Residual risks
