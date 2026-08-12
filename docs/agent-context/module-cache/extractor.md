# Extractor Module Cache

Last refreshed: 2026-06-23

- Owner: `src/processor/extractor.py`.
- Runtime doc: `agents/extractor-agent.md`.
- Product playbook: `skills/update-extractor.md`.
- Source anchors: `DealData` schema validators; `EXTRACTION_PROMPT`; `SECTORS`; `SUB_SECTORS`; LLM call settings in `DealExtractor`.
- Schema: `DealData` validates sectors, sub-sectors, and deal type aliases.
- Prompt: `EXTRACTION_PROMPT` injects controlled vocabularies and asks for JSON.
- Storage coupling: new deal types may require `_roles_for_deal_type()` and `_ROLE_TO_REL` updates in `src/db/repository.py`.
- Verification: `python -m pytest tests/test_extractor_schema.py`; live LLM checks only when prompt quality is the actual change.
