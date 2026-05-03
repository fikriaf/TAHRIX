"""Input Resolver Service.

Accepts any freeform input and returns a list of resolved blockchain addresses
with chain, label, and confidence.

Supported input types (auto-detected):
  • EVM address        0x[40 hex]
  • Bitcoin address    1..., 3..., bc1...
  • TRON address       T[33 base58]
  • Solana address     base58, 32-44 chars
  • TX hash            0x[64 hex]  or  [64 hex] (BTC)
  • Domain             something.tld
  • Email              user@domain.tld
  • IP address         x.x.x.x
  • Company/Entity     anything else → Exa search to extract addresses

Resolution pipeline:
  1. Regex-detect type
  2. If already an address → return directly (confidence 1.0)
  3. If domain/email/company/IP → multi-source Exa search to extract addresses
  4. Deduplicate, rank by confidence, return top N
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.adapters.osint import ExaSearchAdapter
from app.core.logging import get_logger
from app.models.enums import Chain

logger = get_logger(__name__)

# ── Address regexes ──────────────────────────────────────────────────────────
_RE_EVM      = re.compile(r"\b(0x[0-9a-fA-F]{40})\b")
_RE_TX_ETH   = re.compile(r"\b(0x[0-9a-fA-F]{64})\b")
_RE_TX_BTC   = re.compile(r"\b([0-9a-fA-F]{64})\b")
_RE_BTC_BECH = re.compile(r"\b(bc1[02-9ac-hj-np-z]{6,87})\b")
_RE_BTC_LEGACY = re.compile(r"\b([13][a-km-zA-HJ-NP-Z1-9]{25,34})\b")
_RE_TRON     = re.compile(r"\b(T[1-9A-HJ-NP-Za-km-z]{33})\b")
_RE_SOLANA   = re.compile(r"\b([1-9A-HJ-NP-Za-km-z]{32,44})\b")
_RE_EMAIL    = re.compile(r"\b[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}\b")
_RE_DOMAIN   = re.compile(r"\b(?:[a-zA-Z0-9\-]+\.)+[a-zA-Z]{2,}\b")
_RE_IP       = re.compile(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b")

# Chain-specific well-known entity domains → seed address lookups
_CHAIN_HINT_DOMAINS: dict[str, Chain] = {
    "etherscan.io": Chain.ETH,
    "bscscan.com": Chain.BNB,
    "polygonscan.com": Chain.POLYGON,
    "basescan.org": Chain.BASE,
    "tronscan.org": Chain.TRON,
    "blockchain.com": Chain.BTC,
    "blockstream.info": Chain.BTC,
    "solscan.io": Chain.SOL,
    "explorer.solana.com": Chain.SOL,
}

# Exa query templates for different input types - BROADER search including social media
_EXA_COMPANY_QUERIES = [
    '"{name}"',  # General search for the entity
    '"{name}" twitter OR instagram OR social media',
    '"{name}" crypto blockchain ethereum',
    '"{name}" telegram discord',
    '"{name}" scam OR fraud OR hack',
    '"{name}" founder OR creator OR team',
]
_EXA_DOMAIN_QUERIES = [
    'site:{domain}',
    '{domain} whois OR owner',
    '{domain} crypto project',
]
_EXA_EMAIL_QUERIES = [
    '"{email}" twitter OR social media',
    '"{email}" crypto OR blockchain',
]


@dataclass
class ResolvedAddress:
    address: str
    chain: Chain
    label: str = ""
    input_type: str = "unknown"
    confidence: float = 1.0
    source: str = "direct"
    metadata: dict[str, Any] = field(default_factory=dict)
    osint_evidence: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "address": self.address,
            "chain": self.chain.value,
            "label": self.label,
            "input_type": self.input_type,
            "confidence": round(self.confidence, 3),
            "source": self.source,
            "metadata": self.metadata,
            "osint_evidence": self.osint_evidence,
        }


@dataclass
class ResolveResult:
    raw_input: str
    input_type: str
    resolved: list[ResolvedAddress]
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw_input": self.raw_input,
            "input_type": self.input_type,
            "resolved": [r.to_dict() for r in self.resolved],
            "count": len(self.resolved),
            "warnings": self.warnings,
        }


class InputResolver:
    """Resolves any freeform input to a list of blockchain addresses."""

    MAX_RESULTS = 8

    def __init__(self) -> None:
        self._exa = ExaSearchAdapter()

    async def _search_osint_only(
        self, raw: str, *, max_results: int = 5,
    ) -> list[dict[str, str]]:
        """Search for OSINT only - no address extraction."""
        queries = [
            f'"{raw}" twitter OR instagram OR facebook',
            f'"{raw}" telegram discord',
            f'"{raw}" crypto scam fraud',
            f'"{raw}" founder developer team',
            f'"{raw}" site:twitter.com OR site:instagram.com OR site:telegram.org',
        ]
        
        import asyncio
        tasks = [
            self._exa.search(q, num_results=3, search_type="auto")
            for q in queries
        ]
        batches = await asyncio.gather(*tasks, return_exceptions=True)
        
        results = []
        seen_urls = set()
        for batch in batches:
            if not isinstance(batch, list):
                continue
            for r in batch:
                url = r.get("url", "")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    results.append({
                        "title": r.get("title", "")[:200],
                        "snippet": r.get("snippet", "")[:300],
                        "url": url,
                    })
        
        return results[:max_results]

    async def resolve(self, raw: str, *, max_results: int = MAX_RESULTS) -> ResolveResult:
        raw = raw.strip()
        if not raw:
            return ResolveResult(raw_input=raw, input_type="empty", resolved=[],
                                 warnings=["Empty input"])

        input_type, direct = self._detect(raw)
        logger.info("resolver.detect", raw=raw[:40], type=input_type,
                    direct_count=len(direct))

        if direct:
            # Already a blockchain address/hash — return immediately
            return ResolveResult(
                raw_input=raw,
                input_type=input_type,
                resolved=direct[:max_results],
            )

        # Need to search for addresses
        resolved = await self._search_addresses(raw, input_type, max_results=max_results)
        
        # If no addresses found for username/entity, also search for OSINT directly
        osint_only = []
        if not resolved and input_type in ("username", "company_entity"):
            osint_only = await self._search_osint_only(raw, max_results=max_results)
            # Create pseudo-address entries from OSINT results
            for i, ev in enumerate(osint_only):
                resolved.append(ResolvedAddress(
                    address=f"OSINT-{i+1}",
                    chain=Chain.ETH,
                    label=f"OSINT: {ev.get('title', raw)[:30]}",
                    input_type="osint_only",
                    confidence=0.5,
                    source="exa_osint",
                    metadata={"osint_only": True},
                    osint_evidence=osint_only,
                ))
        
        warnings: list[str] = []
        if not resolved:
            warnings.append(
                f"No blockchain addresses found for '{raw[:40]}'. "
                "Showing OSINT results instead."
            )
        return ResolveResult(
            raw_input=raw,
            input_type=input_type,
            resolved=resolved[:max_results],
            warnings=warnings,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Type detection
    # ─────────────────────────────────────────────────────────────────────────
    def _detect(self, raw: str) -> tuple[str, list[ResolvedAddress]]:
        """Return (input_type, direct_addresses_if_any)."""

        # EVM TX hash (0x + 64 hex) — check BEFORE EVM address
        if _RE_TX_ETH.match(raw) and len(raw) == 66:
            return "tx_hash_evm", [ResolvedAddress(
                address=raw.lower(), chain=Chain.ETH,
                label="EVM TX Hash", input_type="tx_hash_evm",
                confidence=1.0, source="direct",
            )]

        # EVM address (0x + 40 hex)
        if _RE_EVM.match(raw) and len(raw) == 42:
            return "evm_address", [ResolvedAddress(
                address=raw.lower(), chain=Chain.ETH,
                label="EVM Wallet", input_type="evm_address",
                confidence=1.0, source="direct",
            )]

        # TRON address
        if _RE_TRON.match(raw) and len(raw) == 34:
            return "tron_address", [ResolvedAddress(
                address=raw, chain=Chain.TRON,
                label="TRON Wallet", input_type="tron_address",
                confidence=1.0, source="direct",
            )]

        # Bitcoin bech32
        if _RE_BTC_BECH.match(raw):
            return "btc_address", [ResolvedAddress(
                address=raw, chain=Chain.BTC,
                label="Bitcoin Wallet (bech32)", input_type="btc_address",
                confidence=1.0, source="direct",
            )]

        # Bitcoin legacy/P2SH
        if _RE_BTC_LEGACY.match(raw) and len(raw) in range(25, 35):
            return "btc_address", [ResolvedAddress(
                address=raw, chain=Chain.BTC,
                label="Bitcoin Wallet (legacy)", input_type="btc_address",
                confidence=1.0, source="direct",
            )]

        # Solana address (base58, 32-44 chars, no 0/O/I/l)
        if re.match(r'^[1-9A-HJ-NP-Za-km-z]{32,44}$', raw):
            return "sol_address", [ResolvedAddress(
                address=raw, chain=Chain.SOL,
                label="Solana Wallet", input_type="sol_address",
                confidence=0.9, source="direct",
                metadata={"note": "Solana address detected by pattern"},
            )]

        # BTC TX hash (64 hex, no 0x)
        if re.match(r'^[0-9a-fA-F]{64}$', raw):
            return "tx_hash_btc", [ResolvedAddress(
                address=raw.lower(), chain=Chain.BTC,
                label="Bitcoin TX Hash", input_type="tx_hash_btc",
                confidence=1.0, source="direct",
            )]

        # Email
        if _RE_EMAIL.match(raw):
            return "email", []

        # IP address
        if _RE_IP.match(raw):
            return "ip_address", []

        # Domain (contains a dot and no spaces)
        if "." in raw and " " not in raw and _RE_DOMAIN.match(raw):
            return "domain", []

        # Username-like (no spaces, no special chars, 3-30 chars) - likely social handle
        if re.match(r'^[a-zA-Z0-9_]{3,30}$', raw):
            return "username", []

        # Fallback: company/entity name (free text)
        return "company_entity", []

    # ─────────────────────────────────────────────────────────────────────────
    # Exa-powered address extraction
    # ─────────────────────────────────────────────────────────────────────────
    async def _search_addresses(
        self, raw: str, input_type: str, *, max_results: int,
    ) -> list[ResolvedAddress]:
        """Run Exa queries appropriate for the input type, extract addresses."""

        queries = self._build_queries(raw, input_type)
        if not queries:
            return []

        # Run all queries in parallel
        import asyncio
        tasks = [
            self._exa.search(q, num_results=5, search_type="fast")
            for q in queries
        ]
        batches = await asyncio.gather(*tasks, return_exceptions=True)

        # Collect all text snippets + URLs from results (OSINT evidence)
        all_text = ""
        source_urls: list[str] = []
        osint_evidence: list[dict[str, str]] = []
        for batch in batches:
            if not isinstance(batch, list):
                continue
            for r in batch:
                snippet = r.get("snippet") or ""
                title = r.get("title") or ""
                url = r.get("url") or ""
                all_text += f" {title} {snippet} {url} "
                if url:
                    source_urls.append(url)
                    # Store evidence for each source
                    if title or snippet:
                        osint_evidence.append({
                            "title": title[:200] if title else "",
                            "snippet": snippet[:300] if snippet else "",
                            "url": url,
                        })

        # Limit evidence to unique sources
        seen_urls = set()
        unique_evidence = []
        for e in osint_evidence:
            if e["url"] not in seen_urls:
                seen_urls.add(e["url"])
                unique_evidence.append(e)
        unique_evidence = unique_evidence[:5]  # Max 5 evidence sources

        # Extract addresses from all collected text
        resolved = self._extract_addresses_from_text(
            all_text, input_type=input_type, label=raw, source_urls=source_urls,
        )

        # Deduplicate by address and attach evidence
        seen: set[str] = set()
        unique: list[ResolvedAddress] = []
        for r in resolved:
            key = r.address.lower()
            if key not in seen:
                seen.add(key)
                # Attach OSINT evidence to each resolved address
                r.osint_evidence = unique_evidence
                unique.append(r)

        # Sort by confidence
        unique.sort(key=lambda r: r.confidence, reverse=True)
        logger.info("resolver.search.done",
                    input=raw[:30], type=input_type, found=len(unique))
        return unique[:max_results]

    def _build_queries(self, raw: str, input_type: str) -> list[str]:
        """Build Exa search queries based on input type - BROADER for OSINT."""
        q: list[str] = []
        if input_type == "company_entity" or input_type == "username":
            # Broad search including social media
            q.append(f'"{raw}"')  # General
            q.append(f'"{raw}" twitter OR instagram OR facebook')  # Social
            q.append(f'"{raw}" crypto OR blockchain OR ethereum')  # Crypto
            q.append(f'"{raw}" scam OR fraud OR hack OR phishing')  # Threat intel
            q.append(f'"{raw}" founder OR developer OR team')  # Team
        elif input_type == "domain":
            domain = raw.lower().strip()
            q.append(f'site:{domain}')
            q.append(f'"{domain}" owner OR whois')
            q.append(f'"{domain}" crypto OR project')
        elif input_type == "email":
            q.append(f'"{raw}" twitter OR social')
            q.append(f'"{raw}" crypto OR blockchain')
        elif input_type == "ip_address":
            q.append(f'"{raw}" crypto exchange')
            q.append(f'"{raw}" threat OR malicious')
        return q

    def _extract_addresses_from_text(
        self,
        text: str,
        *,
        input_type: str,
        label: str,
        source_urls: list[str],
    ) -> list[ResolvedAddress]:
        """Extract all blockchain addresses from a blob of text."""
        results: list[ResolvedAddress] = []
        source_str = "exa_search"

        # EVM addresses
        for match in _RE_EVM.finditer(text):
            addr = match.group(1).lower()
            # Infer chain from context
            chain = self._infer_chain_from_context(addr, text, source_urls)
            # Boost confidence if address appears multiple times
            count = text.lower().count(addr)
            conf = min(0.5 + count * 0.1, 0.95)
            results.append(ResolvedAddress(
                address=addr, chain=chain,
                label=f"{label} ({chain.value})",
                input_type=input_type,
                confidence=conf,
                source=source_str,
                metadata={"occurrences": count},
            ))

        # TRON addresses
        for match in _RE_TRON.finditer(text):
            addr = match.group(1)
            count = text.count(addr)
            conf = min(0.5 + count * 0.1, 0.95)
            results.append(ResolvedAddress(
                address=addr, chain=Chain.TRON,
                label=f"{label} (TRON)",
                input_type=input_type,
                confidence=conf,
                source=source_str,
                metadata={"occurrences": count},
            ))

        # Bitcoin bech32
        for match in _RE_BTC_BECH.finditer(text):
            addr = match.group(1)
            count = text.count(addr)
            conf = min(0.5 + count * 0.1, 0.95)
            results.append(ResolvedAddress(
                address=addr, chain=Chain.BTC,
                label=f"{label} (BTC)",
                input_type=input_type,
                confidence=conf,
                source=source_str,
            ))

        # Solana — only extract if looks like a known SOL format
        for match in re.finditer(r'\b([1-9A-HJ-NP-Za-km-z]{43,44})\b', text):
            addr = match.group(1)
            # Skip if looks like it could be an ETH address in base58
            if not any(c in addr for c in '0OIl'):
                count = text.count(addr)
                conf = min(0.4 + count * 0.1, 0.85)
                results.append(ResolvedAddress(
                    address=addr, chain=Chain.SOL,
                    label=f"{label} (SOL)",
                    input_type=input_type,
                    confidence=conf,
                    source=source_str,
                ))

        return results

    def _infer_chain_from_context(
        self, addr: str, text: str, source_urls: list[str],
    ) -> Chain:
        """Guess EVM chain from surrounding context text and source URLs."""
        text_lower = text.lower()
        url_str = " ".join(source_urls).lower()
        combined = text_lower + " " + url_str

        # URL-based signals (most reliable)
        if "bscscan.com" in combined or " bnb " in combined or "binance smart chain" in combined:
            return Chain.BNB
        if "polygonscan.com" in combined or " matic " in combined or "polygon" in combined:
            return Chain.POLYGON
        if "basescan.org" in combined or "base mainnet" in combined:
            return Chain.BASE
        if "arbiscan.io" in combined or "arbitrum" in combined:
            return Chain.ARB

        # Default EVM → ETH
        return Chain.ETH
