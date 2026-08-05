---
name: prd-analyzer
description: Use when analyzing a task, PRD, ticket, screenshot, or product note before implementation planning.
---

# PRD Analyzer Skill

Use this skill for task understanding before implementation.

## Workflow

1. Follow `.agents/skills/README.md` shared baseline.
2. Identify the user goal, affected runtime module, and likely files.
3. Separate facts from assumptions.
4. Map current behavior to target behavior.
5. Ask clarifying questions only when ambiguity could change schema, API contract, data writes, scraping scope, or verification.
6. Produce acceptance criteria and risks.

## Required Output

- Brief task summary
- Source material reviewed
- Affected modules and likely files
- Before vs after behavior
- Open questions or explicit assumptions
- Draft acceptance criteria
- Verification expectations

Do not edit files in this skill.
