"""Pay-and-fetch demo client: an agent paying an x402-gated endpoint over HTTP.

Registers the EVM and/or Solana payer wallets, then does a normal GET. The x402 transport
transparently catches the 402, signs a stablecoin payment on the chosen chain, retries, and
returns the data. Prints the on-chain settlement tx and its explorer link.

    uv run python client/pay_and_fetch.py --url http://127.0.0.1:8080/v1/company/AAPL --chain evm
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import sys

from dotenv import load_dotenv
from eth_account import Account
from x402 import x402Client
from x402.http.clients import x402HttpxClient
from x402.mechanisms.evm import EthAccountSigner
from x402.mechanisms.evm.exact.register import register_exact_evm_client
from x402.mechanisms.svm import KeypairSigner
from x402.mechanisms.svm.exact.register import register_exact_svm_client

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.config import explorer_url  # noqa: E402

load_dotenv()


def build_client(chain: str) -> x402Client:
    client = x402Client()
    if chain in ("evm", "both"):
        register_exact_evm_client(client, EthAccountSigner(Account.from_key(os.environ["EVM_PAYER_KEY"])))
    if chain in ("svm", "both"):
        register_exact_svm_client(client, KeypairSigner.from_base58(os.environ["SVM_PAYER_KEY"]))
    return client


def _settlement(resp) -> dict | None:
    raw = resp.headers.get("payment-response")
    if not raw:
        return None
    return json.loads(base64.b64decode(raw))


async def main(url: str, chain: str) -> int:
    client = build_client(chain)
    async with x402HttpxClient(client) as http:
        resp = await http.get(url)
    print(f"HTTP {resp.status_code}")
    print(resp.text[:800])
    settle = _settlement(resp)
    if settle:
        tx, network = settle.get("transaction"), settle.get("network")
        print(f"\nsettled on {network}")
        print(f"tx:       {tx}")
        print(f"explorer: {explorer_url(network, tx)}")
        return 0 if settle.get("success") and tx else 2
    print("\nno settlement header (request not paid)")
    return 2


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--url", required=True)
    p.add_argument("--chain", choices=["evm", "svm", "both"], default="evm")
    args = p.parse_args()
    raise SystemExit(asyncio.run(main(args.url, args.chain)))
