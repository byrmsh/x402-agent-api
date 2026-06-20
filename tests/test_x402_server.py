"""Route declaration, per-chain accepts, and receipt-resource extraction."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app import x402_server
from app.config import EVM_NETWORK, SVM_NETWORK


def test_accepts_one_option_per_configured_chain(monkeypatch):
    monkeypatch.setattr(x402_server.settings, "evm_pay_to", "0xReceiver")
    monkeypatch.setattr(x402_server.settings, "svm_pay_to", "SolReceiver")
    options = x402_server._accepts("$0.01")
    networks = {o.network for o in options}
    assert networks == {EVM_NETWORK, SVM_NETWORK}


def test_accepts_skips_chain_without_wallet(monkeypatch):
    monkeypatch.setattr(x402_server.settings, "evm_pay_to", "0xReceiver")
    monkeypatch.setattr(x402_server.settings, "svm_pay_to", "")
    options = x402_server._accepts("$0.01")
    assert [o.network for o in options] == [EVM_NETWORK]


def test_accepts_with_no_wallet_raises(monkeypatch):
    monkeypatch.setattr(x402_server.settings, "evm_pay_to", "")
    monkeypatch.setattr(x402_server.settings, "svm_pay_to", "")
    with pytest.raises(RuntimeError):
        x402_server._accepts("$0.01")


def test_build_routes_declares_both_paid_routes(monkeypatch):
    monkeypatch.setattr(x402_server.settings, "evm_pay_to", "0xReceiver")
    monkeypatch.setattr(x402_server.settings, "svm_pay_to", "SolReceiver")
    routes = x402_server.build_routes()
    assert set(routes) == {"GET /v1/company/*", "GET /v1/search"}


def test_resource_reads_request_path():
    ctx = SimpleNamespace(transport_context=SimpleNamespace(request=SimpleNamespace(path="/v1/company/AAPL")))
    assert x402_server._resource(ctx) == "/v1/company/AAPL"


def test_resource_is_none_without_http_transport():
    # MCP transport has no HTTP request; the hook must not crash.
    assert x402_server._resource(SimpleNamespace(transport_context=None)) is None
    assert x402_server._resource(SimpleNamespace()) is None
