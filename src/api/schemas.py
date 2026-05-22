from datetime import datetime
from typing import Any, Generic, Optional, TypeVar
from uuid import UUID

from pydantic import BaseModel, field_validator, model_validator

T = TypeVar("T")


class ArticleResponse(BaseModel):
    id: UUID
    url: str
    source: str
    title: Optional[str] = None
    scraped_at: datetime
    published_at: Optional[datetime] = None
    is_ma_relevant: Optional[bool] = None
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
