from datetime import date, datetime, time
from typing import Optional
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import Engine, and_, func, select
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
