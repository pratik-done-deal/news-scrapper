import hashlib
import logging
from datetime import date, datetime, time
from typing import Optional
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import and_, create_engine, func, select
from sqlalchemy.orm import Session

from .models import Article, Base, Deal

IST = ZoneInfo("Asia/Kolkata")

logger = logging.getLogger(__name__)


class NewsRepository:
    def __init__(self, database_url: str, pool_size: int = 5, max_overflow: int = 10):
        self.engine = create_engine(
            database_url,
            pool_size=pool_size,
            max_overflow=max_overflow,
        )
        Base.metadata.create_all(self.engine)

    def _hash_url(self, url: str) -> str:
        return hashlib.sha256(url.encode()).hexdigest()

    def url_exists(self, url: str) -> bool:
        url_hash = self._hash_url(url)
        with Session(self.engine) as session:
            result = session.execute(
                select(Article.id).where(Article.url_hash == url_hash)
            ).first()
            return result is not None

    def save_article(
        self,
        url: str,
        source: str,
        title: Optional[str],
        content: Optional[str],
        published_at=None,
    ) -> Article:
        article = Article(
            url=url,
            url_hash=self._hash_url(url),
            source=source,
            title=title,
            content=content,
            published_at=published_at,
        )
        with Session(self.engine) as session:
            session.add(article)
            session.commit()
            session.refresh(article)
            # detach from session so it can be used outside
            session.expunge(article)
        return article

    def mark_ma_relevant(self, article_id: UUID, is_relevant: bool) -> None:
        with Session(self.engine) as session:
            article = session.get(Article, article_id)
            if article:
                article.is_ma_relevant = is_relevant
                session.commit()

    def save_deal(
        self,
        article_id: UUID,
        buyer: Optional[str],
        seller: Optional[str],
        deal_value: Optional[str],
        sector: Optional[str],
        sub_sector: Optional[str],
        country: Optional[str],
        deal_type: Optional[str],
        summary: Optional[str],
    ) -> None:
        with Session(self.engine) as session:
            article = session.get(Article, article_id)
            if article:
                article.is_processed = True
            session.add(
                Deal(
                    article_id=article_id,
                    buyer=buyer,
                    seller=seller,
                    deal_value=deal_value,
                    sector=sector,
                    sub_sector=sub_sector,
                    country=country,
                    deal_type=deal_type,
                    summary=summary,
                )
            )
            session.commit()
        logger.debug(f"Deal saved for article {article_id}")
