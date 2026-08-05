---
name: feature-researcher
description: Use when researching how to implement a feature and producing an approved source-backed plan before editing.
---

# Feature Researcher Skill

Use this after requirements are understood and before implementation.

## Workflow

1. Follow `.agents/skills/README.md` shared baseline.
2. Read the relevant module cache and exact source entry points.
3. Find up to three comparable local patterns.
4. Map data flow through config, runtime module, DB/API schema, and verification boundary.
5. Compare two or three approaches when there is a real choice.
6. Recommend one approach grounded in existing code.

## Required Output

Return an implementation plan with:

- Affected modules and files
- Approach comparison
- Chosen approach
- Backend/API/schema/env dependencies
- Risks and edge cases
- Verification plan

Use this handoff block:

```markdown
## Approved Plan
- **Module:** <module>
- **Approach:** <chosen approach>
- **Files to change:** <list>
- **Steps:**
  - [ ] Step 1
  - [ ] Step 2
```

Do not edit files in this skill.
