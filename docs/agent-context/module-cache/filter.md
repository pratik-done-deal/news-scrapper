# Filter Module Cache

Last refreshed: 2026-06-23

- Owner: `src/processor/filter.py`.
- Runtime doc: `agents/filter-agent.md`.
- Product playbook: `skills/update-filter.md`.
- Source anchors: `NewsFilter.is_ma_funding_relevant()`; title keyword list; content keyword list; `CONTENT_MIN_MATCHES`.
- Main API: `NewsFilter.is_ma_funding_relevant(title, content)`.
- Behavior: one title match is enough; content requires `CONTENT_MIN_MATCHES`.
- Verification: `python -m pytest tests/test_filter.py`; optional live comparison with `python validate_filter.py`.
