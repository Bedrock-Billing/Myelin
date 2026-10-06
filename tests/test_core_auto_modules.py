from unittest.mock import MagicMock, patch

import pytest

from myelin import IPSFProvider, Myelin, OPSFProvider
from myelin.helpers.claim_examples import claim_example
from myelin.input import Modules

CLIENT_ATTRS = (
    "mce_client ioce_client drg_client hhag_client irfg_client ipps_client "
    "opps_client ipf_client ltch_client irf_client hospice_client snf_client "
    "hha_client esrd_client fqhc_client asc_client"
).split()


@pytest.fixture
def stub_myelin():
    """Myelin instance with no JVM, a fake DB engine, and no clients."""
    m = Myelin.__new__(Myelin)
    m.db_manager = MagicMock()
    m.db_manager.engine = object()
    m.logger = MagicMock()
    for attr in CLIENT_ATTRS:
        setattr(m, attr, None)
    m.icd10_converter = None
    with (
        patch.object(IPSFProvider, "from_claim", lambda *a, **k: None),
        patch.object(OPSFProvider, "from_claim", lambda *a, **k: None),
    ):
        yield m


def _inpatient_auto_claim():
    claim = claim_example()
    claim.bill_type = "111"
    claim.lines = [
        line for line in claim.lines if line.revenue_code not in ("0022", "0024")
    ]
    claim.modules = [Modules.AUTO]
    return claim


def test_auto_mode_does_not_mutate_claim(stub_myelin):
    claim = _inpatient_auto_claim()
    generated = []
    orig = Myelin._generate_auto_modules

    def spy(self, *args):
        mods = orig(self, *args)
        generated.append(mods)
        return mods

    with patch.object(Myelin, "_generate_auto_modules", spy):
        first = stub_myelin.process(claim)
        second = stub_myelin.process(claim)

    assert claim.modules == [Modules.AUTO]
    assert second.error != "Auto module cannot be paired with any other module request"
    assert first.model_dump() == second.model_dump()
    assert len(generated) == 2
    assert generated[0] == generated[1]
    assert Modules.AUTO not in generated[0]


def test_duplicate_auto_is_accepted(stub_myelin):
    claim = _inpatient_auto_claim()
    claim.modules = [Modules.AUTO, Modules.AUTO]
    result = stub_myelin.process(claim)
    assert result.error != "Auto module cannot be paired with any other module request"


def test_auto_paired_with_other_module_is_rejected(stub_myelin):
    claim = _inpatient_auto_claim()
    claim.modules = [Modules.AUTO, Modules.MCE]
    result = stub_myelin.process(claim)
    assert result.error == "Auto module cannot be paired with any other module request"
