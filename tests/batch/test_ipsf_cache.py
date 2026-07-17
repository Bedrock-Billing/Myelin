from __future__ import annotations

from datetime import datetime

import pytest

from myelin.input import Claim, DiagnosisCode, PoaType, Provider
from myelin.pricers.ipsf import (
    IPSFProvider,
    clear_provider_cache,
    provider_cache_info,
)


@pytest.fixture(autouse=True)
def reset_cache():
    clear_provider_cache()
    yield
    clear_provider_cache()


def _claim_with_provider(ccn: str = "010001") -> Claim:
    c = Claim()
    c.claimid = "CACHE_TEST"
    c.principal_dx = DiagnosisCode(code="A021", poa=PoaType.Y)
    c.thru_date = datetime(2025, 7, 10)
    c.billing_provider = Provider()
    c.billing_provider.other_id = ccn
    return c


class _FakeEngine:
    """Minimal stand-in for an Engine so the cache test doesn't need a real DB."""


def test_provider_cache_info_starts_empty():
    info = provider_cache_info()
    assert info == {"hits": 0, "misses": 0, "size": 0, "max_size": 256}


def test_from_claim_without_cache_flag_ignores_cache(monkeypatch):
    called = {"count": 0}

    def fake_from_db(self, engine, provider, date_int, **kwargs):
        called["count"] += 1
        self.provider_ccn = provider.other_id
        self.case_mix_index = 1.5

    monkeypatch.setattr(IPSFProvider, "from_db", fake_from_db)

    c = _claim_with_provider()
    p = IPSFProvider()
    p.from_claim(c, _FakeEngine(), use_cache=False)
    assert called["count"] == 1
    info = provider_cache_info()
    assert info["misses"] == 0
    assert info["size"] == 0


def test_from_claim_with_cache_records_miss(monkeypatch):
    def fake_from_db(self, engine, provider, date_int, **kwargs):
        self.provider_ccn = provider.other_id
        self.case_mix_index = 1.5
        self.effective_date = date_int

    monkeypatch.setattr(IPSFProvider, "from_db", fake_from_db)

    c = _claim_with_provider()
    p = IPSFProvider()
    p.from_claim(c, _FakeEngine(), use_cache=True)
    info = provider_cache_info()
    assert info["misses"] == 1
    assert info["size"] == 1
    assert info["hits"] == 0


def test_from_claim_with_cache_records_hit_on_repeat(monkeypatch):
    def fake_from_db(self, engine, provider, date_int, **kwargs):
        self.provider_ccn = provider.other_id
        self.case_mix_index = 1.5
        self.effective_date = date_int

    monkeypatch.setattr(IPSFProvider, "from_db", fake_from_db)

    c1 = _claim_with_provider()
    p1 = IPSFProvider()
    p1.from_claim(c1, _FakeEngine(), use_cache=True)

    c2 = _claim_with_provider()
    p2 = IPSFProvider()
    p2.from_claim(c2, _FakeEngine(), use_cache=True)

    info = provider_cache_info()
    assert info["misses"] == 1
    assert info["hits"] == 1
    assert p2.provider_ccn == "010001"


def test_from_claim_with_cache_different_ccn_is_miss(monkeypatch):
    def fake_from_db(self, engine, provider, date_int, **kwargs):
        self.provider_ccn = provider.other_id
        self.case_mix_index = 1.0
        self.effective_date = date_int

    monkeypatch.setattr(IPSFProvider, "from_db", fake_from_db)

    c1 = _claim_with_provider("010001")
    IPSFProvider().from_claim(c1, _FakeEngine(), use_cache=True)

    c2 = _claim_with_provider("020002")
    IPSFProvider().from_claim(c2, _FakeEngine(), use_cache=True)

    info = provider_cache_info()
    assert info["misses"] == 2
    assert info["hits"] == 0
    assert info["size"] == 2


def test_clear_provider_cache_resets_state(monkeypatch):
    def fake_from_db(self, engine, provider, date_int, **kwargs):
        self.provider_ccn = provider.other_id
        self.case_mix_index = 1.0
        self.effective_date = date_int

    monkeypatch.setattr(IPSFProvider, "from_db", fake_from_db)

    c = _claim_with_provider()
    IPSFProvider().from_claim(c, _FakeEngine(), use_cache=True)
    assert provider_cache_info()["size"] == 1
    clear_provider_cache()
    assert provider_cache_info() == {
        "hits": 0,
        "misses": 0,
        "size": 0,
        "max_size": 256,
    }
