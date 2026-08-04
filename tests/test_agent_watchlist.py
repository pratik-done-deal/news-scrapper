"""Offline tests for NewsAgent.scrape_watchlist — job fan-out, gating, one extraction.

The process pool and Neo4j are stubbed out: what matters here is which
`(source, company)` jobs get built, which articles survive the gate, and that
filter/extraction runs exactly once per run rather than once per company.
"""
import pytest

from src.agent import NewsAgent
from src.processor.watchlist import WatchlistMatcher, build_entries

SEARCHABLE_A = {"name": "Entrackr News", "search_url": "https://e.com/search?title={query}"}
SEARCHABLE_B = {"name": "ISN Funding", "search_url": "https://i.com/search?title={query}"}
LISTING_A = {"name": "Economic Times Corporate"}
LISTING_B = {"name": "CNBC Deals"}

ALL_SOURCES = [SEARCHABLE_A, SEARCHABLE_B, LISTING_A, LISTING_B]


class StubAgent(NewsAgent):
    """A NewsAgent with the process pool, storage and extraction replaced."""

    def __init__(self, scraped=None):
        # Deliberately skips NewsAgent.__init__ — no Neo4j, no Groq, no config.
        self.batch_size = 10
        self.max_articles = 20
        self.repo = None
        self.jobs_seen: list[tuple[str, str | None]] = []
        self.stored: list[list[dict]] = []
        self.extract_calls = 0
        self._scraped = scraped or []

    def _run_scrape_jobs(self, jobs, dt_start, dt_end, counters):
        self.jobs_seen = [(source["name"], company) for source, company in jobs]
        return len(self._scraped), list(self._scraped)

    def extract_pending(self, limit=None):
        self.extract_calls += 1
        return {"processed": 0, "deals": 3, "errors": []}


@pytest.fixture(autouse=True)
def _no_real_storage(monkeypatch):
    stored: list[list[dict]] = []

    def fake_store(batch, repo):
        stored.append(batch)
        return batch

    monkeypatch.setattr("src.agent._store_batch", fake_store)
    return stored


def entries_for(*names):
    return build_entries(
        [
            {
                "entity_type": "seller",
                "entity_id": i,
                "company_name": name,
                "brand_name": None,
                "website": None,
            }
            for i, name in enumerate(names, start=1)
        ]
    )


def article(url, title, content="", searched_company=None):
    return {
        "url": url,
        "title": title,
        "content": content,
        "published_date": None,
        "source_name": "src",
        "searched_company": searched_company,
    }


# --------------------------------------------------------------------------
# Job fan-out
# --------------------------------------------------------------------------

def test_builds_one_search_job_per_source_and_entity():
    agent = StubAgent()
    agent.scrape_watchlist(
        entries=entries_for("Swiggy", "Zepto"),
        sources=[SEARCHABLE_A, SEARCHABLE_B],
        matcher=None,
    )
    assert sorted(agent.jobs_seen) == sorted([
        ("Entrackr News", "Swiggy"),
        ("Entrackr News", "Zepto"),
        ("ISN Funding", "Swiggy"),
        ("ISN Funding", "Zepto"),
    ])


def test_listing_sources_get_one_untargeted_job_each():
    agent = StubAgent()
    agent.scrape_watchlist(
        entries=entries_for("Swiggy"),
        sources=ALL_SOURCES,
        matcher=WatchlistMatcher(["Swiggy"]),
    )
    listing_jobs = [j for j in agent.jobs_seen if j[1] is None]
    assert sorted(listing_jobs) == [("CNBC Deals", None), ("Economic Times Corporate", None)]


def test_listing_sources_are_skipped_without_a_matcher():
    agent = StubAgent()
    agent.scrape_watchlist(entries=entries_for("Swiggy"), sources=ALL_SOURCES, matcher=None)
    assert all(company is not None for _, company in agent.jobs_seen)


def test_max_search_entities_caps_the_fan_out():
    agent = StubAgent()
    counters = agent.scrape_watchlist(
        entries=entries_for("Swiggy", "Zepto", "Ather", "Groww"),
        sources=[SEARCHABLE_A],
        matcher=None,
        max_search_entities=2,
    )
    assert len(agent.jobs_seen) == 2
    assert counters["entities"] == 2
    assert counters["search_jobs"] == 2


