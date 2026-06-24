from src.db.repository import _company_id, _normalize_company_name, _roles_for_deal_type


def test_company_name_normalization_strips_legal_suffixes():
    assert _normalize_company_name("  Tata Sons Pvt. Ltd. ") == "Tata Sons"
    assert _normalize_company_name("ACME PRIVATE LIMITED") == "Acme"


def test_company_id_is_stable_across_legal_suffix_variants():
    assert _company_id("Tata Sons Pvt. Ltd.") == _company_id("Tata Sons")


def test_funding_round_uses_investor_company_roles():
    assert _roles_for_deal_type("funding_round") == ("investor", "company")
    assert _roles_for_deal_type("acquisition") == ("buyer", "seller")
