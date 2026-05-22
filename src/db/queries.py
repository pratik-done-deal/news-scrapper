from datetime import date, datetime, time
from typing import Literal, Optional
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import Engine, and_, func, select, text
from sqlalchemy.orm import Session, selectinload

from .models import Article, Company, CompanyDeal, Deal

IST = ZoneInfo("Asia/Kolkata")


def list_articles(
    engine: Engine,
    source: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    is_ma_relevant: Optional[bool] = None,
    offset: int = 0,
    limit: int = 20,
) -> tuple[int, list[Article]]:
    with Session(engine) as session:
        conditions = []
        if source:
            conditions.append(Article.source == source)
        if date_from:
            dt_from = datetime.combine(date_from, time.min).replace(tzinfo=IST)
            conditions.append(Article.published_at >= dt_from)
        if date_to:
            dt_to = datetime.combine(date_to, time(23, 59, 59)).replace(tzinfo=IST)
            conditions.append(Article.published_at <= dt_to)
        if is_ma_relevant is not None:
            conditions.append(Article.is_ma_relevant == is_ma_relevant)

        base_q = select(Article)
        if conditions:
            base_q = base_q.where(and_(*conditions))

        total = session.scalar(select(func.count()).select_from(base_q.subquery())) or 0
        items = list(
            session.execute(
                base_q.order_by(Article.published_at.desc().nullslast()).offset(offset).limit(limit)
            ).scalars()
        )
        for item in items:
            session.expunge(item)
        return total, items


def get_article(engine: Engine, article_id: UUID) -> Optional[Article]:
    with Session(engine) as session:
        article = session.get(Article, article_id)
        if article:
            session.expunge(article)
        return article


def list_deals(
    engine: Engine,
    sector: Optional[str] = None,
    deal_type: Optional[str] = None,
    offset: int = 0,
    limit: int = 20,
) -> tuple[int, list[Deal]]:
    with Session(engine) as session:
        conditions = []
        if sector:
            conditions.append(Deal.sector.ilike(f"%{sector}%"))
        if deal_type:
            conditions.append(Deal.deal_type.ilike(f"%{deal_type}%"))

        companies_loader = selectinload(Deal.company_deals).selectinload(CompanyDeal.company)

        base_q = select(Deal)
        if conditions:
            base_q = base_q.where(and_(*conditions))

        total = session.scalar(select(func.count()).select_from(base_q.subquery())) or 0
        items = list(
            session.execute(
                base_q.options(companies_loader).order_by(Deal.extracted_at.desc()).offset(offset).limit(limit)
            ).scalars()
        )
        for item in items:
            session.expunge(item)
        return total, items


def get_deal(engine: Engine, deal_id: UUID) -> Optional[Deal]:
    with Session(engine) as session:
        deal = session.execute(
            select(Deal)
            .where(Deal.id == deal_id)
            .options(selectinload(Deal.company_deals).selectinload(CompanyDeal.company))
        ).scalar_one_or_none()
        if deal:
            session.expunge(deal)
        return deal


def get_company(engine: Engine, company_id: UUID) -> Optional[Company]:
    with Session(engine) as session:
        company = session.get(Company, company_id)
        if company:
            session.expunge(company)
        return company


def get_deals_by_company_name(
    engine: Engine,
    name: str,
    offset: int = 0,
    limit: int = 20,
) -> tuple[int, list[Deal]]:
    with Session(engine) as session:
        base_q = (
            select(Deal)
            .join(CompanyDeal, CompanyDeal.deal_id == Deal.id)
            .join(Company, Company.id == CompanyDeal.company_id)
            .where(Company.name.ilike(f"%{name}%"))
            .distinct()
        )

        total = session.scalar(select(func.count()).select_from(base_q.subquery())) or 0
        items = list(
            session.execute(
                base_q
                .options(
                    selectinload(Deal.company_deals).selectinload(CompanyDeal.company),
                    selectinload(Deal.article),
                )
                .order_by(Deal.extracted_at.desc())
                .offset(offset)
                .limit(limit)
            ).scalars()
        )
        for item in items:
            session.expunge(item)
        return total, items


def get_deals_by_company(
    engine: Engine,
    company_id: UUID,
    offset: int = 0,
    limit: int = 20,
) -> tuple[int, list[Deal]]:
    with Session(engine) as session:
        base_q = (
            select(Deal)
            .join(CompanyDeal, CompanyDeal.deal_id == Deal.id)
            .where(CompanyDeal.company_id == company_id)
        )

        total = session.scalar(select(func.count()).select_from(base_q.subquery())) or 0
        items = list(
            session.execute(
                base_q
                .options(
                    selectinload(Deal.company_deals).selectinload(CompanyDeal.company),
                    selectinload(Deal.article),
                )
                .order_by(Deal.extracted_at.desc())
                .offset(offset)
                .limit(limit)
            ).scalars()
        )
        for item in items:
            session.expunge(item)
        return total, items


# ---------------------------------------------------------------------------
# Analytics queries
# ---------------------------------------------------------------------------

def analytics_deals_by_sector(engine: Engine) -> list[dict]:
    """Return deal count broken down by sector, sorted by count descending."""
    with Session(engine) as session:
        rows = session.execute(
            select(
                Deal.sector,
                func.count(Deal.id).label("deal_count"),
            )
            .where(Deal.sector.isnot(None))
            .group_by(Deal.sector)
            .order_by(func.count(Deal.id).desc())
        ).all()
        return [{"sector": r.sector, "deal_count": r.deal_count} for r in rows]


def analytics_top_buyers(
    engine: Engine,
    role: str = "buyer",
    limit: int = 10,
) -> list[dict]:
    """Return companies most frequently appearing as buyer (or investor) in deals."""
    with Session(engine) as session:
        rows = session.execute(
            select(
                Company.id,
                Company.name,
                func.count(CompanyDeal.id).label("deal_count"),
            )
            .join(CompanyDeal, CompanyDeal.company_id == Company.id)
            .where(CompanyDeal.role == role)
            .group_by(Company.id, Company.name)
            .order_by(func.count(CompanyDeal.id).desc())
            .limit(limit)
        ).all()
        return [
            {"company_id": str(r.id), "company_name": r.name, "deal_count": r.deal_count}
            for r in rows
        ]


def analytics_deal_volume(
    engine: Engine,
    group_by: Literal["day", "month", "year"] = "month",
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
) -> list[dict]:
    """Return deal count per time bucket (day / month / year)."""
    trunc_map = {"day": "day", "month": "month", "year": "year"}
    trunc = trunc_map[group_by]

    with Session(engine) as session:
        period_col = func.date_trunc(trunc, Article.published_at).label("period")
        q = (
            select(period_col, func.count(Deal.id).label("deal_count"))
            .join(Article, Deal.article_id == Article.id)
            .where(Article.published_at.isnot(None))
        )
        if date_from:
            dt_from = datetime.combine(date_from, time.min).replace(tzinfo=IST)
            q = q.where(Article.published_at >= dt_from)
        if date_to:
            dt_to = datetime.combine(date_to, time(23, 59, 59)).replace(tzinfo=IST)
            q = q.where(Article.published_at <= dt_to)

        q = q.group_by(text("1")).order_by(text("1"))
        rows = session.execute(q).all()
        return [
            {"period": r.period.date().isoformat() if r.period else None, "deal_count": r.deal_count}
            for r in rows
        ]
