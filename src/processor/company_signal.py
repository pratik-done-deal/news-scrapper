import hashlib
import json
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Optional

from groq import Groq
from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)

Confidence = Literal["low", "medium", "high"]
Direction = Literal["rising", "stable", "falling"]
Polarity = Literal["positive", "negative", "neutral"]
SignalTarget = Literal["invest", "fundraise", "acquisition_target"]
SignalStrength = Literal["weak", "medium", "strong"]

_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "by", "for", "from", "in", "into",
    "is", "may", "of", "on", "or", "the", "to", "with",
}

_TOKEN_ALIASES = {
    "acquire": "acquire",
    "acquired": "acquire",
    "acquires": "acquire",
    "acquisition": "acquire",
    "buy": "acquire",
    "buys": "acquire",
    "buyout": "acquire",
    "invest": "invest",
    "invested": "invest",
    "investment": "invest",
    "raise": "fundraise",
    "raises": "fundraise",
    "funding": "fundraise",
    "fundraise": "fundraise",
    "fundraising": "fundraise",
    "talk": "talks",
    "talks": "talks",
    "discussion": "talks",
    "discussions": "talks",
}

COMPANY_SIGNAL_PROMPT = """\
You are an expert financial analyst estimating near-term company-level deal propensity from news.

Estimate the probability that the named company will do each of these within the next {horizon_days} days:
1. invest_probability: invest in, acquire, merge with, or take a stake in another company.
2. fundraise_probability: raise equity, debt, PE/VC funding, IPO-linked capital, strategic funding, or similar.
3. acquisition_target_probability: be acquired, merged, bought out, receive majority investment, or enter a control transaction.

IMPORTANT:
- These are LLM-estimated probabilities from current evidence, not statistically calibrated probabilities.
- Bias toward catching early weak signals because missed opportunities are worse than false positives.
- Still mark weak/rumor evidence as speculative or low confidence.
- Consider positive and negative signals. Negative signals can increase one score and reduce another.
- Treat duplicate articles as support for confidence, not independent events.
- Only use evidence about the named company. If another company is the actor, do not transfer that signal unless the named company is directly affected.

Return ONLY valid JSON with this exact shape:
{{
  "invest_probability": 0,
  "fundraise_probability": 0,
  "acquisition_target_probability": 0,
  "confidence": "low",
  "direction": "stable",
  "is_speculative": true,
  "positive_signals": [
    {{
      "signal_type": "expansion_plan",
      "target_score": "invest",
      "strength": "medium",
      "polarity": "positive",
      "impact": "+10",
      "source_article_id": "article-id",
      "evidence_text": "short evidence phrase"
    }}
  ],
  "negative_signals": [],
  "evidence_articles": [
    {{
      "article_id": "article-id",
      "title": "article title",
      "source": "source",
      "days_old": 3,
      "decay_weight": 1.0,
      "company_role": "fundraiser",
      "duplicate_count": 1
    }}
  ],
  "explanation": "2-4 sentence analyst-facing explanation."
}}

Company:
{company_name}

Recent deduplicated news and context:
{context_json}
"""


class SignalEvent(BaseModel):
    signal_type: str = "unknown"
    target_score: SignalTarget
    strength: SignalStrength
    polarity: Polarity
    impact: str = ""
    source_article_id: Optional[str] = None
    evidence_text: str = ""

    model_config = {"extra": "ignore"}

    @field_validator("target_score", mode="before")
    @classmethod
    def normalise_target_score(cls, value: Any) -> SignalTarget:
        normalised = str(value or "").lower().strip()
        if normalised in {"invest", "investment", "invest_probability", "acquirer", "acquire"}:
            return "invest"
        if normalised in {"fundraise", "fundraising", "fundraise_probability", "funding"}:
            return "fundraise"
        if normalised in {
            "acquisition_target",
            "acquisition_target_probability",
            "target",
            "acquired",
            "get_acquired",
        }:
            return "acquisition_target"
        return "fundraise"

    @field_validator("strength", mode="before")
    @classmethod
    def normalise_strength(cls, value: Any) -> SignalStrength:
        normalised = str(value or "").lower().strip()
        if normalised in {"strong", "high"}:
            return "strong"
        if normalised in {"medium", "moderate", "mid"}:
            return "medium"
        return "weak"

    @field_validator("polarity", mode="before")
    @classmethod
    def normalise_polarity(cls, value: Any) -> Polarity:
        normalised = str(value or "").lower().strip()
        if normalised in {"positive", "+", "up"}:
            return "positive"
        if normalised in {"negative", "-", "down"}:
            return "negative"
        return "neutral"

    @field_validator("impact", "evidence_text", mode="before")
    @classmethod
    def stringify_required_text(cls, value: Any) -> str:
        if value is None:
            return ""
        return str(value)


