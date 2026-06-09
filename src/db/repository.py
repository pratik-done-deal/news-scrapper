import hashlib
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

def _company_id(name: str) -> str:
    """Deterministic UUID5 so the same company name always gets the same ID."""
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, name))

from neo4j import GraphDatabase

from .models import SCHEMA_CONSTRAINTS, SCHEMA_INDEXES

logger = logging.getLogger(__name__)

# Maps company role → Cypher relationship type
_ROLE_TO_REL = {
    "buyer": "BOUGHT",
    "seller": "SOLD",
    "investor": "INVESTED_IN",
    "company": "INVOLVED_IN",
}


def _split_names(raw: Optional[str]) -> list[str]:
    if not raw:
        return []
    return [n.strip() for n in raw.split(",") if n.strip()]


def _roles_for_deal_type(deal_type: Optional[str]) -> tuple[str, str]:
    if deal_type == "funding_round":
        return "investor", "company"
    return "buyer", "seller"


class NewsRepository:
    def __init__(self, uri: str, user: str, password: str, database: str = "neo4j", pool_size: int = 5):
        self._driver = GraphDatabase.driver(
            uri,
            auth=(user, password),
            max_connection_pool_size=pool_size,
        )
        self._database = database
        self._init_schema()

    def _session(self):
        return self._driver.session(database=self._database)

    def _init_schema(self) -> None:
        with self._session() as session:
            for stmt in SCHEMA_CONSTRAINTS + SCHEMA_INDEXES:
                session.run(stmt)

    def close(self) -> None:
        self._driver.close()

    def _hash_url(self, url: str) -> str:
        return hashlib.sha256(url.encode()).hexdigest()

    def url_exists(self, url: str) -> bool:
        url_hash = self._hash_url(url)
        with self._session() as session:
            result = session.run(
                "MATCH (a:Article {url_hash: $url_hash}) RETURN a.id LIMIT 1",
                url_hash=url_hash,
            )
            return result.single() is not None

    def save_article(
        self,
        url: str,
        source: str,
        title: Optional[str],
        content: Optional[str],
        published_at=None,
    ):
        article_id = str(uuid.uuid4())
        scraped_at = datetime.now(timezone.utc).isoformat()
        published_at_iso = published_at.isoformat() if published_at else None

        with self._session() as session:
            session.run(
                """
                CREATE (a:Article {
                    id:           $id,
                    url:          $url,
                    url_hash:     $url_hash,
                    source:       $source,
                    title:        $title,
                    content:      $content,
                    scraped_at:   $scraped_at,
                    published_at: $published_at,
                    is_ma_relevant: null,
                    is_processed: false
                })
                """,
                id=article_id,
                url=url,
                url_hash=self._hash_url(url),
                source=source,
                title=title,
                content=content,
                scraped_at=scraped_at,
                published_at=published_at_iso,
            )

        # Return a simple namespace so callers can access .id the same way as before
        class _ArticleRef:
            pass

        ref = _ArticleRef()
        ref.id = article_id
        return ref

    def mark_ma_relevant(self, article_id, is_relevant: bool) -> None:
        with self._session() as session:
            session.run(
                "MATCH (a:Article {id: $id}) SET a.is_ma_relevant = $rel",
                id=str(article_id),
                rel=is_relevant,
            )

    def save_deal(
        self,
        article_id,
        buyer: Optional[str],
        seller: Optional[str],
        deal_value: Optional[str],
        sector: Optional[str],
        sub_sector: Optional[str],
        country: Optional[str],
        deal_type: Optional[str],
        summary: Optional[str],
    ) -> None:
        deal_id = str(uuid.uuid4())
        extracted_at = datetime.now(timezone.utc).isoformat()
        buyer_role, seller_role = _roles_for_deal_type(deal_type)

        with self._session() as session:
            # Mark article processed and create the Deal node linked to the Article
            session.run(
                """
                MATCH (a:Article {id: $article_id})
                SET a.is_processed = true
                CREATE (d:Deal {
                    id:           $deal_id,
                    deal_value:   $deal_value,
                    sector:       $sector,
                    sub_sector:   $sub_sector,
                    country:      $country,
                    deal_type:    $deal_type,
                    summary:      $summary,
                    extracted_at: $extracted_at
                })
                CREATE (a)-[:HAS_DEAL]->(d)
                """,
                article_id=str(article_id),
                deal_id=deal_id,
                deal_value=deal_value,
                sector=sector,
                sub_sector=sub_sector,
                country=country,
                deal_type=deal_type,
                summary=summary,
                extracted_at=extracted_at,
            )

            # Create Company nodes and relationships for buyers
            buyer_rel = _ROLE_TO_REL[buyer_role]
            for name in _split_names(buyer):
                session.run(
                    f"""
                    MERGE (c:Company {{name: $name}})
                    ON CREATE SET c.id = $company_id
                    WITH c
                    MATCH (d:Deal {{id: $deal_id}})
                    CREATE (c)-[:{buyer_rel}]->(d)
                    """,
                    name=name,
                    company_id=_company_id(name),
                    deal_id=deal_id,
                )

            # Create Company nodes and relationships for sellers
            seller_rel = _ROLE_TO_REL[seller_role]
            for name in _split_names(seller):
                session.run(
                    f"""
                    MERGE (c:Company {{name: $name}})
                    ON CREATE SET c.id = $company_id
                    WITH c
                    MATCH (d:Deal {{id: $deal_id}})
                    CREATE (c)-[:{seller_rel}]->(d)
                    """,
                    name=name,
                    company_id=_company_id(name),
                    deal_id=deal_id,
                )

        logger.debug(f"Deal saved for article {article_id}")
