"""The company-DB watchlist: which companies a news run is restricted to.

Two jobs, matching the two ways a source can be scoped to our entities:

- `build_entries()` turns company-DB rows into search terms for sources that
  expose an on-site search (`search_url` in `config/sources.yaml`).
- `WatchlistMatcher` gates articles from sources that don't, keeping only the
  ones that actually mention a tracked company.

Search terms prefer the brand over the registered entity: news coverage says
"Swiggy", never "Bundl Technologies Private Limited". Where no brand exists,
the legal suffix is stripped ("Nestle India Limited" -> "Nestle India") with
`strip_legal_suffix()`, which leaves casing alone.
"""

import logging
import re
from dataclasses import dataclass
from typing import Iterable, Optional

from ..db.names import strip_legal_suffix

logger = logging.getLogger(__name__)

DEFAULT_MIN_TERM_LENGTH = 3

# Terms this short or generic match half the news wire, so they are never used
# as an entity gate on their own.
_STOP_TERMS = {"the", "and", "for", "new", "one", "group", "india", "limited", "company"}

_TOKEN_RE = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class WatchlistEntry:
    """One tracked company, with the string we will actually search for."""

    entity_type: str
    entity_id: int
    company_name: str
    brand_name: Optional[str]
    website: Optional[str]
    search_term: str


def derive_search_term(row: dict) -> str:
    """Brand name when the company DB has one, otherwise the registered name
    with its legal suffix stripped."""
    brand = (row.get("brand_name") or "").strip()
    if brand:
        return brand
    return strip_legal_suffix(row.get("company_name") or "")


def build_entries(
    rows: Iterable[dict],
    min_term_length: int = DEFAULT_MIN_TERM_LENGTH,
) -> list[WatchlistEntry]:
    """Turn company-DB rows into deduplicated watchlist entries.

    Rows collapsing to the same search term (a seller and a lead for the same
    company, say) produce one entry — searching the term twice would just fetch
    the same articles again. The first row wins, and `fetch_entities()` orders
    by name, so the choice is stable across runs.
    """
    entries: list[WatchlistEntry] = []
    seen: set[str] = set()
    skipped = 0

    for row in rows:
        term = derive_search_term(row)
        key = term.casefold()
        if len(term) < min_term_length or key in _STOP_TERMS:
            skipped += 1
            continue
        if key in seen:
            continue
        seen.add(key)
        entries.append(
            WatchlistEntry(
                entity_type=row["entity_type"],
                entity_id=row["entity_id"],
                company_name=row["company_name"],
                brand_name=row.get("brand_name"),
                website=row.get("website"),
                search_term=term,
            )
        )

    if skipped:
        logger.info(f"Watchlist: skipped {skipped} entity name(s) too short or too generic to search")
    return entries


def build_gate_terms(
    rows: Iterable[dict],
    min_term_length: int = DEFAULT_MIN_TERM_LENGTH,
) -> list[str]:
    """Every name a tracked company might be called in an article.

    Wider than `build_entries()` on purpose. A search runs once per company, so
    it uses the single best term; the gate only decides whether an article is
    about a tracked company, so it should recognise the registered name *and*
    the brand — a story can say "Bundl Technologies" without ever saying
    "Swiggy".
    """
    terms: list[str] = []
    seen: set[str] = set()

    for row in rows:
        for raw in (row.get("brand_name"), row.get("company_name")):
            term = strip_legal_suffix(raw or "")
            key = term.casefold()
            if len(term) < min_term_length or key in _STOP_TERMS or key in seen:
                continue
            seen.add(key)
            terms.append(term)
    return terms


class WatchlistMatcher:
    """Decides whether an article mentions any tracked company.

    `NewsFilter` scans every keyword pattern over every article, which is fine
    for ~100 M&A keywords but not for thousands of company names. This indexes
    terms by their first token instead: an article's tokens are collected once,
    and only the terms whose first token is present get a full check. Matching
    is case-insensitive and word-boundary anchored, so "Ola" does not match
    "Olive" and "Zepto" does not match "Zeptolab".
    """

    def __init__(self, terms: Iterable[str]) -> None:
        self._patterns: dict[str, list[tuple[str, re.Pattern]]] = {}
        self._terms: list[str] = []

        for term in terms:
            tokens = _TOKEN_RE.findall(term.casefold())
            if not tokens:
                continue
            pattern = re.compile(
                r"(?<![A-Za-z0-9])" + r"[^A-Za-z0-9]+".join(re.escape(t) for t in tokens) + r"(?![A-Za-z0-9])",
                re.IGNORECASE,
            )
            self._patterns.setdefault(tokens[0], []).append((term, pattern))
            self._terms.append(term)

    def __len__(self) -> int:
        return len(self._terms)

    @property
    def terms(self) -> list[str]:
        return list(self._terms)

    def match(self, title: Optional[str], content: Optional[str]) -> list[str]:
        """Every tracked company mentioned in the article, in no useful order."""
        text = " ".join(part for part in (title, content) if part)
        if not text or not self._patterns:
            return []

        candidates = {
            token: self._patterns[token]
            for token in set(_TOKEN_RE.findall(text.casefold()))
            if token in self._patterns
        }
        if not candidates:
            return []

        matched: list[str] = []
        for entries in candidates.values():
            for term, pattern in entries:
                if pattern.search(text):
                    matched.append(term)
        return matched


def gate_articles(
    articles: list[dict],
    matcher: WatchlistMatcher,
) -> tuple[list[dict], int]:
    """Keep only the articles that mention a tracked company.

    Kept articles gain a `matched_entities` key naming the companies found, so
    the caller can log or store why the article survived. Returns
    `(kept, dropped_count)`.
    """
    kept: list[dict] = []
    for article in articles:
        matches = matcher.match(article.get("title"), article.get("content"))
        if matches:
            kept.append({**article, "matched_entities": matches})
    return kept, len(articles) - len(kept)
