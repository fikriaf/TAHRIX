"""Blockchain address validation & normalization."""

from __future__ import annotations

import re

import base58
from eth_utils import is_address as _eth_is_address
from eth_utils import to_checksum_address

from app.core.exceptions import ValidationError

EVM_ADDRESS_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")
EVM_TX_HASH_RE = re.compile(r"^0x[a-fA-F0-9]{64}$")
SOL_ADDRESS_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")  # base58 ~32-44 chars
SOL_SIG_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{43,88}$")


class Chain:
    ETH = "ETH"
    SOL = "SOL"
    BASE = "BASE"
    POLYGON = "POLYGON"
    BNB = "BNB"

    EVM = {ETH, BASE, POLYGON, BNB}
    ALL = {ETH, SOL, BASE, POLYGON, BNB}


def is_evm_address(addr: str) -> bool:
    return bool(EVM_ADDRESS_RE.match(addr)) and _eth_is_address(addr)


def is_solana_address(addr: str) -> bool:
    if not SOL_ADDRESS_RE.match(addr):
        return False
    try:
        decoded = base58.b58decode(addr)
        return len(decoded) == 32
    except Exception:
        return False


def detect_chain(address: str) -> str:
    """Best-effort chain detection from address shape."""
    if is_evm_address(address):
        return Chain.ETH  # EVM-shaped; caller decides which EVM chain
    if is_solana_address(address):
        return Chain.SOL
    raise ValidationError(f"Unrecognized address format: {address[:12]}...")


def normalize_address(address: str, chain: str | None = None) -> str:
    """Return canonical form: EVM → checksum, Solana → as-is (validated)."""
    address = address.strip()
    chain = chain or detect_chain(address)
    if chain in Chain.EVM:
        if not is_evm_address(address):
            raise ValidationError(f"Invalid EVM address: {address}")
        return to_checksum_address(address)
    if chain == Chain.SOL:
        if not is_solana_address(address):
            raise ValidationError(f"Invalid Solana address: {address}")
        return address
    raise ValidationError(f"Unsupported chain: {chain}")


def is_evm_tx_hash(h: str) -> bool:
    return bool(EVM_TX_HASH_RE.match(h))


def is_solana_signature(s: str) -> bool:
    return bool(SOL_SIG_RE.match(s))


def normalize_tx_hash(h: str, chain: str | None = None) -> str:
    h = h.strip()
    if chain in Chain.EVM or (chain is None and is_evm_tx_hash(h)):
        if not is_evm_tx_hash(h):
            raise ValidationError(f"Invalid EVM tx hash: {h}")
        return h.lower()
    if chain == Chain.SOL or is_solana_signature(h):
        return h
    raise ValidationError(f"Invalid transaction hash: {h}")
