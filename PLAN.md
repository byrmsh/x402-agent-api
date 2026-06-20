# x402-agent-api — Build Plan

Portfolio POC (testnet-only) + optional bid asset for the "Senior Python/FastAPI x402/MCP take-over" job.
Deliberately mirrors that job's stack: FastAPI + Postgres + MCP + multi-chain x402 (EVM Base Sepolia + Solana devnet).

## 1. What it is

An **agent-payable structured-data API**: an AI agent pays a stablecoin micropayment (USDC) per request, on
either Base Sepolia (EVM) or Solana devnet, and gets back structured data. Two faces on one service:

- An **x402-gated REST API** serving a real structured dataset from Postgres.
- An **MCP server** exposing the same data as a paid tool, so a Claude-style agent autonomously pays-and-fetches.

Story for the blog: *multi-chain x402 in pure Python is real as of mid-2026; here is a working EVM+Solana
resource server an AI agent pays over MCP*, and it corrects the still-circulating "Python/Solana x402 is
TypeScript-only / in development" myth with x402 2.13.1 source as proof.

## 2. Locked technical decisions (from fact-checked research, x402 2.13.1, 2026-06-19)

- Package: official `x402` (x402-foundation/x402, NOT coinbase/x402 which is frozen). Pin `x402==2.13.1`,
  install `x402[fastapi,httpx,evm,svm,mcp]`. Alpha + weekly releases → pin exact, re-verify imports after any bump.
- Python **3.12** (pin via `uv python pin 3.12`); 3.14 (the box default) risks missing wheels for solders/web3/mcp.
- Server: `x402ResourceServer(HTTPFacilitatorClient(FacilitatorConfig(url="https://x402.org/facilitator")))`,
  `server.register("eip155:84532", ExactEvmServerScheme())` + `server.register("solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1", ExactSvmServerScheme())`,
  attach `PaymentMiddlewareASGI`. Routes are a dict keyed `"GET /path"` → `RouteConfig(accepts=[PaymentOption(EVM), PaymentOption(SVM)])`.
- Facilitator: free hosted `https://x402.org/facilitator`, no keys, gasless on both testnets. Fallback: in-process
  self-hosted facilitator (test_svm.py pattern) if the public one throttles or its devnet feePayer runs dry.
- MCP: SDK-bundled `mcp.server.fastmcp.FastMCP` (mcp 1.28.0), **async `create_payment_wrapper` decorator**
  (do NOT use `wrap_fastmcp_tool_sync` — absent in 2.13.1; the `simple.py` example is broken on clean install).
  Transport **streamable-HTTP** at `/mcp` (proven in `test_mcp_evm.py` with real Base Sepolia settlement); SSE is legacy.
- Persistence: settlement happens AFTER the route returns; persist receipts via `server.on_after_settle` hook,
  reading `SettleResponse.transaction` (the on-chain id field for BOTH chains; there is no `.signature`).
- Deploy: **Google Cloud Run** (only host that is free-at-idle: scale-to-zero, 2M req/mo). Single container,
  reuse the proven `pdf-redaction-api` Dockerfile shape (python:3.12-slim + uv, EXPOSE 8080, uvicorn 0.0.0.0:8080).

### Chain constants (verified)
- Base Sepolia: network `eip155:84532`, chain id 84532, USDC `0x036CbD53842c5426634e7929541eC2318f3dCF7e`,
  EIP-712 domain name `USDC` version `2`, 6 decimals. EIP-3009 gasless → payer needs USDC only, no ETH.
  Request header is `PAYMENT-SIGNATURE` (V2), not `X-PAYMENT` (V1 legacy).
- Solana devnet: network `solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1`, USDC mint
  `4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU`, 6 decimals. SPL TransferChecked (NOT EIP-3009).
  Gasless via facilitator feePayer `CKPKJWNdJEqa81x7CkZ14BVPiY6y16Sxs7owznqtWYp5` → payer needs USDC only, no SOL.
- Explorer links: `https://sepolia.basescan.org/tx/<0xhash>` ; `https://explorer.solana.com/tx/<sig>?cluster=devnet`
  (the `?cluster=devnet` is mandatory or it silently shows mainnet).

## 3. The dataset (what agents pay for)

Real, public-domain, queryable, no external API key, so the demo is not a "weather: sunny" toy. Default choice:
**OpenFlights airports** (~7k rows: IATA/ICAO, name, city, country, lat/lon, timezone) seeded into Postgres.
Swappable by design ("your data/algorithm drops in"). Endpoints:

- `GET /health` — free, liveness.
- `GET /catalog` — free, lists datasets + pricing + accepted chains (the discovery surface).
- `GET /airports/{iata}` — paid $0.001, one enriched record.
- `GET /search?country=&q=` — paid $0.01, multi-record query.

## 4. Components / layout

```
x402-agent-api/
  pyproject.toml            # uv, py3.12, x402==2.13.1 pinned
  app/
    main.py                 # FastAPI app: x402 middleware + mounted MCP app, one ASGI service
    config.py               # env: addresses, facilitator URL, DB URL, networks
    x402_server.py          # build x402ResourceServer, register EVM+SVM, on_after_settle → receipts
    routes.py               # /health /catalog /airports/{iata} /search
    mcp_server.py           # FastMCP, paid get_airport/search tools (dual-chain) + free ping
    db.py                   # asyncpg/SQLAlchemy pool
    models.py               # airports, settlements (receipts) tables
    data/seed_airports.py   # load OpenFlights into Postgres
  client/
    pay_and_fetch.py        # x402HttpxClient demo (EVM + SVM auto-pay)
    agent_demo.py           # x402MCPClient: agent autonomously pays a tool, prints tx + explorer link
  scripts/
    gen_wallets.py          # 4 keypairs: EVM payer, SVM payer, EVM receiver, SVM receiver
    fund.py                 # headless funding (cdp-sdk) with Circle-faucet fallback
    init_solana_ata.py      # PRE-CREATE receiver USDC ATA (load-bearing) + verify payer ATA
  tests/                    # unit + local-facilitator integration + live-marked e2e
  Dockerfile                # python:3.12-slim + uv, 8080
  docker-compose.yml        # app + postgres for local e2e
  README.md                 # live URL, 2 explorer tx links, curl + MCP how-to-test
```

