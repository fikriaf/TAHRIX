"""POST /api/v1/resolve — Input Resolver endpoint.

Accepts any freeform input (address, company name, domain, email, IP, TX hash)
and returns a list of resolved blockchain addresses ready to investigate.

Used by the frontend to enable "investigate anything" UX before creating cases.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.api.v1.dependencies import get_current_user
from app.models.sql import User
from app.services.input_resolver import InputResolver, ResolveResult

router = APIRouter(prefix="/resolve", tags=["resolve"])


@router.post(
    "",
    summary="Resolve any input to blockchain addresses",
    response_model=dict,
)
async def resolve_input(
    body: dict[str, Any],
    current_user: User = Depends(get_current_user),
) -> dict:
    """Resolve a freeform input string to blockchain address(es).

    Accepts:
    - Wallet address (EVM, BTC, TRON, Solana)
    - TX hash
    - Company / entity name  (e.g. "FTX", "Binance", "TerraLuna")
    - Domain                 (e.g. "ftx.com", "tornado.cash")
    - Email                  (e.g. "sam@ftx.com")
    - IP address

    Returns a list of resolved addresses with chain, label, and confidence.
    """
    raw = str(body.get("input", "")).strip()
    max_results = int(body.get("max_results", 8))

    resolver = InputResolver()
    result: ResolveResult = await resolver.resolve(raw, max_results=max_results)
    return result.to_dict()
