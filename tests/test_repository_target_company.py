"""The ABOUT link — how a stake sale's underlying company reaches the graph.

A block deal names the investor selling and the funds buying; the listed company
whose shares moved is neither. Before `target_company` existed it got no node at
all, so `GET /companies/search/news?name=Delhivery` returned nothing despite five
Delhivery deals sitting in the DB.
"""

from unittest.mock import MagicMock

import pytest

from src.db.models import COMPANY_DEAL_RELS, ROLE_TO_REL
from src.db.repository import NewsRepository


@pytest.fixture
def repo():
    """A repository whose session is mocked out — we assert on the Cypher issued."""
    repo = NewsRepository.__new__(NewsRepository)
    session = MagicMock()
    session.run.return_value.single.return_value = {"deal_id": "deal-1"}
    repo._session = MagicMock()
    repo._session.return_value.__enter__ = MagicMock(return_value=session)
    repo._session.return_value.__exit__ = MagicMock(return_value=False)
    repo._mock_session = session
    return repo


def _links(session):
    """(relationship type, company name) for every company MERGE issued."""
    out = []
    for call in session.run.call_args_list:
        query = call.args[0]
        if "MERGE (c:Company" not in query:
            continue
        rel = query.split("MERGE (c)-[:")[1].split("]")[0]
        out.append((rel, call.kwargs["name"]))
    return out


def test_target_company_gets_an_about_link(repo):
    repo.save_deal(
        article_id="a1",
        buyer="Morgan Stanley, Goldman Sachs",
        seller="Nexus Venture Partners",
        target_company="Delhivery",
        deal_value="Rs 530 crore",
        sector="Others",
        sub_sector="Logistics",
        country="India",
        deal_type="divestiture",
        summary="Nexus sold Delhivery shares via block deals.",
    )

    links = _links(repo._mock_session)
    assert ("ABOUT", "Delhivery") in links
    assert ("BOUGHT", "Morgan Stanley") in links
    assert ("SOLD", "Nexus Venture Partners") in links


def test_target_that_is_already_a_party_is_not_duplicated(repo):
    """An acquisition names its subject as the seller — no redundant ABOUT edge."""
    repo.save_deal(
        article_id="a2",
        buyer="Tata Sons",
        seller="Air India",
        target_company="Air India Ltd.",  # same company, legal suffix and all
        deal_value="Rs 18,000 crore",
        sector="Others",
        sub_sector=None,
        country="India",
        deal_type="acquisition",
        summary="Tata Sons acquired Air India.",
    )

    links = _links(repo._mock_session)
    assert ("SOLD", "Air India") in links
    assert not [rel for rel, _ in links if rel == "ABOUT"]


def test_absent_target_company_changes_nothing(repo):
    repo.save_deal(
        article_id="a3",
        buyer="Tiger Global",
        seller="Slice",
        deal_value="$220 million",
        sector="Fintech",
        sub_sector="Payments",
        country="India",
        deal_type="funding_round",
        summary="Slice raised $220M.",
    )

    links = _links(repo._mock_session)
    assert links == [("INVESTED_IN", "Tiger Global"), ("INVOLVED_IN", "Slice")]


def test_placeholder_party_names_are_not_stored_as_companies(repo):
    """An unattributed block deal must not mint a "Not Specified" company."""
    repo.save_deal(
        article_id="a4",
        buyer="Not specified",
        seller="Nexus Venture Partners",
        target_company="Delhivery",
        deal_value="Rs 208 crore",
        sector="Others",
        sub_sector="Logistics",
        country="India",
        deal_type="divestiture",
        summary="Nexus sold Delhivery shares; buyers were not disclosed.",
    )

    links = _links(repo._mock_session)
    assert links == [("SOLD", "Nexus Venture Partners"), ("ABOUT", "Delhivery")]


def test_about_is_part_of_the_shared_company_deal_rels():
    """Read sites build their pattern from this — ABOUT must be in it."""
    assert "ABOUT" in COMPANY_DEAL_RELS.split("|")
    assert set(COMPANY_DEAL_RELS.split("|")) == set(ROLE_TO_REL.values())
