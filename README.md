# x402 agent-payable API

A FastAPI service that sells data to autonomous agents over the [x402](https://x402.org) protocol
(HTTP 402 Payment Required), settled in stablecoins on two chains, exposed as both a REST API and an
MCP server from one deployment. Testnet only: every payment here is Base Sepolia or Solana devnet
USDC, zero real money.

An agent requests a resource, gets a 402 with the price and accepted chains, signs a stablecoin
payment, and retries. A facilitator verifies and settles the payment on-chain and pays the gas, so
the agent spends only USDC. Each settlement is recorded as a public, on-chain-linked receipt.

## Live

Deployed on Cloud Run: **https://upwork-x402-agent-api-874666638466.europe-west1.run.app**

```bash
# what is sold, on which chains, at what price (free)
curl -s https://upwork-x402-agent-api-874666638466.europe-west1.run.app/v1/catalog

# a paid route with no payment returns a 402 challenge listing both chains
curl -s https://upwork-x402-agent-api-874666638466.europe-west1.run.app/v1/company/AAPL

# the on-chain audit trail of payments the service has settled
curl -s https://upwork-x402-agent-api-874666638466.europe-west1.run.app/v1/receipts
```

## Proven live (real testnet settlements)

Every settlement below was made by a client paying the deployed service above, and stays queryable
at `/v1/receipts`.

| Surface | Chain | Transaction |
| --- | --- | --- |
| REST `GET /v1/company/AMZN` | Base Sepolia | [`0x7c6320ff`](https://sepolia.basescan.org/tx/0x7c6320ffb0cd040e78d181967dfe441ba4d5f19ca2b95080dd5d980184bae718) |
| REST `GET /v1/company/JPM` | Solana devnet (gasless) | [`5bvGMtwQ`](https://explorer.solana.com/tx/5bvGMtwQGwfFvtE6QPYwszciRgsXZw2wV2NFcYAGto5Wu9B4bjP4Ph3r6DcBNb5dyoefcPkNLoCfhjZWpWo9Bv9p?cluster=devnet) |
| REST `GET /v1/search?q=bancorp` | Base Sepolia | [`0xd088a917`](https://sepolia.basescan.org/tx/0xd088a9176dafe700641f52f2db0b855a61217c129f4afbf971ae6d93868d8932) |
| MCP tool `get_company` | Base Sepolia | [`0xf5e4b0b8`](https://sepolia.basescan.org/tx/0xf5e4b0b8f104332090b32292ed48d7c8f49d1952b75118ba47da5e02d4b6a6d1) |

On Solana the facilitator is the transaction fee payer, so the paying agent needs no SOL at all.

## Architecture

One FastAPI app, two payment-gated surfaces backed by the same x402 rails:

- **REST** (`app/routes.py`): `PaymentMiddlewareASGI` gates the paid routes. A 402 lists one payment
  option per configured chain, so one endpoint serves both chains.
- **MCP** (`app/mcp_server.py`): a `FastMCP` server mounted at `/mcp` over streamable HTTP, each tool
  wrapped by `x402.mcp.create_payment_wrapper`. An agent runtime discovers, pays for, and calls the
  tools natively.
- **Facilitator**: the public keyless `https://x402.org/facilitator` verifies and settles on both
  testnets. Point `FACILITATOR_URL` at your own to self-host.
- **Data** (`app/data.py`): the SEC EDGAR ticker to CIK reference set (about 10k issuers), in Postgres
  (Neon in production, docker locally). Swappable: a client's own dataset drops in behind two
  functions. With no database configured the service still runs on a small bundled sample.
- **Receipts** (`app/receipts.py`): an `on_after_settle` hook writes every settlement to Postgres;
  `GET /v1/receipts` serves the on-chain audit trail.

## Endpoints and tools

| Path | Price | Notes |
| --- | --- | --- |
| `GET /health` | free | liveness |
| `GET /v1/catalog` | free | what is sold, prices, chains |
| `GET /v1/receipts` | free | settled-payment audit trail |
| `GET /v1/company/{ticker}` | $0.001 | one company reference record |
| `GET /v1/search?q=` | $0.01 | search the dataset |
| MCP `get_company(ticker)` | $0.001 | same data, over MCP at `/mcp` |
| MCP `search_companies(q)` | $0.01 | same data, over MCP at `/mcp` |

## Quickstart

Requires [uv](https://docs.astral.sh/uv/) and Docker.

```bash
uv sync

# 1. Generate throwaway testnet wallets (writes .env)
uv run python scripts/gen_wallets.py

# 2. Fund them at https://faucet.circle.com (USDC, no SOL needed):
#    - Base Sepolia USDC -> EVM payer (EVM_PAYER_ADDRESS)
#    - Solana devnet USDC -> SVM payer (SVM_PAYER_ADDRESS)
#    - Solana devnet USDC -> SVM receiver (SVM_PAY_TO). This one-time drip creates the receiver's
#      token account, which Solana settlement requires (the facilitator pays fees but does not
#      create the account). EVM needs no equivalent step.

# 3. Start Postgres and seed the dataset
docker compose up -d db
echo "DATABASE_URL=postgresql://postgres:x402@127.0.0.1:5433/x402" >> .env
uv run python scripts/seed_edgar.py

# 4. Run the service (REST + MCP)
uv run uvicorn app.main:app --host 127.0.0.1 --port 8080
```

Then, from another shell, let a client pay and fetch:

```bash
# REST, paying on Base Sepolia
uv run python client/pay_and_fetch.py --url http://127.0.0.1:8080/v1/company/AAPL --chain evm

# REST, paying on Solana devnet (gasless)
uv run python client/pay_and_fetch.py --url http://127.0.0.1:8080/v1/company/MSFT --chain svm

# MCP, paying for a tool call
uv run python client/agent_demo.py --url http://127.0.0.1:8080/mcp --ticker AAPL

# Inspect the receipts
curl -s http://127.0.0.1:8080/v1/receipts
```

## Tests

```bash
uv run pytest          # unit + Postgres integration (the DB tests skip if no DATABASE_URL)
```

## Deploy

Live on Cloud Run. The image runs `uvicorn app.main:app --proxy-headers` so the 402 challenge's
resource URL reflects the public https origin, and honors Cloud Run's `$PORT`.

```bash
docker build -t x402-agent-api .
```

In production set `DATABASE_URL` to a Neon connection string and `EVM_PAY_TO` / `SVM_PAY_TO` to your
receiving wallets (the receiving addresses are public; no payer keys live server-side). `docker
compose up` runs the whole stack (API plus Postgres) locally.

## Notes

- Prices are USD strings (`$0.001`); the SDK converts them to 6-decimal USDC atomic units.
- The receiving wallets the API is paid into are public addresses; no private keys live in the
  service. Payer keys are used only by the demo clients.
- Built against `x402==2.13.1` with the bundled `mcp==1.28.0`. See `docs/installed-truth.md` for the
  verified API contract, including where the MCP docstrings diverge from the installed code.
