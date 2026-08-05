from unittest.mock import MagicMock, patch

from src.db.repository import NewsRepository


def _make_repo() -> NewsRepository:
    with patch("src.db.repository.GraphDatabase"):
        return NewsRepository(uri="bolt://x", user="u", password="p")


def _mock_session_returning(repo: NewsRepository, rows: list[dict]) -> MagicMock:
    session = MagicMock()
    session.run.return_value = [{"a": row} for row in rows]
    repo._session = MagicMock()
    repo._session.return_value.__enter__.return_value = session
    repo._session.return_value.__exit__.return_value = False
    return session


def test_get_unprocessed_articles_queries_null_relevance_and_renames_source():
    repo = _make_repo()
    session = _mock_session_returning(repo, [
        {"id": "a1", "url": "https://x/1", "source": "et", "title": "T", "content": "C"},
    ])

    result = repo.get_unprocessed_articles()

    query = session.run.call_args[0][0]
    assert "is_ma_funding_relevant IS NULL" in query
    assert "LIMIT" not in query

    assert len(result) == 1
    assert result[0]["source_name"] == "et"
    assert "source" not in result[0]


def test_get_unprocessed_articles_applies_limit():
    repo = _make_repo()
    session = _mock_session_returning(repo, [])

    repo.get_unprocessed_articles(limit=5)

    query, kwargs = session.run.call_args[0][0], session.run.call_args[1]
    assert "LIMIT $limit" in query
    assert kwargs["limit"] == 5


def test_get_unprocessed_articles_empty_result():
    repo = _make_repo()
    _mock_session_returning(repo, [])

    assert repo.get_unprocessed_articles() == []