class EvidenceArticle(BaseModel):
    article_id: Optional[str] = None
    title: Optional[str] = None
    source: Optional[str] = None
    days_old: Optional[int] = None
    decay_weight: float = Field(ge=0, le=1)
    company_role: str = "mentioned_only"
    duplicate_count: int = Field(default=1, ge=1)

    model_config = {"extra": "ignore"}

    @field_validator("article_id", mode="before")
    @classmethod
    def stringify_article_id(cls, value: Any) -> Optional[str]:
        if value is None:
            return None
        return str(value)


class CompanySignalScore(BaseModel):
    invest_probability: int = Field(ge=0, le=100)
    fundraise_probability: int = Field(ge=0, le=100)
    acquisition_target_probability: int = Field(ge=0, le=100)
    confidence: Confidence
    direction: Direction
    is_speculative: bool
    positive_signals: list[SignalEvent] = Field(default_factory=list)
    negative_signals: list[SignalEvent] = Field(default_factory=list)
    evidence_articles: list[EvidenceArticle] = Field(default_factory=list)
    explanation: str

    model_config = {"extra": "ignore"}

    @field_validator(
        "invest_probability",
        "fundraise_probability",
        "acquisition_target_probability",
        mode="before",
    )
    @classmethod
    def clamp_probability(cls, value: Any) -> int:
        try:
            parsed = int(round(float(value)))
        except (TypeError, ValueError):
            parsed = 0
        return max(0, min(100, parsed))

    @field_validator("confidence", mode="before")
    @classmethod
    def normalise_confidence(cls, value: Any) -> Confidence:
        normalised = str(value or "").lower().strip()
        if normalised in {"high", "strong"}:
            return "high"
        if normalised in {"medium", "moderate", "mid"}:
            return "medium"
        return "low"

    @field_validator("direction", mode="before")
    @classmethod
    def normalise_direction(cls, value: Any) -> Direction:
        normalised = str(value or "").lower().strip()
        if normalised in {"rising", "up", "increasing", "increase"}:
            return "rising"
        if normalised in {"falling", "down", "decreasing", "decrease"}:
            return "falling"
        return "stable"

    @field_validator("positive_signals", "negative_signals", "evidence_articles", mode="before")
    @classmethod
    def normalise_list_fields(cls, value: Any) -> list[Any]:
        if value is None:
            return []
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            return [value]
        return []

    @field_validator("explanation", mode="before")
    @classmethod
    def stringify_explanation(cls, value: Any) -> str:
        if value is None:
            return "The model did not provide a detailed explanation."
        return str(value)


class CompanySignalSnapshot(CompanySignalScore):
    id: str
    company_id: str
    company_name: str
    horizon_days: int
    generated_at: datetime
    valid_until: datetime
    articles_analyzed: int = 0
    duplicates_collapsed: int = 0


def parse_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def news_decay_weight(published_at: Any, as_of: Optional[datetime] = None) -> float:
    published = parse_datetime(published_at)
    if published is None:
        return 0.35

    now = as_of or datetime.now(timezone.utc)
    age_days = max(0, (now - published).days)
    if age_days <= 7:
        return 1.0
    if age_days <= 15:
        return 0.65
    if age_days <= 30:
        return 0.35
    return 0.1


def days_old(published_at: Any, as_of: Optional[datetime] = None) -> Optional[int]:
    published = parse_datetime(published_at)
    if published is None:
        return None
    now = as_of or datetime.now(timezone.utc)
    return max(0, (now - published).days)


def article_fingerprint(article: dict) -> str:
    text = article.get("title") or article.get("content") or article.get("url") or article.get("id") or ""
    normalised = re.sub(r"[^a-z0-9]+", " ", str(text).lower()).strip()
    normalised = re.sub(r"\s+", " ", normalised)
    return hashlib.sha256(normalised[:240].encode()).hexdigest()


# Similarity thresholds for treating two articles as the same story.
DUPLICATE_SIMILARITY_THRESHOLD = 0.45
# When two articles report the SAME monetary amount (e.g. the same funding
# round covered by two outlets), we accept a much lower token-overlap floor:
# outlets phrase the same deal very differently, so the shared amount is a
# stronger duplicate signal than raw vocabulary overlap.
_DUPLICATE_AMOUNT_FLOOR = 0.25

