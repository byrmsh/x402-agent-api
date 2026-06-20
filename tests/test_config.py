"""Explorer-URL routing per chain."""

from __future__ import annotations

from app import config


def test_evm_explorer_points_at_base_sepolia():
    url = config.evm_explorer("0xabc")
    assert url == "https://sepolia.basescan.org/tx/0xabc"


def test_svm_explorer_includes_devnet_cluster():
    # Without ?cluster=devnet the explorer silently shows mainnet, which would be wrong.
    url = config.svm_explorer("3beB")
    assert url == "https://explorer.solana.com/tx/3beB?cluster=devnet"


def test_explorer_url_routes_by_network_prefix():
    assert config.explorer_url(config.EVM_NETWORK, "0xabc").startswith("https://sepolia.basescan.org")
    assert "cluster=devnet" in config.explorer_url(config.SVM_NETWORK, "3beB")


def test_explorer_url_unknown_network_falls_back_to_tx():
    # An unrecognized network must not crash a caller (e.g. /v1/receipts on a stale row).
    assert config.explorer_url("eip155:1", "0xdeadbeef") == "0xdeadbeef"
