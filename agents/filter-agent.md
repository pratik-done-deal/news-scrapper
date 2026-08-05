# Filter Agent

## Role
Fast keyword-based gate that decides whether an article is about M&A activity or a funding round. Runs in the consumer (P2) subprocess. No LLM calls — pure string matching.

## Context
- Lives in `src/processor/filter.py`.
- Class: `NewsFilter`.
- Called once per article after it is saved to the database.
- Result stored as `Article.is_ma_funding_relevant` (bool) in Neo4j.

## Algorithm

```
1. Check title against all patterns.
   → Any 1 match: article is RELEVANT. Stop.

2. Check content against all patterns.
   → ≥ 2 matches: article is RELEVANT.
   → 1 match: treated as incidental — NOT relevant.
   → 0 matches: NOT relevant.
```

## Keyword Layers

| Variable | Strategy | Example |
|----------|----------|---------|
| `_WORD_PATTERNS` | `re.compile` with `\b` word boundaries, `re.IGNORECASE` | `r"\bacquir(ed\|es\|ing)\b"` |
| `_PHRASE_KEYWORDS` | Lowercase substring, checked via `text.lower()` | `"series a"`, `"majority stake"` |

## Skills

### `is_ma_funding_relevant(title, content) → bool`
Returns `True` if the article meets the relevance threshold. Logs matched terms at DEBUG level.

## Tuning the Filter

**More recall (catch more articles):** Add new patterns to `_WORD_PATTERNS` or `_PHRASE_KEYWORDS`, or lower `CONTENT_MIN_MATCHES` to 1.

**More precision (fewer false positives):** Make phrases more specific, or raise `CONTENT_MIN_MATCHES` to 3.

After any change, run `python validate_filter.py` to smoke-test.
