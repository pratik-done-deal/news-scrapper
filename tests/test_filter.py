from src.processor.filter import NewsFilter


def test_title_single_deal_signal_is_relevant():
    news_filter = NewsFilter()

    assert news_filter.is_ma_funding_relevant(
        "Reliance acquires fashion retailer for Rs 900 crore",
        "The companies declined to comment.",
    )


def test_single_incidental_content_signal_is_not_relevant():
    news_filter = NewsFilter()

    assert not news_filter.is_ma_funding_relevant(
        "Infosys reports quarterly results",
        "Management said large deal wins helped growth, but no acquisition was announced.",
    )


def test_two_content_signals_are_relevant():
    news_filter = NewsFilter()

    assert news_filter.is_ma_funding_relevant(
        "Startup expands credit product",
        "The company raised $20 million in a series b funding round led by investors.",
    )
