from datetime import datetime
from typing import Any, Generic, Optional, TypeVar
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from ..db.mysql_queries import ENTITY_TYPES

T = TypeVar("T")


class ArticleResponse(BaseModel):
    id: UUID
    url: str
    source: str
    title: Optional[str] = None
    scraped_at: datetime
    published_at: Optional[datetime] = None
    is_ma_funding_relevant: Optional[bool] = None
    is_processed: bool

    model_config = {"from_attributes": True}


class ArticleDetailResponse(ArticleResponse):
    content: Optional[str] = None


class ArticleSummaryResponse(BaseModel):
    url: str
    source: str
    title: Optional[str] = None
    published_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class CompanyInDealResponse(BaseModel):
    id: UUID
    name: str
    role: str

    model_config = {"from_attributes": True}

    @model_validator(mode="before")
    @classmethod
    def flatten_company_deal(cls, data: Any) -> Any:
        if hasattr(data, "company"):
            return {"id": data.company.id, "name": data.company.name, "role": data.role}
        return data


class DealResponse(BaseModel):
    id: UUID
    article_id: UUID
    deal_value: Optional[str] = None
    sector: Optional[str] = None
    sub_sector: Optional[str] = None
    country: Optional[str] = None
    deal_type: Optional[str] = None
    summary: Optional[str] = None
    extracted_at: datetime
    is_bookmarked: bool = False
    companies: list[CompanyInDealResponse] = []

    model_config = {"from_attributes": True}

    @model_validator(mode="before")
    @classmethod
    def populate_companies(cls, data: Any) -> Any:
        if hasattr(data, "company_deals"):
            data.__dict__.setdefault("companies", data.company_deals)
        return data


class DealWithArticleResponse(BaseModel):
    id: UUID
    article_id: UUID
    deal_value: Optional[str] = None
    sector: Optional[str] = None
    deal_type: Optional[str] = None
    summary: Optional[str] = None
    is_bookmarked: bool = False
    article: Optional[ArticleSummaryResponse] = None

    model_config = {"from_attributes": True}


class SignalEventResponse(BaseModel):
    signal_type: str
    target_score: str
    strength: str
    polarity: str
    impact: str
    source_article_id: Optional[str] = None
    evidence_text: str


class SignalEvidenceArticleResponse(BaseModel):
    article_id: Optional[str] = None
    title: Optional[str] = None
    source: Optional[str] = None
    days_old: Optional[int] = None
    decay_weight: float
    company_role: str
    duplicate_count: int = 1


class CompanySignalResponse(BaseModel):
    id: UUID
    company_id: UUID
    company_name: str
    horizon_days: int
    generated_at: datetime
    valid_until: datetime
    invest_probability: int = Field(ge=0, le=100)
    fundraise_probability: int = Field(ge=0, le=100)
    acquisition_target_probability: int = Field(ge=0, le=100)
    confidence: str
    direction: str
    is_speculative: bool
    articles_analyzed: int
    duplicates_collapsed: int
    positive_signals: list[SignalEventResponse] = Field(default_factory=list)
    negative_signals: list[SignalEventResponse] = Field(default_factory=list)
    evidence_articles: list[SignalEvidenceArticleResponse] = Field(default_factory=list)
    explanation: str


class PaginatedResponse(BaseModel, Generic[T]):
    total: int
    page: int
    page_size: int
    items: list[T]


