from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from src.db.repository import NewsRepository


def _make_repo() -> NewsRepository:
    with patch("src.db.repository.GraphDatabase"):
        return NewsRepository(uri="bolt://x", user="u", password="p")


def _mock_session_returning(repo: NewsRepository, existing_hashes: list[str]) -> MagicMock:
    session = MagicMock()
    session.run.side_effect = [
        [{"h": h} for h in existing_hashes],  # existing url_hash lookup
        None,                                  # UNWIND ... CREATE write
    ]
    repo._session = MagicMock()
    repo._session.return_value.__enter__.return_value = session
    repo._session.return_value.__exit__.return_value = False
    return session


def test_save_articles_batch_skips_existing_and_returns_inserted():
    repo = _make_repo()
    existing_url = "https://example.com/existing"
    new_url = "https://example.com/new"
    existing_hash = repo._hash_url(existing_url)

    _mock_session_returning(repo, [existing_hash])

    articles = [
        {
            "url": existing_url,
            "title": "Old",
            "content": "old content",
            "published_date": None,
            "source_name": "et",
        },
        {
            "url": new_url,
            "title": "New",
            "content": "new content",
            "published_date": datetime(2025, 1, 1, tzinfo=timezone.utc),
            "source_name": "et",
        },
    ]

    inserted = repo.save_articles_batch(articles)

    assert len(inserted) == 1
    assert inserted[0]["url"] == new_url
    assert inserted[0]["url_hash"] == repo._hash_url(new_url)
    assert inserted[0]["id"]
    assert inserted[0]["published_at"] == "2025-01-01T00:00:00+00:00"


def test_save_articles_batch_empty_input_short_circuits():
    repo = _make_repo()
    assert repo.save_articles_batch([]) == []


def test_save_articles_batch_all_existing_returns_empty():
    repo = _make_repo()
    url = "https://example.com/existing"
    existing_hash = repo._hash_url(url)

    _mock_session_returning(repo, [existing_hash])

    articles = [{
        "url": url,
        "title": "Old",
        "content": "old content",
        "published_date": None,
        "source_name": "et",
    }]

    assert repo.save_articles_batch(articles) == []
