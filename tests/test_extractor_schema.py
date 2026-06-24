from src.processor.extractor import DealData


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
