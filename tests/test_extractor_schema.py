import json
from types import SimpleNamespace

from src.processor import extractor as extractor_module
from src.processor.extractor import DealData, DealExtractor


def test_deal_type_alias_is_normalized():
    deal = DealData(deal_type="funding")

    assert deal.deal_type == "funding_round"


def test_unknown_sector_falls_back_to_others():
    deal = DealData(sector="Space Tech")

    assert deal.sector == "Others"


def test_sub_sector_case_is_normalized():
    deal = DealData(sector="fintech", sub_sector="payments")

    assert deal.sector == "Fintech"
    assert deal.sub_sector == "Payments"


class _StubClient:
    """Minimal stand-in for the chat client: returns `payload` as the content."""

    def __init__(self, payload):
        content = json.dumps(payload)
        completion = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
        )
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=lambda **kwargs: completion)
        )


def _extractor(monkeypatch, payload) -> DealExtractor:
    # The real extractor sleeps after every call to pace the API; a unit test
    # has no reason to wait for it.
    monkeypatch.setattr(extractor_module.time, "sleep", lambda _seconds: None)
    return DealExtractor(_StubClient(payload), "test-model")


def test_single_deal_object_is_extracted(monkeypatch):
    payload = {"buyer": "Tiger Global", "seller": "Slice", "deal_type": "funding_round"}

    deal = _extractor(monkeypatch, payload).extract("Slice raises $220M", "content")

    assert deal is not None
    assert deal.buyer == "Tiger Global"


def test_multi_deal_list_is_skipped(monkeypatch):
    """Roundup articles come back as a LIST of deals.

    The graph stores one deal per article (`d.article_id` is uniquely
    constrained), so the extractor must skip these rather than pick one
    arbitrarily and attribute the whole roundup's value to it.
    """
    payload = [
        {"buyer": "Elev8", "seller": "River Mobility", "deal_value": "$120 million"},
        {"buyer": "Singularity AMC", "seller": "BlissClub", "deal_value": "Rs 160 crore"},
    ]

    deal = _extractor(monkeypatch, payload).extract("Startups raised $252M this week", "content")

    assert deal is None


def test_multi_deal_skip_is_logged_as_a_warning(monkeypatch, caplog):
    """The skip has to be countable in the logs, not silent."""
    payload = [{"buyer": "Elev8", "seller": "River Mobility"}]

    with caplog.at_level("WARNING"):
        _extractor(monkeypatch, payload).extract("Weekly funding roundup", "content")

    assert any("Skipping multi-deal article" in record.message for record in caplog.records)
