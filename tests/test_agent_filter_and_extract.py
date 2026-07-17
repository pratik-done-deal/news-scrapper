from unittest.mock import MagicMock

from src.agent import _filter_and_extract_articles


def _article(article_id: str, **overrides) -> dict:
    base = {
        "id": article_id,
        "source_name": "et",
        "title": f"Title {article_id}",
        "content": f"Content {article_id}",
        "url": f"https://example.com/{article_id}",
        "published_date": None,
    }
    base.update(overrides)
    return base


def test_one_article_failure_does_not_block_the_rest_of_the_batch():
    repo = MagicMock()
    news_filter = MagicMock()
    extractor = MagicMock()

    news_filter.is_ma_funding_relevant.side_effect = [RuntimeError("boom"), True]
    extractor.extract.return_value = MagicMock(
        buyer="Acme", seller="Target Co", deal_value="$1M", sector="Fintech",
        sub_sector=None, country="India", deal_type="acquisition", summary="summary",
    )

    articles = [_article("a1"), _article("a2")]

    processed, deals = _filter_and_extract_articles(articles, repo, news_filter, extractor)

    # a1's exception is swallowed and skipped; a2 still gets fully processed.
    assert processed == 1
    assert deals == 1
    repo.mark_ma_funding_relevant.assert_called_once_with("a2", True)
    repo.save_deal.assert_called_once()


def test_not_relevant_article_is_marked_but_not_extracted():
    repo = MagicMock()
    news_filter = MagicMock()
    extractor = MagicMock()
    news_filter.is_ma_funding_relevant.return_value = False

    processed, deals = _filter_and_extract_articles([_article("a1")], repo, news_filter, extractor)

    assert processed == 1
    assert deals == 0
    repo.mark_ma_funding_relevant.assert_called_once_with("a1", False)
    extractor.extract.assert_not_called()
