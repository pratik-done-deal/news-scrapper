import pytest
from pydantic import ValidationError

from src.api.schemas import ScrapeRequest


def test_scrape_request_accepts_iso_dates():
    request = ScrapeRequest(start_date="2025-01-01", end_date="2025-01-31")

    assert request.start_date == "2025-01-01"
    assert request.end_date == "2025-01-31"


def test_scrape_request_rejects_non_iso_dates():
    with pytest.raises(ValidationError):
        ScrapeRequest(start_date="01-01-2025")
