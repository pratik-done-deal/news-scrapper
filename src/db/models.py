import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String, Text
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
    is_ma_relevant = Column(Boolean, default=None)
    is_processed = Column(Boolean, default=False)

    deals = relationship("Deal", back_populates="article", cascade="all, delete-orphan")


class Deal(Base):
    __tablename__ = "deals"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    article_id = Column(UUID(as_uuid=True), ForeignKey("articles.id"), nullable=False)
    buyer = Column(Text)
    seller = Column(Text)
    deal_value = Column(Text)
    sector = Column(Text)
    country = Column(Text)
    deal_type = Column(Text)
    sub_sector = Column(Text)
    summary = Column(Text)
    extracted_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    article = relationship("Article", back_populates="deals")
