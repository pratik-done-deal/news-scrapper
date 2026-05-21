import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class Article(Base):
    __tablename__ = "articles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    url = Column(Text, unique=True, nullable=False)
    url_hash = Column(String(64), nullable=False)
    source = Column(Text, nullable=False)
    title = Column(Text)
    content = Column(Text)
    scraped_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    published_at = Column(DateTime(timezone=True), nullable=True)
    is_ma_relevant = Column(Boolean, default=None)
    is_processed = Column(Boolean, default=False)

    deals = relationship("Deal", back_populates="article", cascade="all, delete-orphan")


class Deal(Base):
    __tablename__ = "deals"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    article_id = Column(UUID(as_uuid=True), ForeignKey("articles.id"), nullable=False)
    deal_value = Column(Text)
    sector = Column(Text)
    country = Column(Text)
    deal_type = Column(Text)
    sub_sector = Column(Text)
    summary = Column(Text)
    extracted_at = Column(DateTime(timezone=True), default=lambda: datetime.now(tz=ZoneInfo("Asia/Kolkata")))

    article = relationship("Article", back_populates="deals")
    company_deals = relationship("CompanyDeal", back_populates="deal", cascade="all, delete-orphan")


class Company(Base):
    __tablename__ = "companies"

    id   = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(Text, nullable=False, unique=True)

    company_deals = relationship("CompanyDeal", back_populates="company")


class CompanyDeal(Base):
    __tablename__ = "company_deals"
    __table_args__ = (
        UniqueConstraint("company_id", "deal_id", "role"),
    )

    id         = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    deal_id    = Column(UUID(as_uuid=True), ForeignKey("deals.id"), nullable=False)
    role       = Column(Text, nullable=False)  # 'buyer' or 'seller'

    company = relationship("Company", back_populates="company_deals")
    deal    = relationship("Deal", back_populates="company_deals")
