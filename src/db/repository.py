import hashlib
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from .names import normalize_company_name as _normalize_company_name


def _company_id(name: str) -> str:
    """Deterministic UUID5 keyed on the normalized name so variants map to the same ID."""
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, _normalize_company_name(name)))

from neo4j import GraphDatabase

from .models import COMPANY_DEAL_RELS, ROLE_TO_REL, SCHEMA_CONSTRAINTS, SCHEMA_INDEXES

logger = logging.getLogger(__name__)


# The LLM sometimes writes a placeholder instead of leaving a party null —
# "Not specified" for the buyers in an unattributed block deal, say. Stored
# verbatim these become Company nodes that accumulate relationships across
# unrelated deals, so they are dropped at the boundary.
_PLACEHOLDER_NAMES = {
    "n/a", "na", "none", "null", "not specified", "unspecified",
    "not disclosed", "undisclosed", "not applicable", "unknown",
    "not available", "not mentioned", "various", "others",
}


def _split_names(raw: Optional[str]) -> list[str]:
    if not raw:
        return []
    return [
        n.strip() for n in raw.split(",")
        if n.strip() and n.strip().lower().strip(".") not in _PLACEHOLDER_NAMES
    ]


def _roles_for_deal_type(deal_type: Optional[str]) -> tuple[str, str]:
    if deal_type == "funding_round":
        return "investor", "company"
    return "buyer", "seller"