def test_no_entities_still_runs_the_gated_listing_sources():
    agent = StubAgent()
    counters = agent.scrape_watchlist(
        entries=[], sources=ALL_SOURCES, matcher=WatchlistMatcher(["Swiggy"])
    )
    assert agent.jobs_seen == [("Economic Times Corporate", None), ("CNBC Deals", None)]
    assert counters["search_jobs"] == 0


def test_nothing_to_do_reports_an_error_and_does_not_extract():
    agent = StubAgent()
    counters = agent.scrape_watchlist(entries=[], sources=[LISTING_A], matcher=None)
    assert counters["errors"] == ["no scrape jobs to run"]
    assert agent.extract_calls == 0


# --------------------------------------------------------------------------
# Gating
# --------------------------------------------------------------------------

def test_listing_articles_are_gated_but_search_hits_are_kept(_no_real_storage):
    scraped = [
        article("s1", "Anything at all", searched_company="Swiggy"),   # targeted
        article("l1", "Swiggy buys a chain"),                          # listing, matches
        article("l2", "Monsoon update", "rain everywhere"),            # listing, no match
    ]
    agent = StubAgent(scraped=scraped)
    counters = agent.scrape_watchlist(
        entries=entries_for("Swiggy"),
        sources=ALL_SOURCES,
        matcher=WatchlistMatcher(["Swiggy"]),
    )

    stored_urls = [a["url"] for batch in _no_real_storage for a in batch]
    assert sorted(stored_urls) == ["l1", "s1"]
    assert counters["gated_out"] == 1


def test_targeted_article_survives_even_when_it_names_no_tracked_company(_no_real_storage):
    # The search itself was the restriction, so the gate must not second-guess it.
    agent = StubAgent(scraped=[article("s1", "Untitled", searched_company="Swiggy")])
    agent.scrape_watchlist(
        entries=entries_for("Swiggy"),
        sources=[SEARCHABLE_A],
        matcher=WatchlistMatcher(["Zomato"]),
    )
    assert [a["url"] for batch in _no_real_storage for a in batch] == ["s1"]


def test_without_a_matcher_nothing_is_gated(_no_real_storage):
    agent = StubAgent(scraped=[article("l1", "Monsoon update")])
    counters = agent.scrape_watchlist(
        entries=entries_for("Swiggy"), sources=[SEARCHABLE_A], matcher=None
    )
    assert counters["gated_out"] == 0
    assert [a["url"] for batch in _no_real_storage for a in batch] == ["l1"]


# --------------------------------------------------------------------------
# Extraction happens once, not per company
# --------------------------------------------------------------------------

def test_extraction_runs_once_regardless_of_entity_count():
    agent = StubAgent(scraped=[article("s1", "x", searched_company="Swiggy")])
    counters = agent.scrape_watchlist(
        entries=entries_for("Swiggy", "Zepto", "Ather"),
        sources=[SEARCHABLE_A, SEARCHABLE_B],
        matcher=None,
    )
    assert len(agent.jobs_seen) == 6
    assert agent.extract_calls == 1
    assert counters["deals"] == 3


def test_storage_respects_the_batch_size(_no_real_storage):
    scraped = [article(f"s{i}", "x", searched_company="Swiggy") for i in range(25)]
    agent = StubAgent(scraped=scraped)
    agent.batch_size = 10
    agent.scrape_watchlist(
        entries=entries_for("Swiggy"), sources=[SEARCHABLE_A], matcher=None
    )
    assert [len(batch) for batch in _no_real_storage] == [10, 10, 5]


def test_counters_report_the_run():
    agent = StubAgent(scraped=[article("s1", "x", searched_company="Swiggy")])
    counters = agent.scrape_watchlist(
        entries=entries_for("Swiggy"), sources=[SEARCHABLE_A], matcher=None
    )
    assert counters["entities"] == 1
    assert counters["search_jobs"] == 1
    assert counters["scraped"] == 1
    assert counters["new"] == 1
    assert counters["errors"] == []