# Collapse punctuation that appears *inside* a word so alternate spellings of
# the same identifier tokenise identically: "reo.dev" -> "reodev", "u.s." ->
# "us", "11.3" -> "113".
_INTRAWORD_PUNCT_RE = re.compile(r"(?<=[a-z0-9])[.'’](?=[a-z0-9])")
# Money amounts written as "$11.3 million" / "11.3 Mn" / "$11.3M" collapse to a
# single stable token ("amt113") so the amount survives tokenisation instead of
# being dropped as short numeric fragments ("11", "3").
_MONEY_RE = re.compile(
    r"\$?\s*([0-9][0-9,]*)\s*(?:million|mn|billion|bn|crore|cr|lakh|thousand|[mbk])\b"
)


def _normalise_text(text: str) -> str:
    lowered = str(text).lower()
    lowered = _INTRAWORD_PUNCT_RE.sub("", lowered)
    return _MONEY_RE.sub(lambda m: f" amt{m.group(1).replace(',', '')} ", lowered)


def article_tokens(article: dict) -> set[str]:
    text = _normalise_text(f"{article.get('title') or ''} {(article.get('content') or '')[:500]}")
    raw_tokens = re.findall(r"[a-z0-9]+", text)
    return {
        _TOKEN_ALIASES.get(token, token)
        for token in raw_tokens
        if len(token) > 2 and token not in _STOPWORDS
    }


def article_similarity(left: dict, right: dict) -> float:
    left_tokens = article_tokens(left)
    right_tokens = article_tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def are_duplicate_articles(
    left: dict,
    right: dict,
    threshold: float = DUPLICATE_SIMILARITY_THRESHOLD,
) -> bool:
    """
    Decide whether two articles are the same underlying story.

    A plain Jaccard token overlap misses cross-outlet duplicates: the same deal
    gets a different headline, framing, and boilerplate on each site, so overall
    vocabulary overlap stays low even when the core facts are identical. We
    therefore also treat two articles as duplicates when they report the same
    monetary amount and clear a lower overlap floor — the shared amount plus a
    little context is a reliable same-deal signal.
    """
    left_tokens = article_tokens(left)
    right_tokens = article_tokens(right)
    if not left_tokens or not right_tokens:
        return False

    intersection = left_tokens & right_tokens
    jaccard = len(intersection) / len(left_tokens | right_tokens)
    if jaccard >= threshold:
        return True

    shares_amount = any(token.startswith("amt") for token in intersection)
    return shares_amount and jaccard >= _DUPLICATE_AMOUNT_FLOOR


def deal_amount_token(deal_value: Optional[str]) -> Optional[str]:
    """
    Extract the normalised amount token (e.g. "amt1955" from "Rs 1,955 Cr") of
    an already-extracted deal, so it can be matched against a new article's text
    even when that article's body is thin or paywalled.
    """
    if not deal_value:
        return None
    for token in article_tokens({"title": deal_value}):
        if token.startswith("amt"):
            return token
    return None


def article_names_parties(article: dict, parties: list[str]) -> int:
    """
    Count how many of `parties` (the buyer/seller company names of an existing
    deal) are fully named in `article`. A company counts only when *all* of its
    name tokens are present, so "Omega Seiki" needs both "omega" and "seiki".
    """
    tokens = article_tokens(article)
    named = 0
    for party in parties:
        party_tokens = article_tokens({"title": party or ""})
        if party_tokens and party_tokens <= tokens:
            named += 1
    return named


def is_duplicate_of_deal(
    article: dict,
    canonical: dict,
    parties: list[str],
    amount_token: Optional[str],
    threshold: float = DUPLICATE_SIMILARITY_THRESHOLD,
) -> bool:
    """
    Decide whether `article` re-reports the same story as an already-extracted
    deal (`canonical` article + its `parties`/`amount_token`).

    Token overlap (`are_duplicate_articles`) is tried first, but it collapses
    when one side is thin/paywalled — the exact case that lets a second outlet's
    copy slip through and pay for a redundant LLM extraction. So we add a signal
    that survives thin bodies: an article that names *both* sides of the deal
    (or one side plus the same monetary amount) is the same story even when raw
    vocabulary overlap is low.
    """
    if are_duplicate_articles(article, canonical, threshold):
        return True

    named = article_names_parties(article, parties)
    if named >= 2:
        return True
    return named >= 1 and amount_token is not None and amount_token in article_tokens(article)


