from unittest.mock import MagicMock, patch

import pytest

from myelin import IPSFProvider, Myelin, OPSFProvider

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
