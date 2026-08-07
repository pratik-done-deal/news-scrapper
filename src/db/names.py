"""Company name normalisation shared by the Neo4j storage layer and the
company-DB watchlist.

Two callers with different needs sit on the same suffix-stripping rule:

- `repository.py` needs a canonical form for identity — `_company_id()` keys a
  UUID5 on it, so its output must stay byte-for-byte stable across releases.
- The watchlist needs a *search* term, where title-casing is harmful:
  "BYJU'S" must not become "Byju'S" before it is typed into a site search.

`strip_legal_suffix()` serves the second, `normalize_company_name()` layers the
title-casing on top for the first.
"""

import re

# Legal entity suffixes to strip before company name comparison/storage.
# Order matters: longer patterns must appear before shorter overlapping ones.
LEGAL_SUFFIX_RE = re.compile(
    r"[\s,.]*(pvt\.?\s*ltd\.?|private\s+limited|public\s+limited"
    r"|co\.\s*ltd\.?|co\.\s*limited"
    r"|limited|ltd\.?|inc\.?|incorporated|corp\.?|corporation"
    r"|llp|llc|gmbh|plc|l\.l\.c\.?|l\.l\.p\.?)[\s.]*$",
    re.IGNORECASE,
)


def strip_legal_suffix(name: str) -> str:
    """Drop trailing legal-entity suffixes and collapse whitespace.

    Casing is left alone: this is what a site search should be given.

    Applied repeatedly, because registered names stack suffixes: "Zoho
    Corporation Private Limited" needs two passes to reach "Zoho". Stripping
    once leaves "Zoho Corporation", which would key a *different* Company node
    from the "Zoho" an article names — the deals would attach to one node and
    the Done Deal reference to the other, and the news feed would come back
    empty. The loop ends when a pass changes nothing.
    """
    name = name.strip()
    while True:
        stripped = LEGAL_SUFFIX_RE.sub("", name).strip().rstrip(",").strip()
        if stripped == name:
            break
        name = stripped
    return re.sub(r"\s+", " ", name)


def normalize_company_name(name: str) -> str:
    """Return a canonical company name by stripping legal suffixes and normalizing whitespace.

    Title-cased, so name variants collapse to one identity. `_company_id()`
    hashes this — changing the output re-keys every existing Company node.
    """
    return strip_legal_suffix(name).title()