def collapse_duplicate_articles(articles: list[dict]) -> list[dict]:
    collapsed: dict[str, dict] = {}
    fingerprints: list[str] = []
    for article in articles:
        fingerprint = article_fingerprint(article)
        existing_fingerprint = fingerprint if fingerprint in collapsed else None
        if existing_fingerprint is None:
            for candidate_fingerprint in fingerprints:
                if are_duplicate_articles(article, collapsed[candidate_fingerprint]):
                    existing_fingerprint = candidate_fingerprint
                    break

        existing = collapsed.get(existing_fingerprint) if existing_fingerprint else None
        if existing is None:
            item = dict(article)
            item["duplicate_count"] = 1
            item["duplicate_article_ids"] = [article.get("id")]
            collapsed[fingerprint] = item
            fingerprints.append(fingerprint)
            continue

        existing["duplicate_count"] += 1
        existing["duplicate_article_ids"].append(article.get("id"))
        if not existing.get("published_at") and article.get("published_at"):
            existing["published_at"] = article.get("published_at")

    return list(collapsed.values())


def build_signal_context(
    company_name: str,
    articles: list[dict],
    deal_history: list[dict],
    as_of: Optional[datetime] = None,
) -> tuple[list[dict], int]:
    unique_articles = collapse_duplicate_articles(articles)
    context_articles = []
    for article in unique_articles:
        published_at = article.get("published_at") or article.get("scraped_at")
        context_articles.append(
            {
                "id": article.get("id"),
                "title": article.get("title"),
                "source": article.get("source"),
                "published_at": published_at,
                "days_old": days_old(published_at, as_of),
                "decay_weight": news_decay_weight(published_at, as_of),
                "duplicate_count": article.get("duplicate_count", 1),
                "duplicate_article_ids": article.get("duplicate_article_ids", []),
                "content_excerpt": (article.get("content") or "")[:900],
            }
        )

    context_articles.sort(
        key=lambda item: (item["decay_weight"], item["published_at"] or ""),
        reverse=True,
    )
    duplicates_collapsed = len(articles) - len(unique_articles)
    return [
        {
            "company_name": company_name,
            "recent_articles": context_articles[:25],
            "deal_history": deal_history[:25],
        }
    ], max(0, duplicates_collapsed)


def empty_signal_snapshot(
    company_id: str,
    company_name: str,
    horizon_days: int,
    generated_at: Optional[datetime] = None,
) -> CompanySignalSnapshot:
    now = generated_at or datetime.now(timezone.utc)
    return CompanySignalSnapshot(
        id=str(uuid.uuid4()),
        company_id=company_id,
        company_name=company_name,
        horizon_days=horizon_days,
        generated_at=now,
        valid_until=now + timedelta(days=1),
        invest_probability=5,
        fundraise_probability=5,
        acquisition_target_probability=5,
        confidence="low",
        direction="stable",
        is_speculative=True,
        positive_signals=[],
        negative_signals=[],
        evidence_articles=[],
        explanation=(
            "No recent company-specific news was found in the scoring window, "
            "so the signal stays at a low speculative baseline."
        ),
    )


class CompanySignalScorer:
    def __init__(self, client: Groq, model: str, temperature: float = 0.1):
        self.client = client
        self.model = model
        self.temperature = temperature

    def generate(
        self,
        company_id: str,
        company_name: str,
        articles: list[dict],
        deal_history: list[dict],
        horizon_days: int = 30,
    ) -> CompanySignalSnapshot:
        now = datetime.now(timezone.utc)
        if not articles:
            return empty_signal_snapshot(company_id, company_name, horizon_days, now)

        context, duplicates_collapsed = build_signal_context(company_name, articles, deal_history, now)
        prompt = COMPANY_SIGNAL_PROMPT.format(
            company_name=company_name,
            horizon_days=horizon_days,
            context_json=json.dumps(context, ensure_ascii=False, default=str),
        )

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=self.temperature,
                max_tokens=1200,
                response_format={"type": "json_object"},
            )
            raw = json.loads(response.choices[0].message.content)
            score = CompanySignalScore(**raw)
        except Exception as exc:
            logger.error("Company signal LLM call failed: %s", exc)
            raise

        return CompanySignalSnapshot(
            id=str(uuid.uuid4()),
            company_id=company_id,
            company_name=company_name,
            horizon_days=horizon_days,
            generated_at=now,
            valid_until=now + timedelta(days=1),
            articles_analyzed=len(articles),
            duplicates_collapsed=duplicates_collapsed,
            **score.model_dump(),
        )
