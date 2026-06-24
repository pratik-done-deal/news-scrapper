# Skill: Update Deal Extraction Logic

## When to Use
When adding new deal types, sectors, sub-sectors, or improving LLM output quality.

## Key Files
- `src/processor/extractor.py` — prompt, schema, validators
- `src/db/repository.py` — relationship mapping for new deal types

---

## Add a New Deal Type

1. Add the value to `allowed` in `DealData.normalise_deal_type`:
   ```python
   allowed = {
       "acquisition", "merger", "funding_round",
       "joint_venture", "divestiture", "partnership",
       "other",
       "your_new_type",   # add here
   }
   ```

2. If the new type has a non-standard buyer/seller role, update `_roles_for_deal_type()` in `src/db/repository.py`:
   ```python
   def _roles_for_deal_type(deal_type):
       if deal_type == "funding_round":
           return "investor", "company"
       if deal_type == "your_new_type":
           return "buyer", "seller"   # or whatever roles apply
       return "buyer", "seller"
   ```

3. If a new relationship type is needed, add it to `_ROLE_TO_REL` in `repository.py`:
   ```python
   _ROLE_TO_REL = {
       ...
       "your_role": "YOUR_REL_TYPE",
   }
   ```

4. Add a labeled example to `EXTRACTION_PROMPT` following the existing format.

---

## Add a New Sector

1. Add to `SECTORS` list in `extractor.py`.
2. The `validate_sector` validator handles unknown values via case-insensitive matching (falls back to `"Others"`).
3. Update the prompt — it injects `{sectors}` into the template:
   ```python
   SECTORS = [..., "Your New Sector"]
   ```

## Add a New Sub-Sector

1. Add to the appropriate key in `SUB_SECTORS` dict.
2. The `validate_sub_sector` validator handles it automatically.
3. If the new sector has sub-sectors, add its key to `SUB_SECTORS` and add a `{your_sub}` reference to the prompt template.

---

## Improve LLM Output Quality

- Add more labeled examples to `EXTRACTION_PROMPT`. The model relies on examples more than instructions.
- If a specific field is consistently wrong, add a validator in `DealData` to normalize it.
- Keep `temperature=0.1` and `response_format={"type": "json_object"}` — changing these degrades reliability.
- Content truncation is at 4000 chars. Raise it only if the model supports a larger context window.
