from datetime import timezone, timedelta

from src.agent import _to_ist_datetime


IST = timezone(timedelta(hours=5, minutes=30))


def test_to_ist_datetime_start_of_day():
    value = _to_ist_datetime("2025-01-01")

    assert value.tzinfo == IST
    assert value.hour == 0
    assert value.minute == 0


def test_to_ist_datetime_end_of_day():
    value = _to_ist_datetime("2025-01-01", end_of_day=True)

    assert value.tzinfo == IST
    assert value.hour == 23
    assert value.minute == 59
    assert value.second == 59
