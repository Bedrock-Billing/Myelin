"""Regression tests for pricer ``process()`` error paths: every pricer turns
provider and pricer errors into a return code, keeps the provider it was given,
and logs unexpected errors with a traceback. See docs/bugs/07-pricer-error-path-inconsistencies.md.
"""

import logging
from unittest.mock import MagicMock

import pytest

from myelin.helpers.utils import (
    JavaRuntimeError,
    PricerRuntimeError,
    ProviderDataError,
)
from myelin.input.claim import Claim
from myelin.pricers.esrd import EsrdClient, EsrdOutput
from myelin.pricers.fqhc import FqhcClient, FqhcOutput
from myelin.pricers.hha import HhaClient, HhaOutput
from myelin.pricers.hospice import HospiceClient, HospiceOutput
from myelin.pricers.ipf import IpfClient, IpfOutput
from myelin.pricers.ipps import IppsClient, IppsOutput
from myelin.pricers.ipsf import IPSFProvider
from myelin.pricers.irf import IrfClient, IrfOutput
from myelin.pricers.ltch import LtchClient, LtchOutput
from myelin.pricers.opps import OppsClient, OppsOutput
from myelin.pricers.opsf import OPSFProvider
from myelin.pricers.snf import SnfClient, SnfOutput

PROVIDER_PRICERS = [
    (IppsClient, IPSFProvider),
    (IpfClient, IPSFProvider),
    (LtchClient, IPSFProvider),
    (IrfClient, IPSFProvider),
    (SnfClient, IPSFProvider),
    (HhaClient, IPSFProvider),
    (EsrdClient, OPSFProvider),
    (OppsClient, OPSFProvider),
]

OUTPUT_CLASSES = {
    IppsClient: IppsOutput,
    IpfClient: IpfOutput,
    LtchClient: LtchOutput,
    IrfClient: IrfOutput,
    SnfClient: SnfOutput,
    HhaClient: HhaOutput,
    EsrdClient: EsrdOutput,
    OppsClient: OppsOutput,
    HospiceClient: HospiceOutput,
    FqhcClient: FqhcOutput,
}

ERRORS = [
    ProviderDataError("P0001", "No provider on claim", "provider explanation"),
    PricerRuntimeError("X01", "Pricer failure", "pricer explanation"),
]


def _client(client_cls, error):
    client = client_cls.__new__(client_cls)  # skip __init__ (no JVM needed)
    client.logger = logging.getLogger("test.pricer")
    # OPPS builds its Java request and provider data itself
    client.db = object()
    client.opps_price_request_class = MagicMock()
    client.outpatient_prov_data_class = MagicMock()
    client.java_integer_class = MagicMock()
    client.java_big_decimal_class = MagicMock()
    client.py_date_to_java_date = MagicMock()

    def fail(*args, **kwargs):
        raise error

    client.create_input_claim = fail
    return client


@pytest.mark.parametrize("error", ERRORS, ids=lambda e: type(e).__name__)
@pytest.mark.parametrize(
    "client_cls, provider_cls", PROVIDER_PRICERS, ids=lambda c: c.__name__
)
def test_handled_errors_keep_provider(client_cls, provider_cls, error):
    provider = provider_cls(provider_ccn="010001")
    output, returned = _client(client_cls, error).process(Claim(claimid="C1"), provider)
    assert output.claim_id == "C1"
    assert output.return_code.code == error.code
    assert output.return_code.explanation == error.explanation
    assert returned is provider


@pytest.mark.parametrize(
    "client_cls, provider_cls", PROVIDER_PRICERS, ids=lambda c: c.__name__
)
def test_unexpected_error_keeps_provider_and_logs_traceback(
    client_cls, provider_cls, caplog
):
    provider = provider_cls(provider_ccn="010001")
    with caplog.at_level(logging.ERROR, logger="test.pricer"):
        output, returned = _client(client_cls, KeyError("drg")).process(
            Claim(claimid="C1"), provider
        )
    assert output.return_code.code == "UNX"
    assert returned is provider
    (record,) = caplog.records
    assert record.exc_info is not None
    assert "C1" in record.getMessage()


