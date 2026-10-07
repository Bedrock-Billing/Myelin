from unittest.mock import MagicMock, patch

import pytest

from myelin import IPSFProvider, Myelin, OPSFProvider
from myelin.helpers.claim_examples import claim_example
from myelin.helpers.utils import ProviderDataError
from myelin.input import IrfPai, LineItem, Modules

MCE, MSDRG, IOCE, CMG = Modules.MCE, Modules.MSDRG, Modules.IOCE, Modules.CMG

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


@pytest.mark.parametrize(
    ("bill_type", "provider_type", "ccn", "rev_codes", "irf_pai", "expected"),
    [
        # 11x: provider type picks the inpatient pricer
        ("111", "00", "010007", [], False, [MCE, MSDRG, Modules.IPPS]),
        ("111", "03", "014000", [], False, [MCE, MSDRG, Modules.PSYCH]),
        ("111", "49", "01S307", [], False, [MCE, MSDRG, Modules.PSYCH]),
        ("111", "02", "012006", [], False, [MCE, MSDRG, Modules.LTCH]),
        ("111", "04", "013025", [], True, [MCE, CMG, Modules.IRF]),
        ("111", "04", "013025", [], False, [MCE, Modules.IRF]),
        # 11x: no inpatient routing for the provider type, so the CCN decides
        ("111", "07", "010001", [], False, [MCE, MSDRG, Modules.IPPS]),
        ("111", "", "014000", [], False, [MCE, MSDRG, Modules.PSYCH]),
        ("111", "", "01M307", [], False, [MCE, MSDRG, Modules.PSYCH]),
        ("111", "", "012006", [], False, [MCE, MSDRG, Modules.LTCH]),
        ("111", "50", "01T011", [], False, [MCE, Modules.IRF]),
        ("111", "50", "01T011", [], True, [MCE, CMG, Modules.IRF]),
        ("111", "", "01T011", [], False, [MCE, Modules.IRF]),
        ("111", "", "01R001", [], True, [MCE, CMG, Modules.IRF]),
        # 11x: CCN ranges match CMS (LTCH 2000-2299, psych 4000-4499)
        ("111", "", "012299", [], False, [MCE, MSDRG, Modules.LTCH]),
        ("111", "", "012300", [], False, [MCE, MSDRG, Modules.IPPS]),
        ("111", "", "014499", [], False, [MCE, MSDRG, Modules.PSYCH]),
        ("111", "", "014500", [], False, [MCE, MSDRG, Modules.IPPS]),
        # 11x: provider type wins over the CCN
        ("111", "00", "014000", [], False, [MCE, MSDRG, Modules.IPPS]),
        # 11x: no provider at all
        ("111", None, None, [], False, [MCE, MSDRG, Modules.IPPS]),
        ("0111", None, None, [], False, [MCE, MSDRG, Modules.IPPS]),
        # Outpatient bills from inpatient-only provider types stay outpatient
        ("131", "03", "014000", [], False, [IOCE, Modules.OPPS]),
        ("131", "02", "012006", [], False, [IOCE, Modules.OPPS]),
        ("131", "04", "013025", [], False, [IOCE, Modules.OPPS]),
        ("131", "00", "010007", [], False, [IOCE, Modules.OPPS]),
        # Revenue codes and other bill types don't depend on provider data
        ("111", "04", "013025", ["0024"], True, [CMG, Modules.IRF]),
        ("111", "00", "010007", ["0024"], False, [Modules.IRF]),
        ("211", "00", "010007", ["0022"], False, [Modules.SNF]),
        ("771", "03", "014000", [], False, [IOCE, Modules.FQHC]),
        ("721", "03", "014000", [], False, [IOCE, Modules.ESRD]),
        ("831", "03", "014000", [], False, [Modules.ASC]),
        ("221", "00", "010007", [], False, [IOCE, Modules.SNF]),
        ("321", "00", "010007", [], False, [Modules.HHA]),
        ("811", "35", "011558", [], False, [Modules.HOSPICE]),
        ("0822", None, None, [], False, [Modules.HOSPICE]),
        ("181", "51", "01U007", [], False, [Modules.SNF]),
        ("181", "51", "01U007", ["0022"], False, [Modules.SNF]),
    ],
)
def test_generate_auto_modules(
    stub_myelin, bill_type, provider_type, ccn, rev_codes, irf_pai, expected
):
    claim = _inpatient_auto_claim()
    claim.bill_type = bill_type
    claim.lines = [LineItem(revenue_code=rc) for rc in rev_codes]
    claim.irf_pai = IrfPai() if irf_pai else None
    provider = (
        None
        if provider_type is None
        else IPSFProvider(provider_type=provider_type, provider_ccn=ccn)
    )
    assert stub_myelin._generate_auto_modules(claim, provider) == expected


def _spy_generated(generated):
    orig = Myelin._generate_auto_modules

    def spy(self, claim, ipsf_provider):
        generated.append((ipsf_provider, orig(self, claim, ipsf_provider)))
        return generated[-1][1]

    return patch.object(Myelin, "_generate_auto_modules", spy)


def test_process_auto_passes_provider_to_generator(stub_myelin):
    def fake_ipsf(self, claim, engine, **kwargs):
        self.provider_ccn = "014000"
        self.provider_type = "03"

    claim = _inpatient_auto_claim()
    generated = []
    with patch.object(IPSFProvider, "from_claim", fake_ipsf), _spy_generated(generated):
        stub_myelin.process(claim)

    ((provider, modules),) = generated
    assert provider is not None
    assert provider.provider_type == "03"
    assert modules == [MCE, MSDRG, Modules.PSYCH]


def _missing_provider(self, claim, engine, **kwargs):
    raise ProviderDataError(
        code="P0002", description="Provider not found", explanation="not found"
    )


def test_process_auto_provider_lookup_failure_is_not_fatal(stub_myelin):
    claim = _inpatient_auto_claim()
    claim.bill_type = "771"
    generated = []
    with (
        patch.object(IPSFProvider, "from_claim", _missing_provider),
        _spy_generated(generated),
    ):
        result = stub_myelin.process(claim)

    ((provider, modules),) = generated
    assert provider is None
    assert modules == [IOCE, Modules.FQHC]
    assert result.error != "not found"


def test_process_auto_provider_lookup_failure_reported_when_needed(stub_myelin):
    claim = _inpatient_auto_claim()
    with patch.object(IPSFProvider, "from_claim", _missing_provider):
        result = stub_myelin.process(claim)
    assert result.error == "not found"
