from datetime import datetime

import pytest

from myelin.helpers.utils import supported_years


@pytest.fixture(autouse=True)
def no_override(monkeypatch):
    monkeypatch.delenv("IPPS_SUPPORTED_YEARS", raising=False)


def test_before_october_ends_at_current_year():
    assert supported_years("IPPS", datetime(2026, 9, 30)) == [2026, 2025, 2024, 2023]


def test_from_october_includes_next_fiscal_year():
    # FY2027 starts 2026-10-01; claims for it must be priceable right away.
    assert supported_years("IPPS", datetime(2026, 10, 1)) == [
        2027,
        2026,
        2025,
        2024,
        2023,
    ]
    assert supported_years("IPPS", datetime(2026, 12, 31)) == [
        2027,
        2026,
        2025,
        2024,
        2023,
    ]


def test_january_drops_oldest_year():
    assert supported_years("IPPS", datetime(2027, 1, 1)) == [2027, 2026, 2025, 2024]


def test_override_keeps_listed_recent_years(monkeypatch):
    monkeypatch.setenv("IPPS_SUPPORTED_YEARS", "2027, 2026,2019")
    assert supported_years("IPPS", datetime(2026, 11, 1)) == [2027, 2026]


def test_override_rejects_non_numbers(monkeypatch):
    monkeypatch.setenv("IPPS_SUPPORTED_YEARS", "2026,next")
    with pytest.raises(ValueError, match="IPPS_SUPPORTED_YEARS"):
        supported_years("IPPS", datetime(2026, 11, 1))
