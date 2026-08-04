"""Offline tests for the company-DB watchlist — search terms and the entity gate."""
import pytest

from src.db.names import normalize_company_name, strip_legal_suffix
from src.processor.watchlist import (
    WatchlistMatcher,
    build_entries,
    build_gate_terms,
    derive_search_term,
    gate_articles,
)


def row(name, brand=None, entity_type="seller", entity_id=1, website=None) -> dict:
    return {
        "entity_type": entity_type,
        "entity_id": entity_id,
        "company_name": name,
        "brand_name": brand,
        "website": website,
    }


# --------------------------------------------------------------------------
# Name helpers — normalize_company_name must stay byte-identical, it keys UUID5
# --------------------------------------------------------------------------

def test_normalize_company_name_unchanged_behaviour():
    assert normalize_company_name("  Tata Sons Pvt. Ltd. ") == "Tata Sons"
    assert normalize_company_name("ACME PRIVATE LIMITED") == "Acme"


def test_strip_legal_suffix_preserves_casing():
    assert strip_legal_suffix("ACME PRIVATE LIMITED") == "ACME"
    assert strip_legal_suffix("Nestle India Limited") == "Nestle India"
    assert strip_legal_suffix("BYJU'S") == "BYJU'S"


def test_strip_legal_suffix_collapses_whitespace():
    assert strip_legal_suffix("  Tata   Sons  Pvt. Ltd. ") == "Tata Sons"


def test_strip_legal_suffix_leaves_a_bare_name_alone():
    assert strip_legal_suffix("Swiggy") == "Swiggy"


# --------------------------------------------------------------------------
# Search term derivation
# --------------------------------------------------------------------------

def test_brand_name_wins_over_the_registered_name():
    assert derive_search_term(row("Bundl Technologies Private Limited", "Swiggy")) == "Swiggy"


def test_registered_name_is_stripped_when_there_is_no_brand():
    assert derive_search_term(row("Nestle India Limited")) == "Nestle India"


def test_blank_brand_falls_back_to_the_name():
    assert derive_search_term(row("Delhivery Limited", "   ")) == "Delhivery"


def test_missing_name_and_brand_yields_an_empty_term():
    assert derive_search_term(row(None)) == ""


# --------------------------------------------------------------------------
# Entry building
# --------------------------------------------------------------------------

def test_entries_carry_the_source_row_and_term():
    entries = build_entries([row("Bundl Technologies Private Limited", "Swiggy", entity_id=7)])
    assert len(entries) == 1
    entry = entries[0]
    assert entry.entity_id == 7
    assert entry.entity_type == "seller"
    assert entry.company_name == "Bundl Technologies Private Limited"
    assert entry.brand_name == "Swiggy"
    assert entry.search_term == "Swiggy"


def test_rows_collapsing_to_the_same_term_are_deduped():
    entries = build_entries([
        row("Bundl Technologies Private Limited", "Swiggy", entity_id=1),
        row("Swiggy", entity_type="lead", entity_id=2),
        row("swiggy limited", entity_type="buyer", entity_id=3),
    ])
    assert [e.search_term for e in entries] == ["Swiggy"]
    assert entries[0].entity_id == 1  # first row wins


def test_terms_shorter_than_the_minimum_are_dropped():
    entries = build_entries([row("BP", entity_id=1), row("ITC Limited", entity_id=2)])
    assert [e.search_term for e in entries] == ["ITC"]


def test_min_term_length_is_configurable():
    entries = build_entries([row("BP", entity_id=1)], min_term_length=2)
    assert [e.search_term for e in entries] == ["BP"]


def test_generic_terms_are_dropped():
    # A suffix-only name normalises to something that would match half the wire.
    entries = build_entries([row("India Limited", entity_id=1), row("Zepto", entity_id=2)])
    assert [e.search_term for e in entries] == ["Zepto"]


def test_empty_rows_yield_no_entries():
    assert build_entries([]) == []


# --------------------------------------------------------------------------
# Gate terms — wider than search terms on purpose
# --------------------------------------------------------------------------

def test_gate_terms_include_both_the_brand_and_the_registered_name():
    terms = build_gate_terms([row("Bundl Technologies Private Limited", "Swiggy")])
    assert terms == ["Swiggy", "Bundl Technologies"]


def test_gate_terms_deduplicate_across_rows():
    terms = build_gate_terms([
        row("Swiggy", entity_id=1),
        row("Swiggy Limited", entity_type="lead", entity_id=2),
    ])
    assert terms == ["Swiggy"]


def test_gate_terms_skip_short_and_generic_names():
    terms = build_gate_terms([row("BP", entity_id=1), row("India Limited", entity_id=2)])
    assert terms == []


def test_gate_terms_handle_a_missing_brand():
    assert build_gate_terms([row("Nestle India Limited")]) == ["Nestle India"]


def test_gate_terms_are_wider_than_search_terms():
    rows = [
        row("Bundl Technologies Private Limited", "Swiggy", entity_id=1),
        row("ANI Technologies Private Limited", "Ola", entity_id=2),
    ]
    assert len(build_gate_terms(rows)) == 4
    assert len(build_entries(rows)) == 2


