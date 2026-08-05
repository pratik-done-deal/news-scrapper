# Task Routing

Last refreshed: 2026-06-23

Use this file first. It exists to prevent rereading every doc and every source file.

If a cache file's `Last refreshed` date is more than 30 days old, treat it as advisory. Verify against source before editing and refresh it when practical.

Use `one cache/doc` literally: read the first routed file, then move to exact source when it identifies the owner. Read the paired runtime agent doc only when the cache is stale, incomplete, or the task needs deeper behavior context.

## Minimal Read Paths

- Broad product or pipeline question -> `docs/reference/project-context.md`; use `docs/agent-context/codebase-map.md` instead when source routing is the main need.
- Repo structure, run commands, or trace order -> `docs/agent-context/codebase-map.md`.
- Testing expectations, Python style, architecture rules, safety rules -> `docs/agent-context/development-guidelines.md`.
- Shared runtime, DB schema, LLM prompt, API trigger, multiprocessing, or scraper base behavior -> `docs/agent-context/high-risk-files.md`.
- Add or debug news source scraping -> `module-cache/scraper.md`; add `agents/scraper-agent.md` only if deeper runtime behavior is needed.
- Filter keyword tuning or false positives/negatives -> `module-cache/filter.md`; add `agents/filter-agent.md` only if deeper runtime behavior is needed.
- Deal schema, prompt, sectors, sub-sectors, or deal type changes -> `module-cache/extractor.md`; add `agents/extractor-agent.md` only if deeper runtime behavior is needed.
- Neo4j writes, company normalization, relationships, constraints -> `module-cache/storage.md`; add `agents/storage-agent.md` only if deeper runtime behavior is needed.
- FastAPI routes, schemas, query functions, scrape trigger jobs -> `module-cache/api.md`; add `agents/api-agent.md` only if deeper runtime behavior is needed.
- Producer/consumer pipeline, queues, date range dispatch, process lifecycle -> `module-cache/pipeline.md`; add `agents/pipeline-agent.md` only if deeper runtime behavior is needed.
- Multiple independent tasks, broad PRD, parallel workers, real subagent spawning, or fresh-session briefs -> `.agents/skills/task-orchestrator/SKILL.md`.

## Intent Map

| User wording | First context file |
|--------------|--------------------|
| scraper, source, site, article links, date parser, trafilatura | `module-cache/scraper.md` |
| keyword, relevant, false positive, false negative, M&A filter | `module-cache/filter.md` |
| Groq, LLM, extraction, prompt, sector, sub-sector, deal type | `module-cache/extractor.md` |
| Neo4j, Cypher, company, relationship, duplicate URL, graph schema | `module-cache/storage.md` |
| endpoint, FastAPI, route, response, schema, query, Swagger | `module-cache/api.md` |
| multiprocessing, queue, worker, producer, consumer, date range run | `module-cache/pipeline.md` |
| task understanding, PRD, Jira, plan, implementation, testing | `.agents/skills/prd-analyzer/SKILL.md`, then `.agents/skills/feature-researcher/SKILL.md` |
| subagent, spawn agent, delegate, parallel agent, worker agent, fresh session brief | `.agents/skills/task-orchestrator/SKILL.md` |
| bug, stack trace, regression, broken behavior | `.agents/skills/bug-solver/SKILL.md` |
| review, diff, PR, quality check | `.agents/skills/code-reviewer/SKILL.md` |
| test, pytest, verification, smoke check | `.agents/skills/python-verifier/SKILL.md` |

## Search Discipline

- Run broad source search only after this routing file and the smallest relevant cache fail to identify owner files.
- Start with one precise query containing a concrete class, method, endpoint, field, source key, or error string.
- Limit search to the relevant module path when possible.
- Stop reading context once the owner file, helper, schema, query, or route is known.

## Stop Rules

Stop context reading and move to source when:

- You found the exact file and function that owns the behavior.
- You found the exact module cache or runtime agent doc for the task.
- You found the exact playbook in `skills/`.
- You found a high-risk file whose blast radius must be checked before editing.

Do not read a second cache file unless the task crosses module boundaries.
