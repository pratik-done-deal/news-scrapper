from datetime import datetime, timedelta, timezone

from src.processor.company_signal import (
    CompanySignalScore,
    build_signal_context,
    collapse_duplicate_articles,
    empty_signal_snapshot,
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