class NewsRepository:
    def __init__(
        self,
        uri: str,
        user: str,
        password: str,
        database: str = "neo4j",
        pool_size: int = 5,
        ensure_schema: bool = True,
    ):
        self._driver = GraphDatabase.driver(
            uri,
            auth=(user, password),
            max_connection_pool_size=pool_size,
        )
        self._database = database
        if ensure_schema:
            self._init_schema()

    def _session(self):
        return self._driver.session(database=self._database)

    def _init_schema(self) -> None:
        with self._session() as session:
            for stmt in SCHEMA_CONSTRAINTS + SCHEMA_INDEXES:
                session.run(stmt)

    def close(self) -> None:
        self._driver.close()

    def register_company(
        self,
        external_id: str,
        name: str,
        brand_name: Optional[str] = None,
    ) -> dict:
        """Attach a Done Deal reference (e.g. "S5122") to a Company node.

        Keyed on the *brand* where one exists, falling back to the registered
        name with its legal suffixes stripped. This is the same rule the
        watchlist searches under, and it has to be: the node must be the one the
        extractor MERGEs when it reads that company out of an article. Press
        coverage writes "Meesho", never "Fashnear Technologies Private Limited",
        so keying on the registered name would mint an orphan node and the feed
        would return nothing while the real deals sat on "Meesho".

        Idempotent, and safe when Done Deal renames a company: the reference is
        first removed from whatever node currently holds it, since
        `company_external_id` is unique and the write would otherwise fail.

        Returns the node's properties plus `created` and `deal_count`. A node
        created fresh with no deals is the signature of a name that did not
        match anything the extractor has seen — worth surfacing to the caller
        rather than reporting success.
        """
        canonical = _normalize_company_name(brand_name or name)
        if not canonical:
            raise ValueError("company name is empty after normalisation")

        with self._session() as session:
            # Release the ref from any other node before claiming it.
            session.run(
                """
                MATCH (old:Company {external_id: $external_id})
                WHERE old.name <> $name
                REMOVE old.external_id, old.external_name
                """,
                external_id=external_id,
                name=canonical,
            )
            record = session.run(
                """
                MERGE (c:Company {name: $name})
                ON CREATE SET c.id = $company_id, c._created = true
                SET c.external_id   = $external_id,
                    c.external_name = $external_name,
                    c.linked_at     = $linked_at
                WITH c, coalesce(c._created, false) AS created
                REMOVE c._created
                WITH c, created
                OPTIONAL MATCH (c)-[r]->(:Deal)
                RETURN c.id AS id, c.name AS name, c.external_id AS external_id,
                       c.external_name AS external_name, c.linked_at AS linked_at,
                       created, count(r) AS deal_count
                """,
                name=canonical,
                company_id=_company_id(canonical),
                external_id=external_id,
                external_name=name,
                linked_at=datetime.now(timezone.utc).isoformat(),
            ).single()

        if record["created"] and not record["deal_count"]:
            logger.warning(
                f"Registered company {external_id} → '{canonical}': created a new node with"
                f" no deals. If {name!r} is known to the press under another name, resend"
                " with that name as brand_name or the news feed will stay empty."
            )
        else:
            logger.info(
                f"Registered company {external_id} → '{canonical}'"
                f" ({'new node' if record['created'] else 'existing node'},"
                f" {record['deal_count']} deal link(s))"
            )
        return dict(record)

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
                    is_ma_funding_relevant: null,
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

    def save_articles_batch(self, articles: list[dict]) -> list[dict]:
        """
        Batch-insert scraped articles, skipping ones already in the DB.

        Each input dict needs: url, title, content, published_date, source_name.
        Returns the subset that was actually inserted, each enriched with the
        generated `id` (and `url_hash`) so callers can run filter/extraction
        against them immediately.
        """
        if not articles:
            return []

        rows = []
        for article in articles:
            published_date = article["published_date"]
            rows.append({
                **article,
                "id": str(uuid.uuid4()),
                "url_hash": self._hash_url(article["url"]),
                "scraped_at": datetime.now(timezone.utc).isoformat(),
                "published_at": published_date.isoformat() if published_date else None,
            })

        with self._session() as session:
            existing = session.run(
                "UNWIND $hashes AS h MATCH (a:Article {url_hash: h}) RETURN a.url_hash AS h",
                hashes=[row["url_hash"] for row in rows],
            )
            existing_hashes = {record["h"] for record in existing}

            new_rows = [row for row in rows if row["url_hash"] not in existing_hashes]
            if not new_rows:
                return []

            session.run(
                """
                UNWIND $rows AS row
                CREATE (a:Article {
                    id:           row.id,
                    url:          row.url,
                    url_hash:     row.url_hash,
                    source:       row.source_name,
                    title:        row.title,
                    content:      row.content,
                    scraped_at:   row.scraped_at,
                    published_at: row.published_at,
                    // The company whose on-site search returned this article,
                    // null for a plain listing/RSS walk. This is provenance the
                    // extractor cannot recover: an article found by searching
                    // "Meesho" is about Meesho even when the LLM names only the
                    // acquirer and the target, so it is what lets a registered
                    // company reach its own news without depending on the
                    // parties matching its name.
                    searched_company: row.searched_company,
                    is_ma_funding_relevant: null,
                    is_processed: false
                })
                """,
                rows=new_rows,
            )

        return new_rows

    def get_unprocessed_articles(self, limit: Optional[int] = None) -> list[dict]:
        """
        Fetch Article rows that haven't been filtered yet
        (is_ma_funding_relevant IS NULL), oldest first.

        Returned dicts use `source_name` (not the node's `source` property) so
        the shape matches what freshly-scraped article dicts already use —
        callers run the same filter/extraction code against either.
        """
        query = "MATCH (a:Article) WHERE a.is_ma_funding_relevant IS NULL RETURN a ORDER BY a.scraped_at ASC"
        params: dict = {}
        if limit is not None:
            query += " LIMIT $limit"
            params["limit"] = limit

        with self._session() as session:
            result = session.run(query, **params)
            rows = []
            for record in result:
                row = dict(record["a"])
                row["source_name"] = row.pop("source")
                rows.append(row)
            return rows

    def mark_ma_funding_relevant(self, article_id, is_relevant: bool) -> None:
        with self._session() as session:
            session.run(
                "MATCH (a:Article {id: $id}) SET a.is_ma_funding_relevant = $rel",
                id=str(article_id),
                rel=is_relevant,
            )

    def get_recent_deal_articles(self, days: int = 7) -> list[dict]:
        """
        Fetch canonical (non-duplicate) articles that already produced a Deal,
        scraped within the last `days` days.

        Used as the comparison pool for cross-source duplicate detection
        (e.g. the same deal covered by CNBC and another outlet) so a
        near-duplicate article can be linked to the existing Deal instead of
        re-running LLM extraction on it.
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        with self._session() as session:
            result = session.run(
                f"""
                MATCH (a:Article)-[:HAS_DEAL]->(d:Deal)
                WHERE a.is_processed = true
                  AND a.duplicate_of IS NULL
                  AND a.scraped_at >= $cutoff
                OPTIONAL MATCH (co:Company)-[:{COMPANY_DEAL_RELS}]->(d)
                RETURN a.id AS id, a.title AS title, a.content AS content,
                       d.id AS deal_id, d.deal_value AS deal_value,
                       [name IN collect(DISTINCT co.name) WHERE name IS NOT NULL] AS parties
                """,
                cutoff=cutoff,
            )
            return [dict(record) for record in result]

    def mark_duplicate_article(self, article_id, canonical_article_id, is_relevant: bool = True) -> None:
        """
        Mark an article as a near-duplicate of an already-processed canonical
        article instead of running LLM extraction on it again. No new Deal
        node is created — the duplicate is linked to the canonical article
        for provenance via DUPLICATE_OF.
        """
        with self._session() as session:
            session.run(
                """
                MATCH (a:Article {id: $article_id})
                MATCH (c:Article {id: $canonical_id})
                SET a.is_processed = true,
                    a.is_ma_funding_relevant = $is_relevant,
                    a.duplicate_of = $canonical_id
                CREATE (a)-[:DUPLICATE_OF]->(c)
                """,
                article_id=str(article_id),
                canonical_id=str(canonical_article_id),
                is_relevant=is_relevant,
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
        target_company: Optional[str] = None,
    ) -> str:
        new_deal_id = str(uuid.uuid4())
        extracted_at = datetime.now(timezone.utc).isoformat()
        buyer_role, seller_role = _roles_for_deal_type(deal_type)

        with self._session() as session:
            # MERGE keyed on the (uniquely constrained) article_id: if two
            # extraction runs race on the same article, Neo4j serializes the
            # concurrent MERGEs so only one Deal node is ever created for it —
            # the second call matches the already-created node instead of
            # inserting a duplicate.
            record = session.run(
                """
                MATCH (a:Article {id: $article_id})
                MERGE (d:Deal {article_id: $article_id})
                ON CREATE SET
                    d.id           = $new_deal_id,
                    d.deal_value   = $deal_value,
                    d.sector       = $sector,
                    d.sub_sector   = $sub_sector,
                    d.country      = $country,
                    d.deal_type    = $deal_type,
                    d.summary      = $summary,
                    d.extracted_at = $extracted_at
                MERGE (a)-[:HAS_DEAL]->(d)
                SET a.is_processed = true
                RETURN d.id AS deal_id
                """,
                article_id=str(article_id),
                new_deal_id=new_deal_id,
                deal_value=deal_value,
                sector=sector,
                sub_sector=sub_sector,
                country=country,
                deal_type=deal_type,
                summary=summary,
                extracted_at=extracted_at,
            ).single()
            deal_id = record["deal_id"]

            # Create Company nodes and relationships, one role at a time. The
            # target is linked last and only when it is not already a party, so
            # a company named as both buyer/seller and subject keeps the more
            # specific role instead of gaining a redundant ABOUT edge.
            parties = {
                _normalize_company_name(n)
                for n in _split_names(buyer) + _split_names(seller)
            }
            for role, raw in (
                (buyer_role, buyer),
                (seller_role, seller),
                ("target", target_company),
            ):
                rel = ROLE_TO_REL[role]
                for name in _split_names(raw):
                    canonical = _normalize_company_name(name)
                    if role == "target" and canonical in parties:
                        continue
                    session.run(
                        f"""
                        MERGE (c:Company {{name: $name}})
                        ON CREATE SET c.id = $company_id
                        WITH c
                        MATCH (d:Deal {{id: $deal_id}})
                        MERGE (c)-[:{rel}]->(d)
                        """,
                        name=canonical,
                        company_id=_company_id(canonical),
                        deal_id=deal_id,
                    )

        logger.debug(f"Deal saved for article {article_id}")
        return deal_id
