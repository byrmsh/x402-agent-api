"""Agent demo: an MCP client that discovers, pays for, and calls an x402-gated tool.

Connects to the MCP server (mounted at /mcp on the API), lists the tools, then lets x402MCPClient
drive the 402 -> sign -> retry handshake for a paid tool call. Prints the tool result and the
on-chain settlement tx.

    uv run python client/agent_demo.py --url http://127.0.0.1:8080/mcp --ticker AAPL

The MCP payment wrapper settles against the first-listed chain (Base Sepolia), so this pays on EVM.
The dual-chain story (EVM + Solana) is exercised over the REST surface by client/pay_and_fetch.py.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from typing import Any

from dotenv import load_dotenv
from eth_account import Account
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from x402 import x402Client

# The streamable-HTTP factory lives in client_async; the package-root create_x402_mcp_client is a
# different, SSE-only helper.
from x402.mcp.client_async import create_x402_mcp_client
from x402.mechanisms.evm import EthAccountSigner
from x402.mechanisms.evm.exact.register import register_exact_evm_client

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.config import explorer_url  # noqa: E402

load_dotenv()


class _SessionResult:
    """Re-exposes the SDK CallToolResult under the attribute names x402 reads.

    x402's convert_mcp_result does getattr(result, "_meta", {}); the SDK stores meta under .meta
    (the _meta is only the JSON wire alias), so the settlement response would be dropped without
    this re-exposure.
    """

    def __init__(self, raw: Any):
        self.content = raw.content
        self.isError = raw.isError
        self.structuredContent = raw.structuredContent
        self._meta = raw.meta or {}


class _SessionAdapter:
    """Bridges x402MCPClient (which calls call_tool(params_dict)) to a standard ClientSession.

    x402MCPClient calls self._mcp_client.call_tool({"name", "arguments", "_meta"}); ClientSession
    takes (name, arguments, *, meta=...). This unpacks the dict and forwards _meta -> meta so the
    x402/payment travels in the request's RequestParams.Meta.
    """

    def __init__(self, session: ClientSession):
        self._session = session

    async def call_tool(self, params: dict[str, Any], **_: Any) -> _SessionResult:
        raw = await self._session.call_tool(
            params["name"], params.get("arguments"), meta=params.get("_meta")
        )
        return _SessionResult(raw)

    async def list_tools(self):
        return await self._session.list_tools()


def _payment_client() -> x402Client:
    client = x402Client()
    register_exact_evm_client(client, EthAccountSigner(Account.from_key(os.environ["EVM_PAYER_KEY"])))
    return client


async def main(url: str, tool: str, arguments: dict[str, Any]) -> int:
    async with streamablehttp_client(url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            print("tools:", ", ".join(t.name for t in tools.tools))

            x402_mcp = create_x402_mcp_client(_SessionAdapter(session), _payment_client())
            result = await x402_mcp.call_tool(tool, arguments)

    text = result.content[0].text if result.content else ""
    print(f"\npayment_made: {result.payment_made}")
    print(f"result: {text[:600]}")

    settle = result.payment_response
    if settle is None:
        print("\nno settlement response (tool not paid)")
        return 2
    print(f"\nsettled on {settle.network}")
    print(f"success:  {settle.success}")
    print(f"tx:       {settle.transaction}")
    print(f"explorer: {explorer_url(settle.network, settle.transaction)}")
    return 0 if settle.success and settle.transaction else 2


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="http://127.0.0.1:8080/mcp")
    p.add_argument("--ticker", help="Call get_company for this ticker")
    p.add_argument("--search", help="Call search_companies with this query")
    args = p.parse_args()

    if args.search:
        tool, arguments = "search_companies", {"q": args.search}
    else:
        tool, arguments = "get_company", {"ticker": args.ticker or "AAPL"}

    raise SystemExit(asyncio.run(main(args.url, tool, arguments)))