## 5. Wallets & funding (testnet, free)

- 4 keypairs generated locally (`gen_wallets.py`), secrets in `.env` (gitignored), addresses in `.env.example`.
- EVM payer: testnet USDC only (gasless). SVM payer: devnet USDC only (gasless), ATA auto-created by Circle faucet.
- **SVM receiver: pre-create USDC ATA** via `spl-token create-account <mint> --owner <receiver> -u devnet`
  (`init_solana_ata.py`) — no faucet creates it; missing receiver ATA = silent settle failure. Load-bearing.
- Headless funding via `cdp-sdk` `request_faucet`; if a free CDP account is gated, fall back to Circle UI faucet
  (`faucet.circle.com`, 20 USDC/2h) — one human/playwright click. `solana airdrop` only as last resort (rate-limited).

## 6. Phased build (de-risk in order; Solana settlement is the real unknown, so prove it early)

- **P0 Scaffold + dependency reality check.** `uv init`, pin 3.12, `uv add 'x402[fastapi,httpx,evm,svm,mcp]'`,
  resolve one lockfile, **`docker build` against python:3.12-slim now** to confirm solders/solana ship manylinux
  wheels (no Rust toolchain). Read installed `site-packages/x402` to pin real symbols: `create_payment_wrapper`,
  `SettleResponse.transaction`, `on_after_settle` ctx shape, schemas. Fix the plan to the installed truth.
- **P1 EVM happy path.** FastAPI server + httpx client → real Base Sepolia settlement, capture `0x` tx, open on
  Basescan. Most battle-tested path; proves the whole 402→sign→verify→settle loop.
- **P2 Solana.** `init_solana_ata.py` (receiver ATA), fund SVM payer, real devnet settlement, capture base58 sig,
  open on Solana Explorer `?cluster=devnet`. First run against in-process facilitator (test_svm pattern), then the
  public facilitator. This is the load-bearing verification.
- **P3 Postgres.** Seed airports; `settlements` receipts table written from `on_after_settle` (tx, chain, amount,
  payer, resource, ts). Real Postgres (docker), no mocked DB.
- **P4 MCP.** `create_payment_wrapper` async tools (paid `get_airport`/`search` dual-chain + free `ping`),
  streamable-HTTP at `/mcp`; `agent_demo.py` (x402MCPClient, `auto_payment=True`, `on_payment_requested` spend gate)
  autonomously pays and prints the explorer link. Dual-chain MCP is our code (no official example does it) → verify.
- **P5 Single-service compose.** Mount MCP `streamable_http_app` (json_response + stateless_http) into the FastAPI
  app sharing one resource server; `docker compose up`; full local e2e on both chains + MCP.
- **P6 Tests.** unit (payload, gating, receipt logic, explorer URLs) + local-facilitator integration (402→pay→200,
  no network) + `@pytest.mark.live` e2e (real both-chain settlement, asserts real tx ids → feeds the blog links).
- **P7 Deploy.** Cloud Run single container (`gcloud run deploy --source .`), `--timeout` set, smoke-test live URL,
  confirm an MCP session survives. **Checkpoint with Bayram for gcloud auth + before anything goes live.**
- **P8 Writeup.** README + bayram.sh blog post. **Go-public checkpoint** before creating the public repo / pushing /
  publishing.

## 7. Testing strategy

- Real Postgres in docker for any DB-touching test (global rule: no mocked-DB tests).
- Local in-process facilitator for fast, network-free integration tests of the payment loop.
- `live` pytest marker for the real on-chain settlements (opt-in; these generate the blog's linkable txs).
- A `make e2e` that brings up compose, funds, runs both-chain client + MCP agent, asserts real tx ids.

## 8. Risks → mitigations (from the adversarial research critic)

1. Solana receiver ATA missing → `init_solana_ata.py` pre-creates it. (load-bearing)
2. `wrap_fastmcp_tool_sync` absent in 2.13.1 → async `create_payment_wrapper`; verify against installed source in P0.
3. `SettleResponse` id field is `.transaction` both chains → confirm in installed schemas (P0).
4. Receipts need `on_after_settle` (route runs before settle) → pin ctx shape in P0 before designing the table.
5. solders/solana wheels on slim image → `docker build` in P0, add build deps only if forced.
6. CDP free-account faucet gating → Circle UI faucet fallback (one click).
7. Cloud Run request timeout vs long MCP session → set `--timeout`, `stateless_http=True`; or demo MCP from a local
   client against the live API if a held connection is flaky.
8. Public facilitator throttling / devnet feePayer dry → in-process facilitator fallback; note in blog.
9. Python 3.14 wheel gaps → pin 3.12.

## 9. Honesty / positioning (per CLAUDE.md + memory)

- Frame as **testnet**, **"built and deployed"**, never paid client work, never mainnet/production, never AI/ML.
- Postgres requirement met by the real data layer + receipts, distinct from the existing Supabase migration blog post.
- No em-dashes, plain tone, run the blog/README through `avoid-ai-writing` before publish.

## 10. Deliverables

- Public repo `byrmsh/x402-agent-api` (license to match: MIT), README leading with the live URL + two real testnet
  explorer tx links + a one-line how-to-test (curl + MCP).
- bayram.sh blog post.
- Live Cloud Run URL.
