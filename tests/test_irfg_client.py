"""Tests for diagnosis codes sent to the CMG grouper.
See docs/bugs/04-irfg-secondary-dx-skipped.md.
"""

from unittest.mock import MagicMock

from myelin.helpers.claim_examples import claim_example
from myelin.input import DiagnosisCode, IrfPai
from myelin.irfg.irfg_client import MAX_DX_CODES, IrfgClient


def make_client(added: list[str]) -> IrfgClient:
    client = IrfgClient.__new__(IrfgClient)  # skip __init__ (no JVM needed)
    claim_obj = MagicMock()
    claim_obj.addCode.side_effect = added.append
    client.irf_claim_class = lambda: claim_obj
    client.dx_code_class = lambda s: s.rstrip("^")
    client.py_date_to_java_date = lambda d: d
    client.create_assessments = lambda pai: None
    return client


def make_claim(principal: str | None, secondaries: list[str | None]):
    claim = claim_example()
    claim.irf_pai = IrfPai()
    claim.principal_dx = DiagnosisCode(code=principal) if principal else None
    claim.secondary_dxs = [DiagnosisCode(code=x) for x in secondaries]
    return claim


def test_all_secondary_codes_sent_in_order():
    added: list[str] = []
    make_client(added).create_claim_input(
        make_claim("I63.50", ["E11.9", "I10", "N17.9"])
    )
    assert added == ["I63.50", "E11.9", "I10", "N17.9"]


def test_secondary_codes_sent_without_principal():
    added: list[str] = []
    make_client(added).create_claim_input(make_claim(None, ["E11.9", "I10"]))
    assert added == ["E11.9", "I10"]


def test_blank_secondary_codes_skipped():
    added: list[str] = []
    claim = make_claim("I63.50", ["E11.9", "", "  ", "N17.9"])
    claim.secondary_dxs.insert(1, DiagnosisCode.model_construct(code=None))
    make_client(added).create_claim_input(claim)
    assert added == ["I63.50", "E11.9", "N17.9"]


def test_codes_capped_including_principal():
    added: list[str] = []
    secondaries = [f"Z{i:02d}.0" for i in range(30)]
    make_client(added).create_claim_input(make_claim("I63.50", secondaries))
    assert len(added) == MAX_DX_CODES
    assert added[0] == "I63.50"
    assert added[1:] == secondaries[: MAX_DX_CODES - 1]
