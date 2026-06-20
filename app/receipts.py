"""Settlement receipts: the on-chain audit trail of payments the API received."""

from __future__ import annotations

from typing import Any

from .config import explorer_url
from .db import get_pool


async def record_settlement(
    *,
    transaction: str,
    network: str,
    payer: str | None,
    amount: str | None,
    pay_to: str | None,
    resource: str | None,
) -> None:
    pool = get_pool()
    if pool is None:
        return
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO settlements (transaction, network, payer, pay_to, amount, resource)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            transaction,
            network,
            payer,
            pay_to,
            amount,
            resource,
        )


async def list_settlements(limit: int = 20) -> list[dict[str, Any]]:
    pool = get_pool()
    if pool is None:
        return []
    async with pool.acquire() as conn:
        recs = await conn.fetch(
            """
            SELECT transaction, network, payer, amount, resource, settled_at
            FROM settlements ORDER BY settled_at DESC LIMIT $1
            """,
            limit,
        )
    return [
        {
            "transaction": r["transaction"],
            "network": r["network"],
            "payer": r["payer"],
            "amount": r["amount"],
            "resource": r["resource"],
            "settled_at": r["settled_at"].isoformat(),
            "explorer": explorer_url(r["network"], r["transaction"]),
        }
        for r in recs
    ]
