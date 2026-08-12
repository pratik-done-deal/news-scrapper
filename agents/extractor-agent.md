# Extractor Agent

## Role
Uses an LLM (Gemini / gemini-3.5-flash-lite) to extract structured deal data from M&A and funding articles. Only called after the Filter Agent confirms an article is relevant.

## Context
- Lives in `src/processor/extractor.py`.
- Class: `DealExtractor`. Initialized with a client and model name. The client comes from `create_llm_client` (`src/llm_client.py`), which wraps the `google-genai` SDK in a chat-completions-shaped adapter — the call shape is unchanged from the Groq client it replaced.
- Runs in the consumer (P2) subprocess.
- Output is validated and normalized by `DealData` (Pydantic v2 model).
- Article content is truncated to 4000 chars at call time.

## LLM Settings

| Setting | Value | Reason |
|---------|-------|--------|
| Model | `gemini-3.5-flash-lite` | Set in `config/settings.yaml` (`groq.model` — the block keeps its old name so existing command lines stay valid) |
| `temperature` | `0.1` | Minimizes hallucination on structured fields |
| `response_format` | `{"type": "json_object"}` | Forces valid JSON output |

## Output Schema — `DealData`

| Field | Type | Notes |
|-------|------|-------|
| `buyer` | `str \| None` | Acquirer or investors (comma-separated if multiple). Legal suffixes stripped by prompt instruction. |
| `seller` | `str \| None` | Target company or funded startup |
| `deal_value` | `str \| None` | As stated in article (e.g. `"₹18,000 crore"`, `"$220 million"`) |
| `sector` | `str \| None` | Validated against `SECTORS`; unknown values → `"Others"` |
| `sub_sector` | `str \| None` | Required only when sector is D2C, Fintech, or Others |
| `country` | `str \| None` | Primary deal country |
| `deal_type` | `str \| None` | `acquisition \| merger \| funding_round \| joint_venture \| divestiture \| partnership \| other` |
| `summary` | `str \| None` | 2–3 sentence analyst summary including deal status (announced vs. closed) |

All fields are `None` if the article is not about a deal.

## Skills

### `extract(title, content) → DealData | None`
Calls the LLM and returns a validated `DealData` object. Returns `None` on any error.

## Prompt Engineering Notes
- `EXTRACTION_PROMPT` has 5 labeled examples covering: closed acquisition, announced/pending acquisition, funding round, PE fund close, and non-deal news. Always add an example when introducing a new deal type.
- The LLM is explicitly instructed to extract **announced but not yet closed** deals — do not remove this instruction.
- Field validators in `DealData` normalize output: case-insensitive sector matching, `"funding" → "funding_round"` alias.

## Adding a New Sector
1. Add to `SECTORS` (or `SUB_SECTORS`) in `extractor.py`.
2. `validate_sector` / `validate_sub_sector` validators auto-handle via case-insensitive matching.
3. Update the prompt template — it interpolates `{sectors}`, `{d2c_sub}`, `{fintech_sub}`, `{others_sub}`.

## Adding a New Deal Type
1. Add the value to the `allowed` set in `DealData.normalise_deal_type`.
2. Update `_roles_for_deal_type()` in `src/db/repository.py` if the buyer/seller role mapping differs.
3. Add a labeled example to `EXTRACTION_PROMPT`.
