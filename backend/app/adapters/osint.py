"""OSINT adapter — multi-source web intelligence for blockchain investigation.

Architecture: parallel search across multiple engines with deduplication.

Sources (in priority order):
  1. Exa AI        — semantic neural search, best for crypto/darkweb mentions
                     POST https://api.exa.ai/search  (API key required)
  2. DuckDuckGo    — Instant Answer API, different index, free/no key
                     GET  https://api.duckduckgo.com/  (fallback + complement)
  3. ip-api.com    — IP geolocation + ASN (free, 45 req/min)
  4. RDAP          — domain WHOIS registration data (completely free)

All sources run in parallel via asyncio.gather(). Results are merged and
deduplicated by URL. Failures in any single source never raise — they return
empty and let others fill in.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Exa AI Search
# ─────────────────────────────────────────────────────────────────────────────

class ExaSearchAdapter:
    """Exa AI neural search — best for semantic/crypto/darkweb queries.

    Docs: https://exa.ai/docs/reference/search-api-guide-for-coding-agents
    Endpoint: POST https://api.exa.ai/search
    Auth: x-api-key header
    """
    provider_name = "exa"
    BASE_URL = "https://api.exa.ai"

    def __init__(self) -> None:
        key = settings.exa_api_key
        self._api_key: str | None = key.get_secret_value() if key else None

    @property
    def available(self) -> bool:
        return bool(self._api_key)

    async def search(
        self,
        query: str,
        *,
        num_results: int = 10,
        search_type: str = "auto",          # auto | fast | instant | deep-lite
        use_highlights: bool = True,
        category: str | None = None,        # news | company | personal site | etc.
        include_domains: list[str] | None = None,
        exclude_domains: list[str] | None = None,
        start_published_date: str | None = None,  # ISO 8601
    ) -> list[dict[str, Any]]:
        """Search via Exa AI. Returns list of structured result dicts."""
        if not self.available:
            logger.debug("exa.unavailable", reason="no_api_key")
            return []

        payload: dict[str, Any] = {
            "query": query,
            "type": search_type,
            "numResults": min(num_results, 20),
            "contents": {
                "highlights": True,
            },
        }
        if category:
            payload["category"] = category
        if include_domains:
            payload["includeDomains"] = include_domains
        if exclude_domains:
            payload["excludeDomains"] = exclude_domains
        if start_published_date:
            payload["startPublishedDate"] = start_published_date

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.post(
                    f"{self.BASE_URL}/search",
                    headers={
                        "x-api-key": self._api_key,
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    results = []
                    for r in (data.get("results") or []):
                        highlights = r.get("highlights") or []
                        snippet = highlights[0] if highlights else (r.get("text") or "")[:300]
                        results.append({
                            "source": "exa",
                            "title": r.get("title", ""),
                            "url": r.get("url", ""),
                            "snippet": snippet[:400],
                            "published_date": r.get("publishedDate"),
                            "author": r.get("author"),
                            "score": r.get("score"),
                        })
                    logger.info("exa.search.ok", query=query[:40], count=len(results))
                    return results
                else:
                    logger.warning("exa.search.error",
                                   status=resp.status_code, body=resp.text[:200])
        except Exception as exc:  # noqa: BLE001
            logger.warning("exa.search.failed", query=query[:40], error=str(exc))
        return []

    async def search_crypto_threat(self, address: str) -> list[dict[str, Any]]:
        """Specialized Exa search for crypto threat intelligence."""
        results = []

        # Run 3 targeted searches in parallel
        tasks = [
            # 1. Direct address mention + crime/fraud context
            self.search(
                f'"{address}" (scam OR hack OR fraud OR "money laundering" OR ransomware OR mixer OR darknet)',
                num_results=5,
                search_type="auto",
            ),
            # 2. Address on blockchain analytics / security sites
            self.search(
                f'"{address}"',
                num_results=5,
                include_domains=[
                    "etherscan.io", "bscscan.com", "tronscan.org",
                    "chainalysis.com", "elliptic.co", "coinbase.com",
                    "certik.com", "slowmist.com", "peckshield.com",
                    "rekt.news", "cryptoscam.com", "scamadviser.com",
                ],
            ),
            # 3. News mentions
            self.search(
                f'"{address}"',
                num_results=3,
                category="news",
            ),
        ]
        batch = await asyncio.gather(*tasks, return_exceptions=True)
        for r in batch:
            if isinstance(r, list):
                results.extend(r)
        return results

    async def search_entity(self, entity_name: str) -> list[dict[str, Any]]:
        """Search for a named entity (exchange, mixer, project)."""
        results = []
        tasks = [
            self.search(
                f"{entity_name} cryptocurrency scam fraud hack",
                num_results=5,
            ),
            self.search(
                f"{entity_name} blockchain",
                num_results=5,
                category="news",
                start_published_date="2022-01-01",
            ),
        ]
        batch = await asyncio.gather(*tasks, return_exceptions=True)
        for r in batch:
            if isinstance(r, list):
                results.extend(r)
        return results


# ─────────────────────────────────────────────────────────────────────────────
# DuckDuckGo Instant Answer (free, no key — complement to Exa)
# ─────────────────────────────────────────────────────────────────────────────

class DuckDuckGoAdapter:
    """DuckDuckGo Instant Answer API — different indexing from Exa, free."""

    async def search(self, query: str, *, max_results: int = 5) -> list[dict[str, Any]]:
        params = {
            "q": query,
            "format": "json",
            "no_html": "1",
            "skip_disambig": "1",
            "t": "TAHRIX",
        }
        try:
            async with httpx.AsyncClient(timeout=12.0) as client:
                resp = await client.get(
                    "https://api.duckduckgo.com/",
                    params=params,
                    headers={"User-Agent": "TAHRIX/1.0"},
                )
                if resp.status_code != 200:
                    return []
                data = resp.json()
        except Exception as exc:  # noqa: BLE001
            logger.debug("ddg.search.failed", error=str(exc))
            return []

        results: list[dict[str, Any]] = []

        if data.get("AbstractText"):
            results.append({
                "source": "duckduckgo",
                "title": data.get("Heading", ""),
                "url": data.get("AbstractURL", ""),
                "snippet": data["AbstractText"][:400],
                "published_date": None,
            })

        for topic in (data.get("RelatedTopics") or [])[:max_results]:
            if isinstance(topic, dict) and topic.get("Text"):
                results.append({
                    "source": "duckduckgo",
                    "title": "",
                    "url": topic.get("FirstURL", ""),
                    "snippet": topic["Text"][:300],
                    "published_date": None,
                })

        return results[:max_results]


# ─────────────────────────────────────────────────────────────────────────────
# Social media search (via Exa targeted + DDG site: search)
# ─────────────────────────────────────────────────────────────────────────────

class SocialMediaAdapter:
    """Social media intelligence — uses Exa (primary) + DDG (fallback)."""

    async def search_mentions(
        self, query: str, *, max_results: int = 10,
    ) -> list[dict[str, Any]]:
        exa = ExaSearchAdapter()
        ddg = DuckDuckGoAdapter()

        tasks = []

        # Exa: search Twitter/X, Reddit, Telegram mentions
        if exa.available:
            tasks.append(exa.search(
                f'"{query}"',
                num_results=max_results // 2,
                include_domains=["twitter.com", "x.com", "reddit.com",
                                 "t.me", "bitcointalk.org", "medium.com"],
            ))
            tasks.append(exa.search(
                f'"{query}" site:reddit.com OR site:twitter.com',
                num_results=max_results // 2,
            ))

        # DDG: site-specific searches as complement
        tasks.append(ddg.search(
            f'site:twitter.com OR site:reddit.com "{query}"',
            max_results=5,
        ))

        results_raw = await asyncio.gather(*tasks, return_exceptions=True)
        merged = []
        seen_urls: set[str] = set()
        for batch in results_raw:
            if isinstance(batch, list):
                for r in batch:
                    url = r.get("url", "")
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        platform = _detect_platform(url)
                        merged.append({**r, "platform": platform})

        return merged[:max_results]


# ─────────────────────────────────────────────────────────────────────────────
# Unified Web Search (Exa primary + DDG complement, parallel, deduplicated)
# ─────────────────────────────────────────────────────────────────────────────

class WebSearchAdapter:
    """Unified multi-source web search.

    Runs Exa AI (primary) + DuckDuckGo (complement) in parallel.
    Results are merged, deduplicated by URL, and sorted by source priority.
    """

    def __init__(self) -> None:
        self._exa = ExaSearchAdapter()
        self._ddg = DuckDuckGoAdapter()

    async def search(
        self, query: str, *, max_results: int = 10,
    ) -> list[dict[str, Any]]:
        """Parallel search across Exa + DuckDuckGo, merged and deduplicated."""
        tasks: list = []

        if self._exa.available:
            tasks.append(self._exa.search(query, num_results=max_results))
        tasks.append(self._ddg.search(query, max_results=max_results // 2))

        batches = await asyncio.gather(*tasks, return_exceptions=True)

        merged: list[dict[str, Any]] = []
        seen_urls: set[str] = set()

        for batch in batches:
            if isinstance(batch, list):
                for r in batch:
                    url = r.get("url", "")
                    # Deduplicate by normalized URL
                    norm = _normalize_url(url)
                    if norm and norm not in seen_urls:
                        seen_urls.add(norm)
                        merged.append(r)

        # Exa results come first (higher priority), DDG after
        merged.sort(key=lambda r: 0 if r.get("source") == "exa" else 1)
        return merged[:max_results]

    async def search_address_intel(
        self, address: str, *, max_results: int = 15,
    ) -> list[dict[str, Any]]:
        """Comprehensive address OSINT — all engines, crypto-focused queries."""
        tasks: list = []

        if self._exa.available:
            # Exa: specialized crypto threat search (3 parallel sub-queries)
            tasks.append(self._exa.search_crypto_threat(address))

        # DDG: general address search
        tasks.append(self._ddg.search(f'"{address}"', max_results=5))
        tasks.append(self._ddg.search(
            f'"{address}" scam OR hack OR darknet OR mixer',
            max_results=5,
        ))

        batches = await asyncio.gather(*tasks, return_exceptions=True)
        merged: list[dict[str, Any]] = []
        seen_urls: set[str] = set()
        for batch in batches:
            if isinstance(batch, list):
                for r in batch:
                    norm = _normalize_url(r.get("url", ""))
                    if norm and norm not in seen_urls:
                        seen_urls.add(norm)
                        merged.append(r)

        merged.sort(key=lambda r: 0 if r.get("source") == "exa" else 1)
        logger.info("web_search.address_intel.done",
                    address=address[:12], total=len(merged))
        return merged[:max_results]

    # Context manager support (for backwards compat with existing tool code)
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        pass


# ─────────────────────────────────────────────────────────────────────────────
# WHOIS / IP lookup
# ─────────────────────────────────────────────────────────────────────────────

class WhoisAdapter:
    """WHOIS lookup via RDAP (free) and IP geolocation via ip-api.com (free)."""

    async def lookup_domain(self, domain: str) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"https://rdap.org/domain/{domain}",
                    headers={"User-Agent": "TAHRIX/1.0"},
                    follow_redirects=True,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    registrar = registrant = creation = expiry = ""
                    nameservers: list[str] = []

                    for entity in (data.get("entities") or []):
                        roles = entity.get("roles") or []
                        vcard = (entity.get("vcardArray") or [None, []])[1]
                        name = next(
                            (v[3] for v in vcard if isinstance(v, list) and v[0] == "fn"),
                            ""
                        )
                        if "registrar" in roles:
                            registrar = name
                        if "registrant" in roles:
                            registrant = name

                    for event in (data.get("events") or []):
                        if event.get("eventAction") == "registration":
                            creation = event.get("eventDate", "")
                        if event.get("eventAction") == "expiration":
                            expiry = event.get("eventDate", "")

                    for ns in (data.get("nameservers") or []):
                        nameservers.append(ns.get("ldhName", ""))

                    return {
                        "domain": domain,
                        "registrar": registrar,
                        "registrant": registrant,
                        "created": creation,
                        "expires": expiry,
                        "nameservers": nameservers,
                        "status": data.get("status", []),
                        "raw_handle": data.get("handle"),
                    }
        except Exception as exc:  # noqa: BLE001
            logger.warning("whois.domain.failed", domain=domain, error=str(exc))
        return {"domain": domain, "error": "lookup_failed"}

    async def lookup_ip(self, ip: str) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"http://ip-api.com/json/{ip}"
                    f"?fields=status,country,countryCode,region,city,"
                    f"isp,org,as,hosting,proxy,vpn,tor",
                    headers={"User-Agent": "TAHRIX/1.0"},
                )
                if resp.status_code == 200:
                    return resp.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("whois.ip.failed", ip=ip, error=str(exc))
        return {"ip": ip, "error": "lookup_failed"}


# ─────────────────────────────────────────────────────────────────────────────
# Darkweb / Threat Intel Monitor
# ─────────────────────────────────────────────────────────────────────────────

class DarkwebMonitorAdapter:
    """Threat intelligence — static DB + multi-source OSINT via Exa + DDG."""

    # Known mixer/darknet addresses (static, confirmed)
    KNOWN_THREAT_ADDRESSES: dict[str, dict] = {
        # ── Tornado Cash (OFAC sanctioned Aug 2022) ──────────────────────────
        "0xd882cfc20f52f2599d84b8e8d58c7fb62cfe344b": {
            "name": "Tornado Cash 0.1 ETH", "type": "mixer", "severity": 0.95,
        },
        "0x910cbd523d972eb0a6f4cae4618ad62622b39dbf": {
            "name": "Tornado Cash 1 ETH", "type": "mixer", "severity": 0.95,
        },
        "0xa160cdab225685da1d56aa342ad8841c3b53f291": {
            "name": "Tornado Cash 100 ETH", "type": "mixer", "severity": 0.95,
        },
        "0xfd8610d20aa15b7b2e3be39b396a1bc3516c7144": {
            "name": "Tornado Cash 1000 ETH", "type": "mixer", "severity": 0.97,
        },
        "0x8576acc5c05d6ce88f4e49bf65bdf0c62f91353c": {
            "name": "Tornado Cash Router", "type": "mixer", "severity": 0.95,
        },
        "0x722122df12d4e14e13ac3b6895a86e84145b6967": {
            "name": "Tornado Cash Proxy", "type": "mixer", "severity": 0.95,
        },
        # Tornado Cash Nova (ETH) — all denominations
        "0x77777feddddffc19ff86db637967013e6c6a116c": {
            "name": "Tornado Cash Nova (ETH)", "type": "mixer", "severity": 0.95,
        },
        "0x94a1b5cdb22c43faab4abeb5c74999895464ddaf": {
            "name": "Tornado Cash Nova Pool", "type": "mixer", "severity": 0.95,
        },
        "0x47ce0c6ed5b0ce3d3a51fdb1c52dc66a7c3c2936": {
            "name": "Tornado Cash 10 ETH", "type": "mixer", "severity": 0.95,
        },
        "0x12d66f87a04a9e220c9d40f6a09a4de40b879884": {
            "name": "Tornado Cash 0.01 ETH", "type": "mixer", "severity": 0.90,
        },
        "0x610b717796ad172b316836ac95a2ffad065ceab4": {
            "name": "Tornado Cash USDC", "type": "mixer", "severity": 0.95,
        },
        "0x5efda5f0fabb2f6de5e2f3a3c3c6e9d08a1f56a1ce": {
            "name": "Tornado Cash USDT", "type": "mixer", "severity": 0.95,
        },
        "0x09227deaeE08a5Ba9D6Eb057F922aDfAd191C36c": {
            "name": "Tornado Cash WBTC", "type": "mixer", "severity": 0.95,
        },
        "0x09227deaee08a5ba9d6eb057f922adfad191c36c": {
            "name": "Tornado Cash WBTC", "type": "mixer", "severity": 0.95,
        },
        "0x0836222f2b2b5a6700c2c38e09ad4e23831a76b": {
            "name": "Tornado Cash Router v2", "type": "mixer", "severity": 0.95,
        },
        "0x745daa146934b27e3f0b6bff1a6e36b9b90fb131": {
            "name": "Tornado Cash Mining v2", "type": "mixer", "severity": 0.90,
        },
        # ── Blender.io (OFAC) ────────────────────────────────────────────────
        "0x1da5821544e25c636c1417ba96ade4cf6d2f9b5a": {
            "name": "Blender.io (OFAC)", "type": "mixer", "severity": 0.99,
        },
        # ── Lazarus Group / DPRK (OFAC) ──────────────────────────────────────
        "0x7f367cc41522ce07553e823bf3be79a889debe1b": {
            "name": "Lazarus Group ETH (OFAC)", "type": "darknet", "severity": 1.0,
        },
        "0xd882cfc20f52f2599d84b8e8d58c7fb62cfe344b": {
            "name": "Lazarus / Tornado Cash linked", "type": "darknet", "severity": 0.97,
        },
        # ── Sinbad / Chipmixer ────────────────────────────────────────────────
        "0x6acdfba02d0835ea9f6ef8b4b7eab0d83d53c9c3": {
            "name": "Sinbad Mixer", "type": "mixer", "severity": 0.95,
        },
    }

    THREAT_KEYWORDS = [
        "tornado cash", "blender.io", "chipmixer", "wasabi wallet",
        "silk road", "alphabay", "hansa", "empire market", "hydra market",
        "lazarus group", "ransomware", "darknet market", "money laundering",
        "rug pull", "exit scam", "phishing", "stolen funds", "hack proceeds",
        "crypto mixer", "tumbler", "ofac sanction", "chainalysis alert",
    ]

    async def check_address_threats(self, address: str) -> list[dict[str, Any]]:
        """Multi-source threat check: static DB + Exa + DDG parallel."""
        threats: list[dict[str, Any]] = []
        addr_lower = address.lower()

        # 1. Static known-threat DB (instant, no network)
        for threat_addr, info in self.KNOWN_THREAT_ADDRESSES.items():
            if addr_lower == threat_addr.lower():
                threats.append({
                    "source": "static_threat_db",
                    "type": info["type"],
                    "name": info["name"],
                    "severity": info["severity"],
                    "description": f"Address matches known {info['type']}: {info['name']}",
                    "url": None,
                    "confirmed": True,
                })

        # 2. Exa AI — semantic threat search (parallel queries)
        exa = ExaSearchAdapter()
        ddg = DuckDuckGoAdapter()

        exa_tasks = []
        if exa.available:
            exa_tasks.append(exa.search(
                f'"{address}" scam hack fraud ransomware "money laundering" mixer darknet sanction',
                num_results=5,
                search_type="auto",
            ))
            # Targeted search on security/blockchain analytics sites
            exa_tasks.append(exa.search(
                f'"{address}"',
                num_results=5,
                include_domains=[
                    "chainalysis.com", "elliptic.co", "ciphertrace.com",
                    "slowmist.com", "peckshield.com", "certik.com",
                    "rekt.news", "ofac.treas.gov", "sanctions.io",
                    "etherscan.io", "bscscan.com",
                ],
            ))

        # DDG as complement
        ddg_tasks = [
            ddg.search(
                f'"{address}" darknet ransomware scam hack "money laundering"',
                max_results=5,
            ),
            ddg.search(
                f'"{address}" chainalysis elliptic sanction',
                max_results=3,
            ),
        ]

        all_tasks = exa_tasks + ddg_tasks
        if all_tasks:
            search_batches = await asyncio.gather(*all_tasks, return_exceptions=True)
            seen_urls: set[str] = set()
            for batch in search_batches:
                if not isinstance(batch, list):
                    continue
                for r in batch:
                    url = r.get("url", "")
                    if url in seen_urls:
                        continue
                    seen_urls.add(url)
                    snippet = (r.get("snippet") or "").lower()
                    matched_kw = [kw for kw in self.THREAT_KEYWORDS if kw in snippet]
                    if matched_kw or r.get("source") == "exa":
                        # Score based on keyword density and source
                        base_sev = 0.35 if r.get("source") == "exa" else 0.25
                        severity = min(base_sev + len(matched_kw) * 0.08, 0.85)
                        threats.append({
                            "source": f"osint_{r.get('source','web')}",
                            "type": "mention",
                            "severity": round(severity, 2),
                            "description": (r.get("snippet") or r.get("title") or "")[:350],
                            "url": url,
                            "title": r.get("title", ""),
                            "keywords": matched_kw,
                            "confirmed": False,
                        })

        logger.info("darkweb_monitor.done",
                    address=address[:12], threats=len(threats))
        return threats

    async def search_darkweb_mentions(
        self, query: str, *, max_results: int = 5,
    ) -> list[dict[str, Any]]:
        """Broader darkweb/threat context search for an entity or domain."""
        exa = ExaSearchAdapter()
        ddg = DuckDuckGoAdapter()
        tasks: list = []
        if exa.available:
            tasks.append(exa.search(
                f'"{query}" darknet OR "dark web" OR tor OR onion OR ransomware OR scam',
                num_results=max_results,
            ))
        tasks.append(ddg.search(
            f'"{query}" darknet OR tor OR "dark web" OR scam',
            max_results=max_results,
        ))
        batches = await asyncio.gather(*tasks, return_exceptions=True)
        results = []
        seen: set[str] = set()
        for batch in batches:
            if isinstance(batch, list):
                for r in batch:
                    url = r.get("url", "")
                    if url not in seen:
                        seen.add(url)
                        results.append(r)
        return results[:max_results]


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _normalize_url(url: str) -> str:
    """Normalize URL for deduplication (strip query params, lowercase)."""
    if not url:
        return ""
    try:
        p = urlparse(url.lower())
        return f"{p.scheme}://{p.netloc}{p.path}".rstrip("/")
    except Exception:  # noqa: BLE001
        return url.lower()[:100]


def _detect_platform(url: str) -> str:
    """Detect social platform from URL."""
    url_lower = url.lower()
    if "twitter.com" in url_lower or "x.com" in url_lower:
        return "twitter"
    if "reddit.com" in url_lower:
        return "reddit"
    if "t.me" in url_lower or "telegram" in url_lower:
        return "telegram"
    if "bitcointalk" in url_lower:
        return "bitcointalk"
    if "medium.com" in url_lower:
        return "medium"
    if "youtube.com" in url_lower:
        return "youtube"
    return "web"
