from datetime import datetime, timedelta, timezone

from src.processor.company_signal import (
    CompanySignalScore,
    are_duplicate_articles,
    article_names_parties,
    build_signal_context,
    collapse_duplicate_articles,
    deal_amount_token,
    empty_signal_snapshot,
    is_duplicate_of_deal,
    news_decay_weight,
)


def test_news_decay_weight_uses_configured_buckets():
    now = datetime(2026, 6, 24, tzinfo=timezone.utc)

    assert news_decay_weight(now - timedelta(days=3), now) == 1.0
    assert news_decay_weight(now - timedelta(days=10), now) == 0.65
    assert news_decay_weight(now - timedelta(days=20), now) == 0.35
    assert news_decay_weight(now - timedelta(days=45), now) == 0.1


def test_collapse_duplicate_articles_groups_matching_titles():
    articles = [
        {
            "id": "a1",
            "title": "Acme is in talks to acquire Beta",
            "source": "one",
            "content": "Acme is in advanced talks to buy Beta for 500 crore.",
        },
        {
            "id": "a2",
            "title": "Acme may buy Beta as acquisition discussions advance",
            "source": "two",
            "content": "Acme is in advanced discussions to acquire Beta for around 500 crore.",
        },
        {"id": "a3", "title": "Acme plans a new market entry", "source": "one"},
    ]

    collapsed = collapse_duplicate_articles(articles)

    assert len(collapsed) == 2
    duplicate = next(item for item in collapsed if item["id"] == "a1")
    assert duplicate["duplicate_count"] == 2
    assert duplicate["duplicate_article_ids"] == ["a1", "a2"]


def test_are_duplicate_articles_matches_same_deal_across_outlets():
    # Same funding round, two outlets: different headline framing, company name
    # spelled differently (ReoDev vs Reo.Dev), amount written differently.
    left = {
        "title": "AI GTM startup ReoDev raises $11.3 million Series A funding led by Elevation Capital",
        "content": "",
    }
    right = {
        "title": "Exclusive: AI sales intelligence startup Reo.Dev raises $11.3 Mn to expand in US",
        "content": "",
    }

    assert are_duplicate_articles(left, right)


def test_are_duplicate_articles_rejects_same_company_different_event():
    left = {
        "title": "AI GTM startup ReoDev raises $11.3 million Series A funding led by Elevation Capital",
        "content": "",
    }
    other_event = {"title": "ReoDev appoints new CTO to lead engineering team", "content": ""}

    assert not are_duplicate_articles(left, other_event)


def test_deal_amount_token_extracts_normalised_amount():
    assert deal_amount_token("Rs 1,955 Cr") == "amt1955"
    assert deal_amount_token("₹1,955 Cr") == "amt1955"
    assert deal_amount_token(None) is None
    assert deal_amount_token("undisclosed") is None


def test_is_duplicate_of_deal_catches_thin_paywalled_report_via_parties():
    # The exact production miss: a thin/paywalled re-report shares almost no
    # vocabulary with the original and carries no amount, so plain token overlap
    # (are_duplicate_articles) fails — but it names both parties of the deal.
    thin_report = {"title": "upGrad-Unacademy Merger Nears Completion", "content": ""}
    canonical = {
        "title": "upGrad set to close Unacademy acquisition in three weeks; deal valued at Rs 1,955 Cr",
        "content": "upGrad is set to close its acquisition of Unacademy in an all-stock transaction.",
    }

    # Token overlap alone misses it...
    assert not are_duplicate_articles(thin_report, canonical)
    # ...but the deal-aware check catches it on the buyer/seller pair.
    assert is_duplicate_of_deal(
        thin_report, canonical, parties=["upGrad", "Unacademy"], amount_token="amt1955"
    )


def test_is_duplicate_of_deal_single_party_needs_matching_amount():
    # Naming only one side is not enough on its own; it needs the shared amount.
    article = {"title": "upGrad plans fresh expansion push", "content": "amt1955 in play"}
    assert is_duplicate_of_deal(
        article, {"title": "x", "content": ""}, parties=["upGrad", "Unacademy"], amount_token="amt1955"
    )
    assert not is_duplicate_of_deal(
        article, {"title": "x", "content": ""}, parties=["upGrad", "Unacademy"], amount_token=None
    )


def test_article_names_parties_requires_all_name_tokens():
    article = {"title": "Omega Seiki raises fresh capital", "content": ""}
    assert article_names_parties(article, ["Omega Seiki"]) == 1
    # Partial name match ("Omega" only) does not count.
    assert article_names_parties({"title": "Omega bakery opens", "content": ""}, ["Omega Seiki"]) == 0


def test_build_signal_context_counts_collapsed_duplicates():
    now = datetime(2026, 6, 24, tzinfo=timezone.utc)
    articles = [
        {
            "id": "a1",
            "title": "Acme looks to raise funds",
            "source": "one",
            "published_at": now.isoformat(),
            "content": "Acme is exploring a fresh round.",
        },
        {
            "id": "a2",
            "title": "Acme looks to raise funds",
            "source": "two",
            "published_at": now.isoformat(),
            "content": "Acme is exploring a fresh round.",
        },
    ]

    context, duplicates_collapsed = build_signal_context("Acme", articles, [], now)

    assert duplicates_collapsed == 1
    assert context[0]["recent_articles"][0]["duplicate_count"] == 2
    assert context[0]["recent_articles"][0]["decay_weight"] == 1.0


def test_signal_score_clamps_llm_probability_values():
    score = CompanySignalScore(
        invest_probability="120",
        fundraise_probability="-5",
        acquisition_target_probability="42.6",
        confidence="low",
        direction="stable",
        is_speculative=True,
        explanation="Speculative early signal.",
    )

    assert score.invest_probability == 100
    assert score.fundraise_probability == 0
    assert score.acquisition_target_probability == 43


def test_signal_score_accepts_common_llm_enum_variants():
    score = CompanySignalScore(
        invest_probability=20,
        fundraise_probability=80,
        acquisition_target_probability=15,
        confidence="Medium",
        direction="Increasing",
        is_speculative=True,
        positive_signals={
            "signal_type": "funding_talks",
            "target_score": "fundraise_probability",
            "strength": "High",
            "polarity": "+",
            "impact": 20,
        },
        negative_signals=None,
        evidence_articles={"title": "Cred raises funding", "decay_weight": 1},
        explanation=None,
    )

    assert score.confidence == "medium"
    assert score.direction == "rising"
    assert score.positive_signals[0].target_score == "fundraise"
    assert score.positive_signals[0].strength == "strong"
    assert score.positive_signals[0].polarity == "positive"
    assert score.positive_signals[0].impact == "20"
    assert score.negative_signals == []
    assert score.evidence_articles[0].article_id is None


def test_empty_signal_snapshot_sets_low_speculative_baseline():
    snapshot = empty_signal_snapshot("company-id", "Acme", 30)

    assert snapshot.company_name == "Acme"
    assert snapshot.invest_probability == 5
    assert snapshot.fundraise_probability == 5
    assert snapshot.acquisition_target_probability == 5
    assert snapshot.confidence == "low"
    assert snapshot.is_speculative is True