# --------------------------------------------------------------------------
# Matcher
# --------------------------------------------------------------------------

def test_matches_a_name_in_the_title():
    matcher = WatchlistMatcher(["Swiggy"])
    assert matcher.match("Swiggy acquires a delivery startup", None) == ["Swiggy"]


def test_matches_a_name_in_the_content():
    matcher = WatchlistMatcher(["Zepto"])
    assert matcher.match("Quick commerce update", "The round was led into Zepto.") == ["Zepto"]


def test_matching_is_case_insensitive():
    matcher = WatchlistMatcher(["Zepto"])
    assert matcher.match("ZEPTO raises funds", None) == ["Zepto"]


def test_does_not_match_a_longer_word():
    matcher = WatchlistMatcher(["Ola"])
    assert matcher.match("Olive oil prices climb", "Olafson said nothing") == []


def test_does_not_match_a_word_prefix():
    matcher = WatchlistMatcher(["Zepto"])
    assert matcher.match("Zeptolab ships a new game", None) == []


def test_matches_a_multi_word_name():
    matcher = WatchlistMatcher(["Nestle India"])
    assert matcher.match("Nestle India reports growth", None) == ["Nestle India"]


def test_multi_word_name_tolerates_punctuation_between_tokens():
    matcher = WatchlistMatcher(["Peak XV"])
    assert matcher.match("Peak-XV backs the round", None) == ["Peak XV"]


def test_multi_word_name_does_not_match_only_its_first_token():
    matcher = WatchlistMatcher(["Nestle India"])
    assert matcher.match("Nestle SA reports growth", None) == []


def test_returns_every_matching_company():
    matcher = WatchlistMatcher(["Swiggy", "Zomato", "Zepto"])
    matched = matcher.match("Swiggy and Zomato both bid", "Zepto stayed out")
    assert sorted(matched) == ["Swiggy", "Zepto", "Zomato"]


def test_no_text_matches_nothing():
    matcher = WatchlistMatcher(["Swiggy"])
    assert matcher.match(None, None) == []


def test_empty_matcher_matches_nothing():
    matcher = WatchlistMatcher([])
    assert len(matcher) == 0
    assert matcher.match("Swiggy acquires something", None) == []


def test_terms_with_no_usable_tokens_are_skipped():
    matcher = WatchlistMatcher(["!!!", "Swiggy"])
    assert matcher.terms == ["Swiggy"]


def test_first_token_index_agrees_with_a_brute_force_scan():
    import re

    terms = ["Swiggy", "Nestle India", "Peak XV", "Zepto", "Ather", "Blue Tokai", "ITC"]
    corpus = [
        "Swiggy and Zepto raise; Nestle India watches",
        "Peak XV leads Ather's round",
        "Blue Tokai opens stores, ITC responds",
        "No tracked company here at all",
        "Olive oil and Zeptolab are not matches",
    ]
    matcher = WatchlistMatcher(terms)
    for text in corpus:
        brute = sorted(
            t for t in terms
            if re.search(
                r"(?<![A-Za-z0-9])" + r"[^A-Za-z0-9]+".join(re.escape(p) for p in t.lower().split())
                + r"(?![A-Za-z0-9])",
                text,
                re.IGNORECASE,
            )
        )
        assert sorted(matcher.match(text, None)) == brute


# --------------------------------------------------------------------------
# Gate
# --------------------------------------------------------------------------

def test_gate_keeps_only_matching_articles():
    matcher = WatchlistMatcher(["Swiggy", "Nestle India"])
    articles = [
        {"url": "a", "title": "Swiggy buys a dark store chain", "content": ""},
        {"url": "b", "title": "Monsoon update", "content": "Rain across the west"},
        {"url": "c", "title": "Deal news", "content": "Nestle India confirmed the deal"},
    ]
    kept, dropped = gate_articles(articles, matcher)
    assert [a["url"] for a in kept] == ["a", "c"]
    assert dropped == 1


def test_gate_annotates_kept_articles_with_matches():
    matcher = WatchlistMatcher(["Swiggy"])
    kept, _ = gate_articles([{"url": "a", "title": "Swiggy raises", "content": ""}], matcher)
    assert kept[0]["matched_entities"] == ["Swiggy"]


def test_gate_does_not_mutate_the_input_articles():
    matcher = WatchlistMatcher(["Swiggy"])
    article = {"url": "a", "title": "Swiggy raises", "content": ""}
    gate_articles([article], matcher)
    assert "matched_entities" not in article


def test_gate_on_an_empty_list():
    assert gate_articles([], WatchlistMatcher(["Swiggy"])) == ([], 0)


@pytest.mark.parametrize("field", ["title", "content"])
def test_gate_handles_missing_fields(field):
    matcher = WatchlistMatcher(["Swiggy"])
    article = {"url": "a", field: "Swiggy raises a round"}
    kept, dropped = gate_articles([article], matcher)
    assert len(kept) == 1 and dropped == 0
