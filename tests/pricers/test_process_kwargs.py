"""Regression tests: pricer ``process()`` must accept caller kwargs (e.g. ``session``).

The built-in ``process_claim()`` ignores them (no TypeError; see
docs/bugs/01-process-claim-kwargs-typeerror.md), and a plugin that replaces
``process_claim()`` through the ``client_methods`` hook must still receive them.
"""

import types
from logging import getLogger

import pytest
from sqlalchemy.orm import Session

from myelin.input.claim import Claim
from myelin.pricers.ipf import IpfClient, IpfOutput
from myelin.pricers.ipps import IppsClient, IppsOutput
from myelin.pricers.ipsf import IPSFProvider
from myelin.pricers.ltch import LtchClient, LtchOutput


CLIENTS = [
    (IppsClient, IppsOutput),
    (IpfClient, IpfOutput),
    (LtchClient, LtchOutput),
]


class FakeDispatch:
    def __init__(self):
        self.requests = []

    def process(self, request):
        self.requests.append(request)
        return "response"


@pytest.mark.parametrize("client_cls, output_cls", CLIENTS)
def test_process_accepts_session_kwarg(monkeypatch, client_cls, output_cls):
    client = client_cls.__new__(client_cls)  # skip __init__ (no JVM needed)
    client.logger = getLogger("test")
    client.dispatch_obj = FakeDispatch()

    received_kwargs = {}

    def fake_create_input_claim(claim, ipsf_provider, drg_output, **kwargs):
        received_kwargs.update(kwargs)
        return "request", ipsf_provider

    client.create_input_claim = fake_create_input_claim
    monkeypatch.setattr(output_cls, "from_java", lambda self, response: None)

    claim = Claim(claimid="C1")
    provider = IPSFProvider()
    session = Session()

    output, returned_provider = client.process(claim, provider, session=session)

    assert isinstance(output, output_cls)
    assert output.claim_id == "C1"
    assert returned_provider is provider
    assert received_kwargs == {"session": session}
    assert client.dispatch_obj.requests == ["request"]


@pytest.mark.parametrize("client_cls, output_cls", CLIENTS)
def test_plugin_process_claim_receives_kwargs(monkeypatch, client_cls, output_cls):
    """A plugin's process_claim (bound via client_methods) gets the caller's session."""
    client = client_cls.__new__(client_cls)
    client.logger = getLogger("test")
    client.create_input_claim = lambda claim, provider, drg_output, **kw: (
        "request",
        provider,
    )
    monkeypatch.setattr(output_cls, "from_java", lambda self, response: None)

    seen = {}

    def plugin_process_claim(self, claim, pricing_request, session, **kwargs):
        seen["session"] = session
        seen["request"] = pricing_request
        return "response"

    client.process_claim = types.MethodType(plugin_process_claim, client)
    session = Session()

    output, _ = client.process(Claim(claimid="C2"), IPSFProvider(), session=session)

    assert seen == {"session": session, "request": "request"}
    assert output.return_code is None or output.return_code.code != "UNX"
