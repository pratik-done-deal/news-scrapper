import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

# Whole-word patterns to avoid false matches on short terms
_WORD_PATTERNS: list[re.Pattern] = [re.compile(p, re.IGNORECASE) for p in [
    r"\bacquir(ed|es|ing|er|ers|ition|itions)\b",
    r"\bmerger(s)?\b", r"\bmerged\b", r"\bmerging\b",
    r"\bamalgamat(ed|ion|ing)\b",
    r"\btakeover(s)?\b", r"\btake-over(s)?\b",
    r"\bbuyout(s)?\b", r"\bbuy-out(s)?\b",
    r"\bdivest(ed|ing|iture|itures|ment|ments)?\b",
    r"\bspin-?off(s)?\b",
    r"\bcarve-?out(s)?\b",
    r"\bdemerger(s)?\b", r"\bde-merger(s)?\b",
    r"\blbo\b", r"\bmbo\b",
]]

# Phrase keywords — long enough to be unambiguous, matched as substrings
_PHRASE_KEYWORDS: list[str] = [
    # Funding rounds
    "funding round", "seed round", "pre-seed round",
    "series a", "series b", "series c", "series d", "series e", "series f",
    "growth equity", "growth round", "bridge round",
    "raised $", "raised rs", "raised ₹",
    # Deal vehicles
    "private equity", "venture capital",
    "pe-backed", "vc-backed", "pe firm", "vc firm",
    # Deal types
    "joint venture", "leveraged buyout", "management buyout",
    "tender offer", "open offer",
    "hostile bid", "hostile takeover",
    "friendly bid", "friendly acquisition",
    "strategic acquisition", "strategic investment",
    # Stake transactions
    "majority stake", "minority stake", "controlling stake",
    "stake acquisition", "stake sale", "stake purchase",
    "promoter stake", "promoter sell", "promoter divest",
    # Asset / business transactions
    "asset sale", "asset purchase", "asset acquisition",
    "business transfer", "slump sale",
    "sells its", "sold its", "buying out",
    # Deal closure language
    "definitive agreement", "binding agreement",
    "term sheet", "letter of intent", "loi signed",
    "deal signed", "deal closed", "deal valued",
    "deal worth", "deal at $", "deal at rs", "deal at ₹",
    "transaction valued", "transaction worth",
    "transaction closed", "transaction signed",
    # India-specific regulatory / deal triggers
    "nclt approv", "nclt order",
    "sebi open offer", "sebi approv",
    "preferential allotment",
    "compulsory open offer",
    # Consolidation / restructuring
    "consolidation deal", "sector consolidat",
    "business consolidat", "industry consolidat",
    # PE / VC investment language
    "invested in", "invests in",          # kept narrow by pairing with stake/deal context below
    "portfolio acquisition", "portfolio company",
    "exit stake", "exit investment",
    "secondary stake", "secondary sale",
]


def _count_matches(text: str) -> tuple[int, list[str]]:
    """Return (match_count, matched_terms) for all M&A keywords found in text."""
    matched: list[str] = []
    for pattern in _WORD_PATTERNS:
        m = pattern.search(text)
        if m:
            matched.append(m.group())
    lower = text.lower()
    for phrase in _PHRASE_KEYWORDS:
        if phrase in lower:
            matched.append(phrase)
    return len(matched), matched


class NewsFilter:
    # A title is short and specific — one match is enough.
    # Content is long and can contain incidental mentions, so require at least 2.
    CONTENT_MIN_MATCHES = 2

    def is_ma_relevant(self, title: Optional[str], content: Optional[str]) -> bool:
        if title:
            count, terms = _count_matches(title)
            if count >= 1:
                logger.debug(f"MA match on title: {terms}")
                return True

        if content:
            count, terms = _count_matches(content)
            if count >= self.CONTENT_MIN_MATCHES:
                logger.debug(f"MA match on content ({count} signals): {terms}")
                return True
            if count == 1:
                logger.debug(f"MA content match ignored (only 1 signal — likely incidental): {terms}")

        logger.debug("No MA keywords found — skipping article")
        return False
