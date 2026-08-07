# Project Context — Deal & Funding Intelligence Platform

Full reference for the architecture, graph schema, and code conventions.
Pull this file when making changes that cross multiple components.

---

## Architecture

Producer/consumer multiprocessing (spawn context). Two processes only — never a pool.

```
Process 1 (main) — P1 Producer
  NewsAgent.run()
    for each source (serial):
      _scrape_links()         → article URLs
      scraper.extract_article() → title, content, published_date
      job_queue.put({source_name, articles})
    job_queue.put(STOP_PROCESSING)

Process 2 — P2 Consumer (article-processor)
  _processing_worker()
    while True:
      job = job_queue.get()
      for each article:
        repo.save_article()
        filter.is_ma_funding_relevant()   → bool
        if relevant: extractor.extract()  → DealData
        if deal: repo.save_deal()
      result_queue.put({type, source_name, new, deals})
```

- Scraping is I/O-bound → main process (no subprocess overhead per source).
- LLM calls + DB writes are CPU/network-bound → single dedicated subprocess keeps concurrency simple.
- IPC: `job_queue` (producer → consumer), `result_queue` (consumer → main).
- `STOP_PROCESSING` sentinel always sent in `finally` block — worker never hangs.

---

## Neo4j Graph Schema

### Nodes

| Label | ID Strategy | Properties |
|-------|-------------|-----------|
| `Article` | `uuid4` | `id`, `url`, `url_hash` (sha256), `source`, `title`, `content`, `scraped_at`, `published_at`, `is_ma_funding_relevant` (bool\|null), `is_processed` (bool) |
| `Deal` | `uuid4` | `id`, `deal_value`, `sector`, `sub_sector`, `country`, `deal_type`, `summary`, `extracted_at` |
| `Company` | `uuid5(normalized_name)` | `id`, `name` |

### Relationships

| Pattern | Meaning |
|---------|---------|
| `(Article)-[:HAS_DEAL]->(Deal)` | Article is source of this deal |
| `(Company)-[:BOUGHT]->(Deal)` | Acquirer in acquisition |
| `(Company)-[:SOLD]->(Deal)` | Target in acquisition / divesting party |
| `(Company)-[:INVESTED_IN]->(Deal)` | VC/PE investor in funding round |
| `(Company)-[:INVOLVED_IN]->(Deal)` | Startup receiving investment |
| `(Company)-[:ABOUT]->(Deal)` | Deal's subject when it is neither party — the listed company whose shares moved in a stake sale |

### Role → Relationship Mapping (`db/models.py`)

Defined in `models.py`, imported by both `repository.py` (write) and `queries.py`
(read) so the two cannot drift. `COMPANY_DEAL_RELS` joins them into the
`BOUGHT|SOLD|...` pattern every "any company on this deal" query must use.

```python
ROLE_TO_REL = {
    "buyer":    "BOUGHT",
    "seller":   "SOLD",
    "investor": "INVESTED_IN",
    "company":  "INVOLVED_IN",
    "target":   "ABOUT",
}

# funding_round → (investor, company); everything else → (buyer, seller)
def _roles_for_deal_type(deal_type): ...
```

### Constraints & Indexes (`models.py`)

Applied idempotently on every `NewsRepository.__init__()`:
- Unique constraints: `Article.id`, `Article.url`, `Deal.id`, `Company.name`
- Indexes: `url_hash`, `source`, `is_processed`, `is_ma_funding_relevant`, `scraped_at`, `sector`, `deal_type`, `extracted_at`, `Company.id`

---

## Company Name Normalization

`_normalize_company_name(name)` in `repository.py`:
1. Strip legal suffixes: `Pvt. Ltd.`, `Private Limited`, `Ltd.`, `Inc.`, `Corp.`, `LLP`, `LLC`, `GmbH`, `plc`, etc.
2. Strip trailing commas and whitespace.
3. Apply `.title()` for consistent casing.

`_company_id(name)` returns `uuid5(NAMESPACE_DNS, normalized_name)` — deterministic, so variants like `"Tata Sons Pvt. Ltd."` and `"Tata Sons"` resolve to the same ID.

Always normalize before querying by company name.

---

## URL Deduplication

SHA-256 hash of each URL stored as `url_hash`. Checked in both the producer (`_scrape_articles`) and consumer (`_process_source_articles`) before any work is done. This prevents reprocessing on re-runs.

---

## Deal Extraction — `DealData` Schema

```python
class DealData(BaseModel):
    buyer:       Optional[str]   # acquirer or investors (comma-separated)
    seller:      Optional[str]   # target or funded startup
    deal_value:  Optional[str]   # "₹18,000 crore", "$220 million"
    sector:      Optional[str]   # validated against SECTORS
    sub_sector:  Optional[str]   # required for D2C / Fintech / Others
    country:     Optional[str]
    deal_type:   Optional[str]   # acquisition | merger | funding_round | joint_venture | divestiture | partnership | other
    summary:     Optional[str]   # 2–3 sentence analyst summary
```

Validators normalize: case-insensitive sector match (unknown → `"Others"`), `"funding"` alias → `"funding_round"`.
All fields `None` when article is not about a deal.

LLM settings: `temperature=0.1`, `response_format={"type": "json_object"}`, content truncated to 4000 chars.

---

## Code Conventions

- **Datetimes:** Always timezone-aware IST (`UTC+5:30`). Stored as ISO 8601 strings in Neo4j.
- **UUIDs:** `uuid4()` for Articles/Deals. `uuid5(NAMESPACE_DNS, name)` for Companies.
- **Pydantic v2:** `@field_validator` + `@classmethod`. `model_validator` for cross-field logic.
- **Cypher:** Always `$param` parameterized. Never interpolate user-controlled strings into Cypher.
- **Logging:** Format `[LABEL|source|process] message`. `P1 producer` = scraper process, `P2 consumer` = processing subprocess.
- **Secrets:** Passed as CLI flags, defaulting to empty in `src/config.py`. Never hardcode a real credential there; never commit `news_agent.log`.
- **Scraper errors:** `extract_article()` must return `(None, None, None)` on any failure — never raise.

---

## Controlled Vocabularies (`extractor.py`)

```python
SECTORS = [
    "D2C", "Edtech", "Fintech", "Gaming", "Agency", "Marketplace",
    "SaaS", "Others", "AI/Deeptech/IoT", "Healthcare Services",
    "Hospitality/Restaurants", "IT Services/Products", "B2B Services", "Renewables/EV",
]

SUB_SECTORS = {
    "D2C":     ["Apparel", "B&P", "Personal Care", "F&B", "Footwear", "Healthcare", "H&H", "Jewellery", "Consumer Goods", "Others"],
    "Fintech": ["Insurance", "Lending/Wealthtech", "Payments", "Personal Finance", "Regulation Tech", "Others"],
    "Others":  ["Agritech", "Automobile", "Crypto/Blockchain", "Cybersecurity", "Logistics", "Manufacturing/Exports", "Marketplace", "Media", "Real Estate/Proptech", "Sports/Fitness-tech"],
}
```
