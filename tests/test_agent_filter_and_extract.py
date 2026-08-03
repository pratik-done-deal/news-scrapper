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
    repo.get_recent_deal_articles.return_value = []
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
    repo.get_recent_deal_articles.return_value = []
    news_filter = MagicMock()
    extractor = MagicMock()
    news_filter.is_ma_funding_relevant.return_value = False

    processed, deals = _filter_and_extract_articles([_article("a1")], repo, news_filter, extractor)

    assert processed == 1
    assert deals == 0
    repo.mark_ma_funding_relevant.assert_called_once_with("a1", False)
    extractor.extract.assert_not_called()


def test_near_duplicate_article_is_linked_instead_of_re_extracted():
    repo = MagicMock()
    repo.get_recent_deal_articles.return_value = [
        {
            "id": "canonical-1",
            "title": "Acme acquires Target Co in $1M deal",
            "content": "Acme announced today it will acquire Target Co for $1M in cash.",
            "deal_id": "deal-1",
        }
    ]
    news_filter = MagicMock()
    news_filter.is_ma_funding_relevant.return_value = True
    extractor = MagicMock()

    duplicate_article = _article(
        "a2",
        source_name="cnbc",
        title="Acme acquires Target Co in $1M deal",
        content="Acme announced today it will acquire Target Co for $1M in cash.",
    )

    processed, deals = _filter_and_extract_articles([duplicate_article], repo, news_filter, extractor)

    assert processed == 1
    assert deals == 0
    extractor.extract.assert_not_called()
    repo.mark_duplicate_article.assert_called_once_with("a2", "canonical-1", is_relevant=True)


def test_thin_duplicate_skips_both_filter_and_extraction_via_deal_parties():
    # A thin/paywalled re-report of an already-extracted deal shares little
    # vocabulary with the original, but names both parties — it must be caught
    # BEFORE the relevance filter so neither LLM call is paid for.
    repo = MagicMock()
    repo.get_recent_deal_articles.return_value = [
        {
            "id": "canonical-1",
            "title": "upGrad set to close Unacademy acquisition; deal valued at Rs 1,955 Cr",
            "content": "upGrad is set to close its acquisition of Unacademy for Rs 1,955 crore.",
            "deal_id": "deal-1",
            "deal_value": "Rs 1,955 Cr",
            "parties": ["upGrad", "Unacademy"],
        }
    ]
    news_filter = MagicMock()
    extractor = MagicMock()

    thin_duplicate = _article(
        "a2",
        source_name="inc42",
        title="upGrad-Unacademy Merger Nears Completion",
        content="",
    )

    processed, deals = _filter_and_extract_articles([thin_duplicate], repo, news_filter, extractor)

    assert processed == 1
    assert deals == 0
    news_filter.is_ma_funding_relevant.assert_not_called()
    extractor.extract.assert_not_called()
    repo.mark_duplicate_article.assert_called_once_with("a2", "canonical-1", is_relevant=True)
