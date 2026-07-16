from datetime import datetime
from typing import Any, Generic, Optional, TypeVar
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

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
    companies: list[CompanyInDealResponse] = []

    model_config = {"from_attributes": True}

    @model_validator(mode="before")
    @classmethod
    def populate_companies(cls, data: Any) -> Any:
        if hasattr(data, "company_deals"):
            data.__dict__.setdefault("companies", data.company_deals)
        return data


class DealWithArticleResponse(DealResponse):
    article: Optional[ArticleResponse] = None


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
