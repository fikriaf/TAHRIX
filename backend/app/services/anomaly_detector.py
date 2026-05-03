"""Anomaly Detector — implements the 17 patterns from MVP §3.4.

Each detector is a pure function over a context object (`AnomalyContext`) that
collects raw transactions, neighbor info, and graph queries. Detectors return
zero or one `AnomalyFlag` per pattern. Severity ∈ [0,1] is derived from how
strongly the pattern fires.

Implementation strategy:
  • Patterns that need only the local TX list (P02, P03, P05, P08, P09, P10)
    are computed directly from `AnomalyContext.transactions`.
  • Patterns that need labeled-neighbor knowledge (P01, P11) use the graph
    repository. Pattern P07 (bridge hopping) uses `bridge_events`.
  • Patterns we currently skip in MVP because they need richer data (logs,
    DEX-specific decoding) are P12, P13, P14, P15, P16, P17 — they are
    **registered but no-op** so the registry stays complete; they can be
    enabled when the relevant data sources land.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable

from app.core.logging import get_logger
from app.models.domain import AnomalyFlag, BridgeEvent, TransactionNode
from app.models.enums import AnomalyCode

logger = get_logger(__name__)

# Known mixer markers (substring match on entity_label, case-insensitive).
KNOWN_MIXER_PATTERNS = ("tornado", "sinbad", "blender", "chipmixer", "mixer", "tumbler")

# Known mixer addresses (lowercase) — matches focal address being a mixer itself.
KNOWN_MIXER_ADDRESSES: frozenset[str] = frozenset({
    "0xd882cfc20f52f2599d84b8e8d58c7fb62cfe344b",  # TC 0.1 ETH
    "0x910cbd523d972eb0a6f4cae4618ad62622b39dbf",  # TC 1 ETH
    "0xa160cdab225685da1d56aa342ad8841c3b53f291",  # TC 100 ETH
    "0xfd8610d20aa15b7b2e3be39b396a1bc3516c7144",  # TC 1000 ETH
    "0x8576acc5c05d6ce88f4e49bf65bdf0c62f91353c",  # TC Router
    "0x722122df12d4e14e13ac3b6895a86e84145b6967",  # TC Proxy
    "0x77777feddddffc19ff86db637967013e6c6a116c",  # TC Nova
    "0x94a1b5cdb22c43faab4abeb5c74999895464ddaf",  # TC Nova Pool
    "0x47ce0c6ed5b0ce3d3a51fdb1c52dc66a7c3c2936",  # TC 10 ETH
    "0x12d66f87a04a9e220c9d40f6a09a4de40b879884",  # TC 0.01 ETH
    "0x610b717796ad172b316836ac95a2ffad065ceab4",  # TC USDC
    "0x0836222f2b2b5a6700c2c38e09ad4e23831a76b",   # TC Router v2
    "0x745daa146934b27e3f0b6bff1a6e36b9b90fb131",  # TC Mining v2
    "0x1da5821544e25c636c1417ba96ade4cf6d2f9b5a",  # Blender.io
    "0x7f367cc41522ce07553e823bf3be79a889debe1b",  # Lazarus ETH
    "0x6acdfba02d0835ea9f6ef8b4b7eab0d83d53c9c3",  # Sinbad
})


@dataclass
class AnomalyContext:
    address: str
    chain: str
    transactions: list[TransactionNode] = field(default_factory=list)
    bridge_events: list[BridgeEvent] = field(default_factory=list)
    # Pre-resolved labeled neighbors (1-hop): list of (counterparty, label_str)
    labeled_neighbors: list[tuple[str, str]] = field(default_factory=list)
    sanctioned_neighbors_1hop: int = 0
    sanctioned_neighbors_2hop: int = 0
    is_self_sanctioned: bool = False


Detector = Callable[[AnomalyContext], AnomalyFlag | None]
_REGISTRY: dict[AnomalyCode, Detector] = {}


def detector(code: AnomalyCode):
    def deco(fn: Detector) -> Detector:
        _REGISTRY[code] = fn
        return fn
    return deco


def run_all(ctx: AnomalyContext) -> list[AnomalyFlag]:
    flags: list[AnomalyFlag] = []
    for code, fn in _REGISTRY.items():
        try:
            flag = fn(ctx)
        except Exception as e:  # noqa: BLE001
            logger.exception("anomaly.detector.error", code=code.value, error=str(e))
            continue
        if flag:
            flags.append(flag)
    return flags


# ── helpers ──
def _outgoing(ctx: AnomalyContext) -> list[TransactionNode]:
    return [t for t in ctx.transactions
            if t.from_address and t.from_address.lower() == ctx.address.lower()]


def _incoming(ctx: AnomalyContext) -> list[TransactionNode]:
    return [t for t in ctx.transactions
            if t.to_address and t.to_address.lower() == ctx.address.lower()]


# ── P01 Mixer interaction ──
@detector(AnomalyCode.P01_MIXER)
def detect_mixer(ctx: AnomalyContext) -> AnomalyFlag | None:
    # Check 1: focal address IS a known mixer (e.g. investigating Tornado Cash directly)
    self_is_mixer = ctx.address.lower() in KNOWN_MIXER_ADDRESSES
    if self_is_mixer:
        return AnomalyFlag(
            code=AnomalyCode.P01_MIXER,
            severity=1.0,
            description=f"Address IS a confirmed OFAC-sanctioned mixer/tumbler contract.",
            evidence_tx_hashes=[],
            metadata={"self_mixer": True, "address": ctx.address},
        )

    # Check 2: counterparty interactions with known mixers (via entity labels)
    hits = [
        (cp, label) for cp, label in ctx.labeled_neighbors
        if any(p in (label or "").lower() for p in KNOWN_MIXER_PATTERNS)
    ]
    # Check 3: counterparty addresses match known mixer addresses
    addr_hits = [
        (cp, "known_mixer_address") for cp, _ in ctx.labeled_neighbors
        if cp.lower() in KNOWN_MIXER_ADDRESSES
    ]
    hits = hits + [h for h in addr_hits if h not in hits]

    if not hits:
        return None
    return AnomalyFlag(
        code=AnomalyCode.P01_MIXER,
        severity=min(1.0, 0.6 + 0.15 * len(hits)),
        description=f"Direct interaction with {len(hits)} known mixer address(es).",
        evidence_tx_hashes=[],
        metadata={"counterparties": [cp for cp, _ in hits[:10]]},
    )


# ── P02 Layering: 3+ hop transfers with near-equal values ──
@detector(AnomalyCode.P02_LAYERING)
def detect_layering(ctx: AnomalyContext) -> AnomalyFlag | None:
    # Heuristic: among outgoing TX, find chains where consecutive tx values are
    # within ±1 % AND they target distinct addresses.
    outs = sorted(_outgoing(ctx), key=lambda t: t.timestamp)
    if len(outs) < 3:
        return None
    hits = 0
    evidence: list[str] = []
    for i in range(len(outs) - 2):
        a, b, c = outs[i], outs[i + 1], outs[i + 2]
        vals = [v for v in (a.value_usd or a.value_native, b.value_usd or b.value_native,
                            c.value_usd or c.value_native) if v]
        if len(vals) < 3 or min(vals) <= 0:
            continue
        rel = (max(vals) - min(vals)) / max(vals)
        if rel <= 0.01 and len({a.to_address, b.to_address, c.to_address}) == 3:
            hits += 1
            evidence.extend([a.hash, b.hash, c.hash])
    if hits == 0:
        return None
    return AnomalyFlag(
        code=AnomalyCode.P02_LAYERING,
        severity=min(1.0, 0.55 + 0.1 * hits),
        description=f"{hits} layering chains detected (≥3 hops, near-equal values).",
        evidence_tx_hashes=evidence[:10],
    )


# ── P03 Fan-out structuring: 1 → >10 wallets in <1h ──
@detector(AnomalyCode.P03_FAN_OUT)
def detect_fanout(ctx: AnomalyContext) -> AnomalyFlag | None:
    outs = _outgoing(ctx)
    if not outs:
        return None
    # Sliding window: any 1-hour window where unique recipients > 5 (lowered from 10).
    outs.sort(key=lambda t: t.timestamp)
    window = timedelta(hours=1)
    best_n: int = 0
    best_window: list[TransactionNode] = []
    left = 0
    for right in range(len(outs)):
        while outs[right].timestamp - outs[left].timestamp > window:
            left += 1
        recip = {t.to_address for t in outs[left:right + 1] if t.to_address}
        if len(recip) > best_n:
            best_n = len(recip)
            best_window = outs[left:right + 1]
    if best_n <= 5:
        return None
    return AnomalyFlag(
        code=AnomalyCode.P03_FAN_OUT,
        severity=min(1.0, 0.45 + 0.04 * best_n),
        description=f"Fan-out structuring: sent to {best_n} unique wallets within 1h.",
        evidence_tx_hashes=[t.hash for t in best_window[:10]],
    )


# ── P04 Fan-in consolidation: >10 wallets → 1 in <24h ──
@detector(AnomalyCode.P04_FAN_IN)
def detect_fanin(ctx: AnomalyContext) -> AnomalyFlag | None:
    ins = sorted(_incoming(ctx), key=lambda t: t.timestamp)
    if len(ins) <= 5:
        return None
    window = timedelta(hours=24)
    best_n, best_window = 0, []
    left = 0
    for right in range(len(ins)):
        while ins[right].timestamp - ins[left].timestamp > window:
            left += 1
        senders = {t.from_address for t in ins[left:right + 1] if t.from_address}
        if len(senders) > best_n:
            best_n = len(senders)
            best_window = ins[left:right + 1]
    if best_n <= 5:
        return None
    return AnomalyFlag(
        code=AnomalyCode.P04_FAN_IN,
        severity=min(1.0, 0.45 + 0.04 * best_n),
        description=f"Fan-in consolidation: received from {best_n} unique wallets within 24h.",
        evidence_tx_hashes=[t.hash for t in best_window[:10]],
    )


# ── P05 Peeling chain ──
@detector(AnomalyCode.P05_PEELING)
def detect_peeling(ctx: AnomalyContext) -> AnomalyFlag | None:
    # Simplified: look for series of single-hop outgoing tx with strictly decreasing values.
    outs = sorted(_outgoing(ctx), key=lambda t: t.timestamp)
    if len(outs) < 4:
        return None
    decreasing_run = 1
    longest = 1
    evidence: list[str] = [outs[0].hash]
    cur_chain = [outs[0]]
    for i in range(1, len(outs)):
        prev_v = outs[i - 1].value_usd or outs[i - 1].value_native
        cur_v = outs[i].value_usd or outs[i].value_native
        if prev_v and cur_v and 0 < cur_v < prev_v:
            decreasing_run += 1
            cur_chain.append(outs[i])
            if decreasing_run > longest:
                longest = decreasing_run
                evidence = [t.hash for t in cur_chain[-longest:]]
        else:
            decreasing_run = 1
            cur_chain = [outs[i]]
    if longest < 4:
        return None
    return AnomalyFlag(
        code=AnomalyCode.P05_PEELING,
        severity=min(1.0, 0.50 + 0.07 * longest),
        description=f"Peeling chain of length {longest} detected (decreasing successive transfers).",
        evidence_tx_hashes=evidence[:10],
    )


# ── P06 Round-trip — placeholder (needs deeper graph traversal) ──
@detector(AnomalyCode.P06_ROUND_TRIP)
def detect_round_trip(ctx: AnomalyContext) -> AnomalyFlag | None:
    # Roundtrip pattern: an outgoing tx eventually returns to the originator.
    # In MVP we approximate via direct ping-pong (A→B then B→A) within 24h.
    by_pair: dict[tuple[str, str], list[TransactionNode]] = {}
    for t in ctx.transactions:
        if not t.to_address:
            continue
        key = (t.from_address.lower(), t.to_address.lower())
        by_pair.setdefault(key, []).append(t)
    addr = ctx.address.lower()
    hits: list[str] = []
    for (a, b), txs in by_pair.items():
        if a != addr:
            continue
        rev = by_pair.get((b, a), [])
        for out_tx in txs:
            for in_tx in rev:
                if 0 < (in_tx.timestamp - out_tx.timestamp).total_seconds() < 86400:
                    hits.extend([out_tx.hash, in_tx.hash])
    if not hits:
        return None
    return AnomalyFlag(
        code=AnomalyCode.P06_ROUND_TRIP,
        severity=0.6,
        description="Round-trip pattern: funds returned within 24h.",
        evidence_tx_hashes=hits[:10],
    )


# ── P07 Bridge hopping: >2 bridges in 24h ──
@detector(AnomalyCode.P07_BRIDGE_HOPPING)
def detect_bridge_hopping(ctx: AnomalyContext) -> AnomalyFlag | None:
    if len(ctx.bridge_events) <= 2:
        return None
    events = sorted(ctx.bridge_events, key=lambda b: b.timestamp)
    window = timedelta(hours=24)
    left = 0
    best = 0
    for right in range(len(events)):
        while events[right].timestamp - events[left].timestamp > window:
            left += 1
        best = max(best, right - left + 1)
    if best <= 2:
        return None
    return AnomalyFlag(
        code=AnomalyCode.P07_BRIDGE_HOPPING,
        severity=min(1.0, 0.4 + 0.1 * best),
        description=f"{best} cross-chain bridge events within 24h.",
        metadata={"protocols": list({b.protocol.value for b in events})},
    )


# ── P08 Whale: single TX > $1m USD ──
@detector(AnomalyCode.P08_WHALE)
def detect_whale(ctx: AnomalyContext) -> AnomalyFlag | None:
    big = [t for t in ctx.transactions if (t.value_usd or 0) >= 1_000_000]
    if not big:
        return None
    return AnomalyFlag(
        code=AnomalyCode.P08_WHALE,
        severity=0.75,
        description=f"{len(big)} whale TX (≥ $1m USD) — high-value transfer pattern.",
        evidence_tx_hashes=[t.hash for t in big[:10]],
    )


# ── P09 Dormant reactivation ──
@detector(AnomalyCode.P09_DORMANT_REACTIVATION)
def detect_dormant(ctx: AnomalyContext) -> AnomalyFlag | None:
    if len(ctx.transactions) < 2:
        return None
    times = sorted(t.timestamp for t in ctx.transactions)
    # Gap > 180 days followed by a tx; flag if any such gap exists in trailing year.
    gaps = [(times[i] - times[i - 1]).days for i in range(1, len(times))]
    big_gaps = [g for g in gaps if g >= 180]
    if not big_gaps:
        return None
    # Check that a "big" reactivation tx exists right after the gap.
    return AnomalyFlag(
        code=AnomalyCode.P09_DORMANT_REACTIVATION,
        severity=min(1.0, 0.55 + 0.08 * len(big_gaps)),
        description=f"Wallet reactivated after dormancy ({max(big_gaps)} days max gap).",
        metadata={"max_gap_days": max(big_gaps)},
    )


# ── P10 Rapid succession: >50 TX in <10 min ──
@detector(AnomalyCode.P10_RAPID_SUCCESSION)
def detect_rapid(ctx: AnomalyContext) -> AnomalyFlag | None:
    times = sorted(t.timestamp for t in ctx.transactions)
    window = timedelta(minutes=10)
    left = 0
    best = 0
    for right in range(len(times)):
        while times[right] - times[left] > window:
            left += 1
        best = max(best, right - left + 1)
    if best <= 20:  # lowered from 50
        return None
    return AnomalyFlag(
        code=AnomalyCode.P10_RAPID_SUCCESSION,
        severity=min(1.0, 0.50 + 0.004 * best),
        description=f"{best} transactions within 10 min — rapid succession pattern.",
    )


# ── P11 OFAC indirect: 1-hop neighbor of sanctioned address ──
@detector(AnomalyCode.P11_OFAC_INDIRECT)
def detect_ofac_indirect(ctx: AnomalyContext) -> AnomalyFlag | None:
    if ctx.is_self_sanctioned or ctx.sanctioned_neighbors_1hop == 0:
        return None
    return AnomalyFlag(
        code=AnomalyCode.P11_OFAC_INDIRECT,
        severity=min(1.0, 0.5 + 0.1 * ctx.sanctioned_neighbors_1hop),
        description=f"{ctx.sanctioned_neighbors_1hop} OFAC-sanctioned neighbor(s) at 1 hop.",
    )


# ── P12-P17: heuristic implementations using available TX data ──
# Known DEX router addresses (lowercase) — used by P12 & P17
KNOWN_DEX_ROUTERS = {
    # Uniswap
    "0x7a250d5630b4cf539739df2c5dacb4c659f2488d",  # v2 Router
    "0xe592427a0aece92de3edee1f18e0157c05861564",  # v3 Router
    "0x68b3465833fb72a70ecdf485e0e4c7bd8665fc45",  # v3 Router 2
    "0xef1c6e67703c7bd7107eed8303fbe6ec2554bf6b",  # Universal Router
    # SushiSwap
    "0xd9e1ce17f2641f24ae83637ab66a2cca9c378b9f",
    # PancakeSwap V2
    "0x10ed43c718714eb63d5aa57b78b54704e256024e",
    # 1inch
    "0x1111111254eeb25477b68fb85ed929f73a960582",
    "0x111111125421ca6dc452d289314280a0f8842a65",
    # 0x Protocol
    "0xdef1c0ded9bec7f1a1670819833240f027b25eff",
}

# ERC721 Transfer signature: Transfer(address,address,uint256)
# ERC1155 TransferSingle: TransferSingle(address,address,address,uint256,uint256)
NFT_METHODS = {"transferfrom", "safetransferfrom", "safebatchtransferfrom"}

# DEX swap method selectors (lowercase, 4-byte hex without 0x)
SWAP_METHOD_SIGNATURES = {
    "swapexacttokensfortokens", "swaptokensforexacttokens",
    "swapexactethfortokens", "swaptokensforexacteth",
    "swapexacttokensforeth", "swapethforexacttokens",
    "exactinputsingle", "exactoutputsingle", "exactinput", "exactoutput",
    "swap", "execute",
}


def _is_dex_router(address: str | None) -> bool:
    return bool(address) and address.lower() in KNOWN_DEX_ROUTERS


def _is_swap(tx: TransactionNode) -> bool:
    """Best-effort: TX is a DEX swap if to_address is a known router OR
    the method name matches a swap selector."""
    if _is_dex_router(tx.to_address):
        return True
    if tx.method:
        m = tx.method.lower().split("(")[0].strip()
        return m in SWAP_METHOD_SIGNATURES
    return False


def _is_nft_transfer(tx: TransactionNode) -> bool:
    if not tx.method:
        return False
    return any(m in tx.method.lower() for m in NFT_METHODS)


# ── P12 DEX Wash Trading: same wallet swap-back-and-forth via DEX ──
@detector(AnomalyCode.P12_DEX_WASH)
def detect_dex_wash(ctx: AnomalyContext) -> AnomalyFlag | None:
    """Detect: wallet performs ≥3 swap pairs (buy then sell) on DEX within 1h
    each, returning to similar position. Heuristic: count DEX router round-trips
    where outflow & inflow values are within ±5%."""
    swaps = [t for t in ctx.transactions if _is_swap(t)]
    if len(swaps) < 6:
        return None

    addr = ctx.address.lower()
    out_swaps = sorted(
        [s for s in swaps if s.from_address and s.from_address.lower() == addr],
        key=lambda t: t.timestamp,
    )
    if len(out_swaps) < 6:
        return None

    # Count near-equal value swap pairs within 1-hour windows
    pair_hits = 0
    evidence: list[str] = []
    for i, a in enumerate(out_swaps[:-1]):
        for b in out_swaps[i + 1:i + 5]:  # look ahead 4 swaps max
            dt = (b.timestamp - a.timestamp).total_seconds()
            if dt <= 0 or dt > 3600:
                continue
            va = a.value_usd or a.value_native
            vb = b.value_usd or b.value_native
            if not (va and vb) or min(va, vb) <= 0:
                continue
            rel = abs(va - vb) / max(va, vb)
            if rel <= 0.05:
                pair_hits += 1
                evidence.extend([a.hash, b.hash])
                break

    if pair_hits < 3:
        return None
    return AnomalyFlag(
        code=AnomalyCode.P12_DEX_WASH,
        severity=min(1.0, 0.4 + 0.1 * pair_hits),
        description=f"DEX wash trading: {pair_hits} near-equal swap round-trips on DEX routers within 1h.",
        evidence_tx_hashes=evidence[:10],
        metadata={"swap_pair_count": pair_hits, "total_dex_swaps": len(out_swaps)},
    )


# ── P13 NFT Wash Trading: self-trades / circular NFT transfers ──
@detector(AnomalyCode.P13_NFT_WASH)
def detect_nft_wash(ctx: AnomalyContext) -> AnomalyFlag | None:
    """Detect circular NFT transfer: A → B → A (same token implied via repeated
    counterparty pairs in NFT-method TXs). Severity scales with cycle count."""
    nft_txs = [t for t in ctx.transactions if _is_nft_transfer(t)]
    if len(nft_txs) < 4:
        return None

    addr = ctx.address.lower()
    pairs: dict[tuple[str, str], list[TransactionNode]] = {}
    for t in nft_txs:
        if not (t.from_address and t.to_address):
            continue
        key = (t.from_address.lower(), t.to_address.lower())
        pairs.setdefault(key, []).append(t)

    cycles: list[str] = []
    for (a, b), txs in pairs.items():
        if a != addr:
            continue
        rev = pairs.get((b, a), [])
        if not rev:
            continue
        # For each outgoing NFT tx, check if a matching reverse tx exists within 7d
        for out_tx in txs:
            for in_tx in rev:
                dt = (in_tx.timestamp - out_tx.timestamp).total_seconds()
                if 0 < dt < 7 * 86400:
                    cycles.extend([out_tx.hash, in_tx.hash])

    if len(cycles) < 4:  # at least 2 round-trips
        return None
    return AnomalyFlag(
        code=AnomalyCode.P13_NFT_WASH,
        severity=min(1.0, 0.4 + 0.05 * (len(cycles) // 2)),
        description=f"NFT wash trading: {len(cycles) // 2} circular NFT transfer cycles detected.",
        evidence_tx_hashes=cycles[:10],
        metadata={"cycle_count": len(cycles) // 2},
    )


# ── P14 Flash Loan Attack: many internal calls in a single block ──
@detector(AnomalyCode.P14_FLASH_LOAN)
def detect_flash_loan(ctx: AnomalyContext) -> AnomalyFlag | None:
    """Detect: in a single block, wallet has ≥5 transactions AND total moved
    value exceeds $500k (heuristic for borrow + arb + repay)."""
    by_block: dict[int, list[TransactionNode]] = {}
    for t in ctx.transactions:
        if t.block_number is None:
            continue
        by_block.setdefault(t.block_number, []).append(t)

    suspicious_blocks: list[tuple[int, int, float]] = []
    for blk, txs in by_block.items():
        if len(txs) < 5:
            continue
        total_usd = sum((t.value_usd or 0) for t in txs)
        if total_usd >= 500_000:
            suspicious_blocks.append((blk, len(txs), total_usd))

    if not suspicious_blocks:
        return None

    suspicious_blocks.sort(key=lambda x: x[2], reverse=True)
    top = suspicious_blocks[0]
    evidence = [
        t.hash for t in by_block[top[0]][:10]
    ]
    return AnomalyFlag(
        code=AnomalyCode.P14_FLASH_LOAN,
        severity=min(1.0, 0.5 + 0.1 * len(suspicious_blocks)),
        description=(
            f"Flash-loan signature: {len(suspicious_blocks)} block(s) with "
            f"≥5 TXs and ≥$500k volume (top block {top[0]}: {top[1]} TXs, ${top[2]:,.0f})."
        ),
        evidence_tx_hashes=evidence,
        metadata={"top_block": top[0], "top_tx_count": top[1], "top_volume_usd": top[2]},
    )


# ── P15 Address Poisoning: tiny dust from look-alike address ──
@detector(AnomalyCode.P15_ADDRESS_POISONING)
def detect_address_poisoning(ctx: AnomalyContext) -> AnomalyFlag | None:
    """Detect: incoming TX with very small value (<$1) FROM an address whose
    first/last 4 hex chars match a known counterparty the wallet frequently
    transacts with. Classic vanity-address poisoning attack."""
    ins = _incoming(ctx)
    if not ins:
        return None

    # Build set of "frequent counterparties" (≥3 outgoing TXs with that address)
    out_counterparts: dict[str, int] = {}
    for t in _outgoing(ctx):
        if t.to_address:
            out_counterparts[t.to_address.lower()] = out_counterparts.get(
                t.to_address.lower(), 0,
            ) + 1
    frequent = {a for a, n in out_counterparts.items() if n >= 3}
    if not frequent:
        return None

    suspicious: list[str] = []
    for tx in ins:
        if not tx.from_address:
            continue
        sender = tx.from_address.lower()
        # Dust threshold: <$1 USD or <0.001 native
        is_dust = (
            (tx.value_usd is not None and tx.value_usd < 1)
            or (tx.value_native < 0.001)
        )
        if not is_dust:
            continue
        # Check vanity-prefix similarity with any frequent counterparty
        for freq in frequent:
            if sender == freq:
                continue
            # Match first 6 + last 4 chars (typical poisoning pattern)
            if (sender[:6] == freq[:6] and sender[-4:] == freq[-4:]):
                suspicious.append(tx.hash)
                break

    if len(suspicious) < 1:
        return None
    return AnomalyFlag(
        code=AnomalyCode.P15_ADDRESS_POISONING,
        severity=min(1.0, 0.5 + 0.15 * len(suspicious)),
        description=(
            f"Address-poisoning: {len(suspicious)} dust TX from address(es) "
            f"with vanity-prefix matching a frequent counterparty."
        ),
        evidence_tx_hashes=suspicious[:10],
    )


# ── P16 Rug Pull: massive outflow burst from contract ──
@detector(AnomalyCode.P16_RUG_PULL)
def detect_rug_pull(ctx: AnomalyContext) -> AnomalyFlag | None:
    """Detect: wallet (assumed contract/deployer) experiences a sudden outflow
    spike where >50% of total historical outflow value happens in <1h window.
    Heuristic for liquidity-pull events."""
    outs = _outgoing(ctx)
    if len(outs) < 5:
        return None
    total_value = sum((t.value_usd or t.value_native or 0) for t in outs)
    if total_value <= 0:
        return None

    outs_sorted = sorted(outs, key=lambda t: t.timestamp)
    window = timedelta(hours=1)
    left = 0
    best_window_value = 0.0
    best_window_txs: list[TransactionNode] = []
    for right in range(len(outs_sorted)):
        while outs_sorted[right].timestamp - outs_sorted[left].timestamp > window:
            left += 1
        cur_txs = outs_sorted[left:right + 1]
        cur_val = sum((t.value_usd or t.value_native or 0) for t in cur_txs)
        if cur_val > best_window_value:
            best_window_value = cur_val
            best_window_txs = cur_txs

    pct = best_window_value / total_value
    if pct < 0.5 or len(best_window_txs) < 5:
        return None
    return AnomalyFlag(
        code=AnomalyCode.P16_RUG_PULL,
        severity=min(1.0, 0.4 + pct),
        description=(
            f"Rug-pull signature: {pct*100:.0f}% of total outflow ($"
            f"{best_window_value:,.0f}) drained in 1-hour window across "
            f"{len(best_window_txs)} TXs."
        ),
        evidence_tx_hashes=[t.hash for t in best_window_txs[:10]],
        metadata={"burst_pct": pct, "burst_value_usd": best_window_value},
    )


# ── P17 Sandwich Attack: paired DEX swaps bracketing same-block target ──
@detector(AnomalyCode.P17_SANDWICH)
def detect_sandwich(ctx: AnomalyContext) -> AnomalyFlag | None:
    """Detect: wallet performs ≥2 DEX swaps in the same block targeting the
    same router (front-run + back-run pattern). Strong sandwich-bot signal."""
    swaps_by_block: dict[int, list[TransactionNode]] = {}
    for t in ctx.transactions:
        if t.block_number is None or not _is_swap(t):
            continue
        addr = ctx.address.lower()
        if t.from_address and t.from_address.lower() == addr:
            swaps_by_block.setdefault(t.block_number, []).append(t)

    sandwich_blocks: list[int] = []
    evidence: list[str] = []
    for blk, txs in swaps_by_block.items():
        if len(txs) < 2:
            continue
        # Same router, opposite direction (heuristic: alternating method names)
        routers = {(t.to_address or "").lower() for t in txs}
        if len(routers) == 1:
            sandwich_blocks.append(blk)
            evidence.extend(t.hash for t in txs)

    if len(sandwich_blocks) < 2:
        return None
    return AnomalyFlag(
        code=AnomalyCode.P17_SANDWICH,
        severity=min(1.0, 0.4 + 0.1 * len(sandwich_blocks)),
        description=(
            f"Sandwich-attack signature: {len(sandwich_blocks)} blocks with "
            f"multiple same-block DEX swaps to identical router (front+back-run)."
        ),
        evidence_tx_hashes=evidence[:10],
        metadata={"sandwich_block_count": len(sandwich_blocks)},
    )
