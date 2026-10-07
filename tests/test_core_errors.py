"""Regression tests for error reporting in ``Myelin.process()``: a failing module
doesn't stop the others, errors name their module and code, and errors from
several modules are all kept. See docs/bugs/08-core-error-reporting.md.
"""

from unittest.mock import MagicMock

import pytest

from myelin import IPSFProvider
from myelin.helpers.claim_examples import claim_example
from myelin.helpers.utils import JavaRuntimeError
from myelin.input import Modules
from myelin.msdrg import MsdrgOutput
from myelin.pricers.ipps import IppsOutput


def _claim(*modules, bill_type="111"):
    claim = claim_example()
    claim.bill_type = bill_type
    claim.modules = list(modules)
    return claim


def _stub_inpatient_clients(m):
    m.mce_client = MagicMock()
    m.drg_client = MagicMock()
    m.drg_client.process.return_value = MsdrgOutput()
    m.ipps_client = MagicMock()
    m.ipps_client.process.return_value = (IppsOutput(), IPSFProvider())


def test_failed_module_does_not_stop_later_modules(stub_myelin):
    _stub_inpatient_clients(stub_myelin)
    stub_myelin.mce_client.process.side_effect = JavaRuntimeError(
        "JERR_INVALID_DATE", "Invalid date format", "Invalid patient status"
    )
    result = stub_myelin.process(_claim(Modules.MCE, Modules.MSDRG, Modules.IPPS))

    assert result.mce is None
    assert result.msdrg is stub_myelin.drg_client.process.return_value
    assert result.ipps is not None
    assert result.error == (
        "[MCE] JERR_INVALID_DATE: Invalid date format - Invalid patient status"
    )


def test_unexpected_module_error_is_logged_and_others_run(stub_myelin):
    _stub_inpatient_clients(stub_myelin)
    stub_myelin.drg_client.process.side_effect = KeyError("dx")
    result = stub_myelin.process(_claim(Modules.MCE, Modules.MSDRG, Modules.IPPS))

    assert result.error == "[MSDRG] UNX: Unexpected error"
    stub_myelin.logger.exception.assert_called_once()
    # IPPS still runs, without a DRG; the pricer reports that in its return code
    assert result.ipps is not None
    assert stub_myelin.ipps_client.process.call_args.args[2] is None


def test_errors_from_several_modules_are_all_kept(stub_myelin):
    result = stub_myelin.process(_claim(Modules.MCE, Modules.MSDRG))
    assert result.error == (
        "[MCE] client not initialized; [MSDRG] client not initialized"
    )


@pytest.mark.parametrize("modules", [[Modules.AUTO], [Modules.MCE]])
def test_non_payment_bill_is_rejected_in_every_mode(stub_myelin, modules):
    result = stub_myelin.process(_claim(*modules, bill_type="110"))
    assert result.error == "Bill type 110 is a non payment bill"