@pytest.mark.parametrize("error", ERRORS, ids=lambda e: type(e).__name__)
@pytest.mark.parametrize("client_cls", [HospiceClient, FqhcClient])
def test_providerless_pricers_handle_errors(client_cls, error):
    args = () if client_cls is HospiceClient else (None,)
    output = _client(client_cls, error).process(Claim(claimid="C1"), *args)
    assert output.return_code.code == error.code


@pytest.mark.parametrize("client_cls", [HospiceClient, FqhcClient])
def test_providerless_pricers_return_unx(client_cls, caplog):
    # Hospice used to fall through to the Java call with no request and raise
    args = () if client_cls is HospiceClient else (None,)
    with caplog.at_level(logging.ERROR, logger="test.pricer"):
        output = _client(client_cls, KeyError("x")).process(Claim(claimid="C1"), *args)
    assert output.return_code.code == "UNX"
    assert caplog.records[0].exc_info is not None


def _client_failing_java_call(client_cls, error):
    """Client whose input builds fine but whose Java pricing call fails."""
    client = _client(client_cls, error)

    def create(claim, *args, **kwargs):
        if client_cls in (OppsClient, HospiceClient, FqhcClient):
            return MagicMock()
        return MagicMock(), args[0]

    def fail(*args, **kwargs):
        raise error

    client.create_input_claim = create
    client.process_claim = fail
    client.dispatch_obj = MagicMock()
    client.dispatch_obj.process.side_effect = error
    return client


def _process(client, client_cls, provider):
    if client_cls is HospiceClient:
        return client.process(Claim(claimid="C1"))
    if client_cls is FqhcClient:
        return client.process(Claim(claimid="C1"), None)
    return client.process(Claim(claimid="C1"), provider)


ALL_PRICERS = PROVIDER_PRICERS + [
    (HospiceClient, IPSFProvider),
    (FqhcClient, IPSFProvider),
]


@pytest.mark.parametrize(
    "client_cls, provider_cls", ALL_PRICERS, ids=lambda c: c.__name__
)
def test_java_call_failure_returns_output(client_cls, provider_cls):
    # Used to escape the pricer as JavaRuntimeError and abort the remaining modules
    error = JavaRuntimeError("JERR", "Java failure", "Java explanation")
    provider = provider_cls(provider_ccn="010001")
    result = _process(
        _client_failing_java_call(client_cls, error), client_cls, provider
    )
    output = result[0] if isinstance(result, tuple) else result
    assert output.claim_id == "C1"
    assert output.return_code.code == "JERR"
    if isinstance(result, tuple):
        assert result[1] is provider


@pytest.mark.parametrize(
    "client_cls, provider_cls", ALL_PRICERS, ids=lambda c: c.__name__
)
def test_from_java_failure_returns_unx(client_cls, provider_cls, caplog, monkeypatch):
    client = _client_failing_java_call(client_cls, KeyError("unused"))
    client.process_claim = lambda *a, **k: MagicMock()
    client.dispatch_obj.process.side_effect = None
    output_cls = OUTPUT_CLASSES[client_cls]

    def broken_from_java(self, response):
        raise AttributeError("getTotalPayment")

    monkeypatch.setattr(output_cls, "from_java", broken_from_java)
    with caplog.at_level(logging.ERROR, logger="test.pricer"):
        result = _process(client, client_cls, provider_cls(provider_ccn="010001"))
    output = result[0] if isinstance(result, tuple) else result
    assert isinstance(output, output_cls)
    assert output.return_code.code == "UNX"
    assert "AttributeError" in output.return_code.explanation
    assert caplog.records[-1].exc_info is not None
