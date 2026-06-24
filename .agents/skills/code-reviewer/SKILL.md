---
name: code-reviewer
description: Use for review, diff review, pre-PR review, or checking implementation quality.
---

# Code Reviewer Skill

## Workflow

1. Follow `.agents/skills/README.md` shared baseline, except start from the diff.
2. Inspect `git status --short`, `git diff HEAD`, and staged diff when relevant.
3. Read one relevant cache based on changed paths.
4. Check correctness, regression risk, missing tests, security, env leakage, Cypher parameterization, API schema compatibility, and live dependency assumptions.

## Output Format

Start with one verdict:

- Blocking issues found
- Non-blocking issues only
- No issues found

Then list:

1. Blocking issues with file and line references
2. Non-blocking issues
3. Test gaps and residual risk
4. Suggested verification

Do not rewrite code unless the user explicitly asks for fixes.
