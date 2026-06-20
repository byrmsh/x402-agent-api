"""Configuration and verified chain constants for the x402 agent-payable API.

Testnet only. Every chain constant here was verified against installed x402 2.13.1
(see docs/installed-truth.md). Mints/addresses are Base Sepolia + Solana devnet.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict

# --- Networks (CAIP-2) ---
EVM_NETWORK = "eip155:84532"  # Base Sepolia
SVM_NETWORK = "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1"  # Solana devnet

# --- Assets (6-decimal testnet USDC) ---
EVM_USDC = "0x036CbD53842c5426634e7929541eC2318f3dCF7e"  # Base Sepolia USDC
SVM_USDC = "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU"  # Solana devnet USDC

# --- Explorers (the ?cluster=devnet is mandatory for Solana or it shows mainnet) ---
def evm_explorer(tx: str) -> str:
    return f"https://sepolia.basescan.org/tx/{tx}"


def svm_explorer(sig: str) -> str:
    return f"https://explorer.solana.com/tx/{sig}?cluster=devnet"


def explorer_url(network: str, tx: str) -> str:
    return svm_explorer(tx) if network.startswith("solana:") else evm_explorer(tx)


class Settings(BaseSettings):
    """Runtime config. Receiving (pay_to) addresses are public; no private keys here."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Receiving wallets the API is paid into (one per chain).
    evm_pay_to: str = ""
    svm_pay_to: str = ""

    # Facilitator that verifies + settles on-chain. Public default is keyless on both testnets.
    # Point at our own URL to run a self-hosted facilitator we control.
    facilitator_url: str = "https://x402.org/facilitator"

    # Postgres (Neon serverless in prod, local docker in dev). Empty => data/receipts disabled.
    database_url: str = ""

    # Prices (USD strings; the SDK resolves to 6-decimal USDC atomic units).
    price_lookup: str = "$0.001"
    price_search: str = "$0.01"

    # Max records a paid search returns (the x402 middleware buffers the full body in memory).
    search_limit: int = 25

    port: int = 8080


settings = Settings()