class ScrapeRequest(BaseModel):
    start_date: Optional[str] = None
    end_date: Optional[str] = None

    @field_validator("start_date", "end_date")
    @classmethod
    def validate_date_format(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            datetime.strptime(v, "%Y-%m-%d")
        return v


class CompanyScrapeRequest(BaseModel):
    company: str = Field(..., min_length=1, description="Company name to search each source for")
    sources: Optional[list[str]] = Field(
        None, description="Restrict to these source names; omit to use all searchable sources"
    )
    start_date: Optional[str] = None
    end_date: Optional[str] = None

    @field_validator("start_date", "end_date")
    @classmethod
    def validate_date_format(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            datetime.strptime(v, "%Y-%m-%d")
        return v

    @model_validator(mode="after")
    def validate_date_pair(self) -> "CompanyScrapeRequest":
        if bool(self.start_date) != bool(self.end_date):
            raise ValueError("start_date and end_date must be provided together")
        return self


class WatchlistScrapeRequest(BaseModel):
    """Scrape news restricted to companies tracked in the company MySQL DB."""

    since: Optional[str] = Field(
        None,
        description="Only search companies added to the company DB on or after this date "
                    "(YYYY-MM-DD). Omit to use the watchlist.default_since_hours window.",
    )
    entity_types: Optional[list[str]] = Field(
        None, description="Restrict to seller / buyer / lead; omit for all three"
    )
    limit: Optional[int] = Field(
        None, ge=1, description="Cap on entities searched; defaults to watchlist.max_entities_per_run"
    )
    sources: Optional[list[str]] = Field(
        None, description="Restrict to these source names; omit to use every configured source"
    )
    start_date: Optional[str] = None
    end_date: Optional[str] = None

    @field_validator("since", "start_date", "end_date")
    @classmethod
    def validate_date_format(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            datetime.strptime(v, "%Y-%m-%d")
        return v

    @field_validator("entity_types")
    @classmethod
    def validate_entity_types(cls, v: Optional[list[str]]) -> Optional[list[str]]:
        if v is None:
            return v
        unknown = [t for t in v if t not in ENTITY_TYPES]
        if unknown:
            raise ValueError(f"Unknown entity type(s): {', '.join(unknown)}")
        return v

    @model_validator(mode="after")
    def validate_date_pair(self) -> "WatchlistScrapeRequest":
        if bool(self.start_date) != bool(self.end_date):
            raise ValueError("start_date and end_date must be provided together")
        return self


class RegisterCompanyRequest(BaseModel):
    """Done Deal telling us to track a company and go find its news."""

    company_id: str = Field(
        ...,
        min_length=2,
        description="Done Deal reference, e.g. 'S5122'. Prefix S/B/L then the row id.",
    )
    company_name: str = Field(
        ...,
        min_length=2,
        description="The company name, e.g. 'Meesho'. This is what gets typed into each "
                    "news site's search, so it should be the name coverage uses. Legal "
                    "suffixes are stripped automatically ('Delhivery Limited' → 'Delhivery').",
    )
    brand_name: Optional[str] = Field(
        None,
        description="Optional. Only needed when company_name is a registered entity name "
                    "the press never uses ('Fashnear Technologies Private Limited' vs "
                    "'Meesho'); news sites have nothing filed under the former, so a search "
                    "for it returns nothing. Omit when the two are the same.",
    )
    scrape: bool = Field(
        True,
        description="Run a backfill scrape for this company. Set false to only "
                    "record the link — useful when re-syncing a company already scraped.",
    )

    @field_validator("company_id")
    @classmethod
    def validate_company_id(cls, v: str) -> str:
        from ..processor.entity_link import InvalidEntityRef, parse_entity_ref

        try:
            parse_entity_ref(v)
        except InvalidEntityRef as exc:
            raise ValueError(str(exc)) from exc
        return v.strip().upper().replace("-", "")

    @field_validator("company_name")
    @classmethod
    def validate_company_name(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("company_name must not be blank")
        return v.strip()


class RegisteredCompanyResponse(BaseModel):
    """The stored link between a Done Deal reference and a Company node."""

    company_id: str = Field(..., description="Done Deal reference, e.g. 'S5122'")
    company_name: str = Field(..., description="Name Done Deal sent")
    graph_name: str = Field(
        ..., description="Normalised name the node is keyed by, and news is searched under"
    )
    node_id: UUID
    linked_at: Optional[str] = None
    created: Optional[bool] = Field(
        None, description="True when this call created the node rather than stamping an existing one"
    )
    deal_count: Optional[int] = Field(
        None,
        description="Deals already linked to this node. `created: true` with `deal_count: 0` "
                    "usually means the name did not match anything the extractor has seen — "
                    "check brand_name.",
    )
    job_id: Optional[str] = Field(
        None,
        description="Backfill scrape job; poll GET /api/v1/news-scrapper/companies/scrape/{job_id}",
    )


class CompanyNewsResponse(BaseModel):
    """A registered company's deal feed, keyed by its Done Deal reference."""

    company: RegisteredCompanyResponse
    total: int
    page: int
    page_size: int
    items: list[DealWithArticleResponse]


class EntitySummary(BaseModel):
    """A company DB entity as the UI refers to it, plus the name its news is
    filed under in the news graph."""

    ref: str = Field(..., description="Company DB reference, e.g. 'S5123'")
    entity_type: str
    entity_id: int
    company_name: str
    brand_name: Optional[str] = None
    website: Optional[str] = None
    search_term: str = Field(
        ..., description="Name the news graph is searched by — brand where one exists"
    )


class EntityNewsResponse(BaseModel):
    """A paginated deal feed with the entity it was resolved from.

    Carries the entity so the UI can show which company DB record produced the
    feed without a second call — and so an empty `items` is attributable to the
    company having no extracted deals rather than to a failed lookup.
    """

    entity: EntitySummary
    total: int
    page: int
    page_size: int
    items: list[DealWithArticleResponse]


class WatchlistEntryResponse(BaseModel):
    entity_type: str
    entity_id: int
    company_name: str
    brand_name: Optional[str] = None
    website: Optional[str] = None
    search_term: str


class WatchlistPreviewResponse(BaseModel):
    """What a watchlist run would search for, without running it."""

    since: Optional[str] = None
    total_entities: int = Field(..., description="Rows matching the filters in the company DB")
    total_terms: int = Field(..., description="Distinct search terms after dedup and length filtering")
    counts_by_type: dict[str, int]
    entries: list[WatchlistEntryResponse]


class ExtractRequest(BaseModel):
    limit: Optional[int] = None


class ScrapeJobResponse(BaseModel):
    job_id: str
    status: str
    started_at: datetime
    finished_at: Optional[datetime] = None
    result: Optional[dict] = None
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Analytics schemas
# ---------------------------------------------------------------------------

class DealsBySectorItem(BaseModel):
    sector: str
    deal_count: int


class TopBuyerItem(BaseModel):
    company_id: str
    company_name: str
    deal_count: int


class DealVolumeItem(BaseModel):
    period: Optional[str]
    deal_count: int
