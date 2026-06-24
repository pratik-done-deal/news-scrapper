# Skill: Update M&A / Funding Filter Keywords

## When to Use
When the filter is missing deal types that should be relevant, or catching too many unrelated articles.

## Files
- `src/processor/filter.py`
- `validate_filter.py` — run this after changes

## Adding a Keyword

### Single-word terms → `_WORD_PATTERNS`
Add a compiled regex with `\b` word boundaries:
```python
_WORD_PATTERNS = [...,
    re.compile(r"\byour_term(s|ing|ed)?\b", re.IGNORECASE),
]
```

### Multi-word phrases → `_PHRASE_KEYWORDS`
Add a lowercase string (matched as substring against `text.lower()`):
```python
_PHRASE_KEYWORDS = [...,
    "your phrase here",
]
```

Make phrases long enough to be unambiguous. Short terms like `"invested"` will cause false positives.

## Adjusting the Threshold
`NewsFilter.CONTENT_MIN_MATCHES` controls how many matches are required in the article body:
- Default: `2`
- Lower to `1` to increase recall (catch more articles, risk more false positives)
- Raise to `3` for higher precision (fewer false positives, risk missing some deals)

The title threshold is always `1` (title matches are always specific).

## Validating
```bash
python validate_filter.py
```
Check that known M&A articles return `True` and unrelated articles return `False`.
