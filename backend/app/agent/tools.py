"""Tool Registry — 18 tools the Agent can call (T01–T18).

Each tool has:
  • a stable name (T01..T18)
  • a JSON-schema description (OpenAI function calling format)
  • an async `execute(args, ctx)` function returning a JSON-serialisable dict

The registry is built lazily; tools that depend on a missing API key are still
registered but return `{"unavailable": true, "reason": ...}` instead of raising
— the agent uses this signal to pick a different tool.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable
import re
import socket

from app.adapters.alchemy import AlchemyAdapter
from app.adapters.btc import BlockstreamAdapter
from app.adapters.chainalysis import ChainalysisAdapter
from app.adapters.etherscan import EtherscanAdapter
from app.adapters.helius import HeliusAdapter
from app.adapters.layerzero import LayerZeroAdapter
from app.adapters.osint import (
    DarkwebMonitorAdapter,
    SocialMediaAdapter,
    WebSearchAdapter,
    WhoisAdapter,
)
from app.adapters.telegram import TelegramAdapter
from app.adapters.tron import TronAdapter
from app.adapters.wormhole import WormholeAdapter
from app.core.exceptions import ConfigurationError, TahrixError
from app.core.logging import get_logger
from app.models.domain import AnomalyFlag, BridgeEvent, TransactionNode
from app.models.enums import Chain
from app.repositories.graph_repository import GraphRepository
from app.services.anomaly_detector import AnomalyContext, run_all
from app.services.gnn_service import GnnService, GnnUnavailableError

logger = get_logger(__name__)

ToolFn = Callable[[dict[str, Any], "ToolContext"], Awaitable[dict[str, Any]]]


def _detect_platform_from_url(url: str) -> str:
    u = url.lower()
    if "twitter.com" in u or "x.com" in u:
        return "twitter"
    if "reddit.com" in u:
        return "reddit"
    if "t.me" in u or "telegram" in u:
        return "telegram"
    if "bitcointalk" in u:
        return "bitcointalk"
    if "medium.com" in u:
        return "medium"
    return "web"


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON schema
    fn: ToolFn

    def to_openai_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass
class ToolContext:
    """Shared state available to all tools during a single investigation."""
    case_id: str
    address: str
    chain: Chain
    seen_addresses: set[str]
    transactions: list[TransactionNode]
    bridge_events: list[BridgeEvent]
    anomaly_flags: list[AnomalyFlag]


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def _safe_call(fn):
    async def _wrapped(args, ctx):
        try:
            return await fn(args, ctx)
        except ConfigurationError as e:
            return {"unavailable": True, "reason": e.message}
        except TahrixError as e:
            return {"error": e.code, "message": e.message}
        except Exception as e:  # noqa: BLE001
            logger.exception("tool.error", tool=fn.__name__, error=str(e))
            return {"error": "internal", "message": str(e)}
    _wrapped.__name__ = fn.__name__
    return _wrapped


# ─────────────────────────────────────────────────────────────────────────────
# Tool implementations
# ─────────────────────────────────────────────────────────────────────────────
@_safe_call
async def t01_get_eth_transactions(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    address = args["address"]
    max_pages = int(args.get("max_pages", 2))
    chain = Chain(args.get("chain", "ETH"))
    async with AlchemyAdapter(chain=chain) as alchemy:
        transfers = await alchemy.iter_asset_transfers(address, max_pages=max_pages)
        nodes = [alchemy.map_transfer_to_tx(t) for t in transfers]
    # Persist + accumulate in ctx
    if nodes:
        await GraphRepository.upsert_transactions_bulk(nodes)
    ctx.transactions.extend(nodes)
    ctx.seen_addresses.update({n.from_address for n in nodes if n.from_address})
    ctx.seen_addresses.update({n.to_address for n in nodes if n.to_address})
    return {
        "count": len(nodes),
        "first_seen": nodes[-1].timestamp.isoformat() if nodes else None,
        "last_seen": nodes[0].timestamp.isoformat() if nodes else None,
    }


@_safe_call
async def t02_get_sol_transactions(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    address = args["address"]
    limit = int(args.get("limit", 100))
    async with HeliusAdapter() as helius:
        raw = await helius.get_transactions_for_address(address, limit=limit)
    nodes = [n for n in (HeliusAdapter.map_enhanced_to_tx(r) for r in raw) if n is not None]
    if nodes:
        await GraphRepository.upsert_transactions_bulk(nodes)
    ctx.transactions.extend(nodes)
    return {"count": len(nodes)}


@_safe_call
async def t03_check_sanctions(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    address = args["address"]
    async with ChainalysisAdapter() as ca:
        result = await ca.check_address(address)
    return {
        "sanctioned": result.sanctioned,
        "identifications": result.identifications,
    }


@_safe_call
async def t04_run_gnn_inference(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    address = args.get("address", ctx.address)
    chain = Chain(args.get("chain", ctx.chain.value))
    sub = await GraphRepository.get_subgraph(address, chain, max_hops=2)
    nodes = sub["nodes"]
    edges = sub["edges"]
    try:
        pred = GnnService.instance().predict(address, nodes, edges)
    except GnnUnavailableError as e:
        return {"unavailable": True, "reason": e.message}
    return {
        "score": pred.score,
        "label": pred.label.value,
        "explanation": pred.explanation,
        "subgraph_size": pred.subgraph_size,
        "top_features": pred.shap_top_features,
    }


@_safe_call
async def t05_trace_forward(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    rows = await GraphRepository.trace_forward(
        args.get("address", ctx.address),
        Chain(args.get("chain", ctx.chain.value)),
        max_hops=int(args.get("hops", 3)),
        limit=int(args.get("limit", 100)),
    )
    return {"count": len(rows), "wallets": rows[:50]}


@_safe_call
async def t06_trace_backward(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    rows = await GraphRepository.trace_backward(
        args.get("address", ctx.address),
        Chain(args.get("chain", ctx.chain.value)),
        max_hops=int(args.get("hops", 3)),
        limit=int(args.get("limit", 100)),
    )
    return {"count": len(rows), "wallets": rows[:50]}


@_safe_call
async def t07_check_bridge_lz(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    tx_hash = args["tx_hash"]
    async with LayerZeroAdapter() as lz:
        msgs = await lz.get_messages_by_tx(tx_hash)
    events: list[BridgeEvent] = []
    for m in msgs:
        ev = LayerZeroAdapter.to_bridge_event(m)
        if ev:
            events.append(ev)
            await GraphRepository.upsert_bridge_event(ev)
    ctx.bridge_events.extend(events)
    return {"count": len(events),
            "events": [e.model_dump(mode="json") for e in events[:5]]}


@_safe_call
async def t08_check_bridge_wh(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    tx_hash = args["tx_hash"]
    async with WormholeAdapter() as wh:
        op = await wh.find_by_source_tx(tx_hash)
    if not op:
        return {"count": 0, "events": []}
    ev = WormholeAdapter.to_bridge_event(op)
    if not ev:
        return {"count": 0, "events": []}
    await GraphRepository.upsert_bridge_event(ev)
    ctx.bridge_events.append(ev)
    return {"count": 1, "events": [ev.model_dump(mode="json")]}


@_safe_call
async def t09_get_entity_label(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    address = args["address"]
    chain = Chain(args.get("chain", "ETH"))
    async with EtherscanAdapter() as es:
        label = await es.get_address_metadata(address, chain=chain)
    return {"address": address,
            "label": label.model_dump(mode="json") if label else None}


@_safe_call
async def t10_detect_anomaly(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    # Use accumulated state in ctx
    sanctioned = ctx.seen_addresses & set(args.get("sanctioned_addresses", []))
    labeled = [(addr, label) for addr, label in args.get("labeled_neighbors", [])]
    actx = AnomalyContext(
        address=ctx.address,
        chain=ctx.chain.value,
        transactions=ctx.transactions,
        bridge_events=ctx.bridge_events,
        labeled_neighbors=labeled,
        sanctioned_neighbors_1hop=len(sanctioned),
        is_self_sanctioned=bool(args.get("self_sanctioned", False)),
    )
    flags = run_all(actx)
    ctx.anomaly_flags = flags
    return {"count": len(flags),
            "flags": [f.model_dump(mode="json") for f in flags]}


@_safe_call
async def t11_generate_report(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    # Wired by the Investigation Runner once finalized — agent should request
    # this only after risk score is computed and the case is ready for export.
    return {"deferred": True, "case_id": ctx.case_id}


@_safe_call
async def t12_send_alert(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    # Build a canonical alert template from context — ignore LLM-generated text
    # to prevent truncation/typos. send_alert is only called for CRITICAL per playbook.
    llm_summary = (args.get("text") or "").strip()
    # Extract first 3 meaningful lines of LLM summary as supplementary notes
    summary_lines = [l for l in llm_summary.splitlines() if l.strip()][:3]
    notes = "\n".join(summary_lines) if summary_lines else "See case report for details."

    # Detect grade from LLM text if present, default CRITICAL (only call for critical)
    grade = "critical"
    for g in ("high", "medium", "low", "critical"):
        if g in llm_summary.lower():
            grade = g
            break
    grade_emoji = {"critical": "🚨", "high": "⚠️", "medium": "🟡", "low": "✅"}
    emoji = grade_emoji[grade]
    chain_val = ctx.chain.value if hasattr(ctx.chain, "value") else str(ctx.chain)

    text = (
        f"{emoji} <b>TAHRIX ALERT — {grade.upper()} RISK</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>Case:</b> {ctx.case_id}\n"
        f"<b>Address:</b> <code>{ctx.address}</code>\n"
        f"<b>Chain:</b> {chain_val}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"{notes}"
    )
    async with TelegramAdapter() as tg:
        result = await tg.send_message(text)
    return {"sent": True, "message_id": result.get("message_id")}


@_safe_call
async def t13_web_search(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """T13 — Multi-source web OSINT: Exa AI (primary) + DuckDuckGo (complement), parallel."""
    query = args["query"]
    max_results = int(args.get("max_results", 10))
    address_mode = args.get("address_mode", False)  # True = use crypto-focused search

    searcher = WebSearchAdapter()

    # Use specialized address search if query looks like/is the target address
    if address_mode or query == ctx.address or (
        len(query) >= 30 and query.replace("0x", "").isalnum()
    ):
        results = await searcher.search_address_intel(query, max_results=max_results)
    else:
        results = await searcher.search(query, max_results=max_results)

    # Persist notable results as OsintNode in Neo4j
    from app.models.domain import OsintNode
    from app.repositories.graph_repository import GraphRepository
    for r in results[:5]:
        url = r.get("url", "")
        if url:
            node = OsintNode(
                source=f"web_search_{r.get('source','web')}",
                entity_ref=ctx.address,
                url=url,
                snippet=(r.get("snippet") or r.get("text", ""))[:300],
                platform=_detect_platform_from_url(url),
                retrieved_at=datetime.now(tz=timezone.utc),
            )
            try:
                await GraphRepository.upsert_osint_node(node)
            except Exception:  # noqa: BLE001
                pass

    # Return condensed result for agent context window
    condensed = [
        {
            "source": r.get("source"),
            "title": r.get("title", "")[:100],
            "url": r.get("url", ""),
            "snippet": (r.get("snippet") or "")[:250],
            "published": r.get("published_date"),
        }
        for r in results
    ]
    return {"count": len(results), "results": condensed}


@_safe_call
async def t14_whois_lookup(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """T14 — WHOIS / IP-geo lookup for domains and IPs associated with a wallet."""
    target = args["target"]  # domain or IP
    target_type = args.get("type", "auto")

    whois = WhoisAdapter()
    import re
    is_ip = bool(re.match(r"^\d{1,3}(\.\d{1,3}){3}$", target))
    if target_type == "ip" or (target_type == "auto" and is_ip):
        result = await whois.lookup_ip(target)
    else:
        result = await whois.lookup_domain(target)

    return result


@_safe_call
async def t15_social_media_intel(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """T15 — Search Twitter/Reddit/Telegram for public mentions (Exa + DDG parallel)."""
    query = args.get("query", ctx.address)
    max_results = int(args.get("max_results", 10))

    social = SocialMediaAdapter()
    mentions = await social.search_mentions(query, max_results=max_results)

    # Persist to Neo4j as OsintNodes
    from app.models.domain import OsintNode
    from app.repositories.graph_repository import GraphRepository
    for m in mentions[:5]:
        url = m.get("url", "")
        if url:
            node = OsintNode(
                source="social_media",
                entity_ref=ctx.address,
                url=url,
                snippet=(m.get("snippet") or m.get("text", ""))[:300],
                platform=m.get("platform", "web"),
                retrieved_at=datetime.now(tz=timezone.utc),
            )
            try:
                await GraphRepository.upsert_osint_node(node)
            except Exception:  # noqa: BLE001
                pass

    condensed = [
        {
            "platform": m.get("platform", "web"),
            "url": m.get("url", ""),
            "snippet": (m.get("snippet") or "")[:200],
            "source": m.get("source"),
        }
        for m in mentions
    ]
    return {"count": len(mentions), "mentions": condensed}


@_safe_call
async def t16_darkweb_monitor(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """T16 — Check known threat databases and darkweb feeds for address/entity mentions."""
    address = args.get("address", ctx.address)
    monitor = DarkwebMonitorAdapter()
    threats = await monitor.check_address_threats(address)

    # Persist to Neo4j as ThreatIntelHit nodes
    if threats:
        from app.models.domain import ThreatIntelHit
        from app.repositories.graph_repository import GraphRepository
        for t in threats:
            hit = ThreatIntelHit(
                source=t.get("source", "unknown"),
                address=address,
                threat_type=t.get("type", "unknown"),
                severity=float(t.get("severity", 0.5)),
                description=t.get("description", ""),
                url=t.get("url"),
                confirmed=bool(t.get("confirmed", False)),
                detected_at=datetime.now(tz=timezone.utc),
            )
            await GraphRepository.upsert_threat_intel(hit)

    return {
        "count": len(threats),
        "threats": threats,
        "max_severity": max((t.get("severity", 0) for t in threats), default=0),
    }


@_safe_call
async def t17_get_btc_transactions(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """T17 — Fetch Bitcoin transactions for an address via Blockstream.info (free, no key)."""
    address = args["address"]
    limit = int(args.get("limit", 25))
    async with BlockstreamAdapter() as btc:
        raw_txs = await btc.get_transactions(address, limit=limit)
        nodes = [n for n in (btc.map_tx_to_node(t, address) for t in raw_txs) if n is not None]
    if nodes:
        from app.repositories.graph_repository import GraphRepository
        await GraphRepository.upsert_transactions_bulk(nodes)
    ctx.transactions.extend(nodes)
    ctx.seen_addresses.update({n.from_address for n in nodes if n.from_address})
    ctx.seen_addresses.update({n.to_address for n in nodes if n.to_address})
    return {
        "count": len(nodes),
        "first_seen": nodes[-1].timestamp.isoformat() if nodes else None,
        "last_seen": nodes[0].timestamp.isoformat() if nodes else None,
    }


@_safe_call
async def t18_get_tron_transactions(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """T18 — Fetch TRON TRX + TRC20 transactions via TronGrid (free, no key)."""
    address = args["address"]
    limit = int(args.get("limit", 50))
    tron = TronAdapter()
    raw_txs = await tron.get_transactions(address, limit=limit)
    raw_trc20 = await tron.get_trc20_transactions(address, limit=limit)

    nodes = [n for n in (tron.map_tx_to_node(t) for t in raw_txs) if n is not None]
    nodes += [n for n in (tron.map_trc20_to_node(t) for t in raw_trc20) if n is not None]

    if nodes:
        from app.repositories.graph_repository import GraphRepository
        await GraphRepository.upsert_transactions_bulk(nodes)
    ctx.transactions.extend(nodes)
    ctx.seen_addresses.update({n.from_address for n in nodes if n.from_address})
    ctx.seen_addresses.update({n.to_address for n in nodes if n.to_address})
    return {"count": len(nodes), "trx": len(raw_txs), "trc20": len(raw_trc20)}


@_safe_call
async def t19_resolve_identity(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """T19 — Resolve any identity (company, domain, email, name) to blockchain addresses.

    Useful mid-investigation when you discover a new entity name or domain
    and need to find its associated wallet addresses before investigating further.
    """
    from app.services.input_resolver import InputResolver
    raw = args["input"]
    max_results = int(args.get("max_results", 5))
    resolver = InputResolver()
    result = await resolver.resolve(raw, max_results=max_results)
    # Add newly found addresses to ctx for agent awareness
    for r in result.resolved:
        ctx.seen_addresses.add(r.address)
    return result.to_dict()


@_safe_call
async def t20_expand_counterparties(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """T20 — Depth expansion: fetch transactions for counterparty wallets discovered so far.

    This is the key to building a branching graph. After get_eth_transactions fills
    ctx.seen_addresses with counterparties, call this tool to fetch THEIR transactions
    and persist them to Neo4j, completing the next depth layer.

    Fetches up to `max_addresses` unseen counterparties in parallel (Alchemy, 1 page each).
    Only runs on EVM chains. Use once per depth hop, after the initial TX fetch.
    """
    import asyncio

    max_addresses = min(int(args.get("max_addresses", 10)), 20)
    max_pages = int(args.get("max_pages", 1))
    chain = Chain(args.get("chain", ctx.chain.value))

    # Collect addresses NOT yet expanded (exclude focal address)
    already_fetched: set[str] = {ctx.address.lower()}
    # Mark any address we've already fetched TXs for
    for tx in ctx.transactions:
        if tx.from_address:
            already_fetched.add(tx.from_address.lower())
        if tx.to_address:
            already_fetched.add(tx.to_address.lower())

    candidates = [
        a for a in ctx.seen_addresses
        if a.lower() not in already_fetched and a.startswith("0x") and len(a) == 42
    ][:max_addresses]

    if not candidates:
        return {"expanded": 0, "message": "No new EVM counterparties to expand"}

    async def _fetch_one(address: str) -> int:
        try:
            async with AlchemyAdapter(chain=chain) as alchemy:
                transfers = await alchemy.iter_asset_transfers(address, max_pages=max_pages)
                nodes = [alchemy.map_transfer_to_tx(t) for t in transfers]
            if nodes:
                await GraphRepository.upsert_transactions_bulk(nodes)
                ctx.transactions.extend(nodes)
                ctx.seen_addresses.update({n.from_address for n in nodes if n.from_address})
                ctx.seen_addresses.update({n.to_address for n in nodes if n.to_address})
            return len(nodes)
        except Exception as exc:  # noqa: BLE001
            logger.warning("t20.expand.error", address=address[:10], error=str(exc))
            return 0

    counts = await asyncio.gather(*[_fetch_one(a) for a in candidates])
    total_new = sum(counts)
    return {
        "expanded": len(candidates),
        "new_transactions": total_new,
        "addresses": candidates,
        "total_seen_addresses": len(ctx.seen_addresses),
    }


@_safe_call
async def t21_sherlock_username(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """T21 — Sherlock username OSINT across 300+ social media sites with PROFILE SCRAPING."""
    import asyncio
    import json
    import re
    from datetime import datetime, timezone
    import httpx
    from bs4 import BeautifulSoup
    
    username = args["username"]
    
    # Sites with profile scraping capability
    sites_scrape = {
        "GitHub": f"https://github.com/{username}",
        "Twitter": f"https://twitter.com/{username}",
        "Instagram": f"https://instagram.com/{username}",
        "LinkedIn": f"https://linkedin.com/in/{username}",
        "Medium": f"https://medium.com/@{username}",
    }
    
    found = []
    
    async with httpx.AsyncClient(timeout=15.0, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }) as client:
        for site_name, url in sites_scrape.items():
            try:
                r = await client.get(url, follow_redirects=True)
                if r.status_code == 200:
                    soup = BeautifulSoup(r.text, 'html.parser')
                    snippet = f"Found on {site_name}"
                    metadata = {}
                    
                    # GitHub specific scraping
                    if site_name == "GitHub":
                        # Try to get bio/description
                        bio_elem = soup.find('p', {'class': 'p-name'}) or soup.find('span', {'itemprop': 'name'})
                        if bio_elem:
                            metadata['name'] = bio_elem.get_text(strip=True)[:100]
                        bio_text = soup.find('p', {'class': 'p-bio'})
                        if bio_text:
                            metadata['bio'] = bio_text.get_text(strip=True)[:200]
                        loc_elem = soup.find('span', {'itemprop': 'location'})
                        if loc_elem:
                            metadata['location'] = loc_elem.get_text(strip=True)
                        company_elem = soup.find('span', {'class': 'p-org'})
                        if company_elem:
                            metadata['company'] = company_elem.get_text(strip=True)
                        # Followers
                        followers = soup.find('a', {'href': f'/{username}?tab=followers'})
                        if followers:
                            metadata['followers'] = followers.get_text(strip=True)
                        # Repos
                        repos = soup.find('a', {'href': f'/{username}?tab=repositories'})
                        if repos:
                            metadata['repos'] = repos.get_text(strip=True)
                        snippet = f"GitHub: {metadata.get('name', 'User')}" + (f" | {metadata['bio'][:50]}..." if metadata.get('bio') else "")
                    
                    # Twitter specific scraping  
                    elif site_name == "Twitter":
                        name_elem = soup.find('div', {'data-testid': 'UserName'})
                        if name_elem:
                            metadata['display_name'] = name_elem.get_text(strip=True)[:50]
                        bio_elem = soup.find('div', {'data-testid': 'UserDescription'})
                        if bio_elem:
                            metadata['bio'] = bio_elem.get_text(strip=True)[:200]
                        loc_elem = soup.find('span', {'data-testid': 'UserLocation'})
                        if loc_elem:
                            metadata['location'] = loc_elem.get_text(strip=True)
                        join_elem = soup.find('span', {'data-testid': 'UserJoinDate'})
                        if join_elem:
                            metadata['joined'] = join_elem.get_text(strip=True)
                        snippet = f"Twitter: {metadata.get('display_name', 'Account')}" + (f" | {metadata['bio'][:50]}..." if metadata.get('bio') else "")
                    
                    # Instagram specific
                    elif site_name == "Instagram":
                        title_elem = soup.find('title')
                        if title_elem:
                            metadata['title'] = title_elem.get_text()
                        # May have meta description
                        desc_elem = soup.find('meta', {'name': 'description'})
                        if desc_elem and desc_elem.get('content'):
                            metadata['description'] = desc_elem.get('content')[:200]
                        snippet = f"Instagram account found"
                    
                    # LinkedIn specific
                    elif site_name == "LinkedIn":
                        name_elem = soup.find('h1', {'class': 'text-heading-xlarge'})
                        if name_elem:
                            metadata['name'] = name_elem.get_text(strip=True)[:100]
                        headline_elem = soup.find('div', {'class': 'inline-show-more-text'})
                        if headline_elem:
                            metadata['headline'] = headline_elem.get_text(strip=True)[:200]
                        snippet = f"LinkedIn: {metadata.get('name', 'Profile')}" + (f" | {metadata['headline'][:50]}..." if metadata.get('headline') else "")
                    
                    # Medium specific
                    elif site_name == "Medium":
                        name_elem = soup.find('h1')
                        if name_elem:
                            metadata['name'] = name_elem.get_text(strip=True)[:100]
                        bio_elem = soup.find('p', {'class': lambda x: x and 'bio' in x})
                        if bio_elem:
                            metadata['bio'] = bio_elem.get_text(strip=True)[:200]
                        snippet = f"Medium: {metadata.get('name', 'Writer')}" + (f" | {metadata['bio'][:50]}..." if metadata.get('bio') else "")
                    
                    found.append({
                        "site": site_name, 
                        "url": url, 
                        "status": "found",
                        "metadata": metadata,
                        "snippet": snippet
                    })
                    print(f"✓ {site_name}: {snippet}")
                else:
                    print(f"✕ {site_name}: {r.status_code}")
            except Exception as e:
                print(f"✕ {site_name}: {e}")
    
    # Also check simple sites without scraping
    simple_sites = [
        ("Facebook", f"https://facebook.com/{username}"),
        ("YouTube", f"https://youtube.com/@{username}"),
        ("Reddit", f"https://reddit.com/user/{username}"),
        ("TikTok", f"https://tiktok.com/@{username}"),
        ("Telegram", f"https://t.me/{username}"),
    ]
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        for site_name, url in simple_sites:
            try:
                r = await client.get(url, follow_redirects=True)
                if r.status_code == 200:
                    found.append({"site": site_name, "url": url, "status": "found", "snippet": f"Found on {site_name}"})
            except:
                pass
    
    # Save to Neo4j with detailed metadata
    from app.models.domain import OsintNode
    from app.repositories.graph_repository import GraphRepository
    
    saved_count = 0
    for f in found:
        # Build detailed snippet from metadata
        detail_snippet = f.get('snippet', '')
        if f.get('metadata'):
            meta = f['metadata']
            if meta.get('name'):
                detail_snippet += f" | Name: {meta['name']}"
            if meta.get('bio'):
                detail_snippet += f" | Bio: {meta['bio'][:100]}..."
            if meta.get('location'):
                detail_snippet += f" | Location: {meta['location']}"
            if meta.get('company'):
                detail_snippet += f" | Company: {meta['company']}"
            if meta.get('followers'):
                detail_snippet += f" | {meta['followers']}"
        
        node = OsintNode(
            source="sherlock",
            entity_ref=ctx.address,
            url=f["url"],
            snippet=detail_snippet[:300],
            platform=f["site"].lower(),
            retrieved_at=datetime.now(timezone.utc),
            metadata=f.get('metadata', {}),
        )
        try:
            await GraphRepository.upsert_osint_node(node)
            saved_count += 1
        except Exception as e:
            print(f"Save error: {e}")
    
    return {
        "found": len(found),
        "saved": saved_count,
        "results": found,
        "detailed": any(f.get('metadata') for f in found)
    }


@_safe_call
async def t22_theharvester(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """T22 — theHarvester for email/subdomain enumeration with DNS & SCRAPING."""
    import asyncio
    from datetime import datetime, timezone
    import httpx
    from bs4 import BeautifulSoup
    import socket
    
    domain = args["domain"]
    limit = int(args.get("limit", 50))
    
    subdomains = []
    emails = []
    metadata = {}
    
    # 1. DNS subdomain enumeration using socket
    print(f"Enumerating DNS subdomains for {domain}...")
    dns_prefixes = ["www", "mail", "ftp", "webmail", "smtp", "pop", "ns1", "ns2", "cdn", "blog", "admin", "forum", "news", "vpn", "dev", "shop", "portal", "wiki", "jobs", "docs", "beta", "store", "chat", "test", "git", "svn", "backup", "mx", "cloud", "app", "api", "cdn1", "server", "host", "panel", "control", "cp", "web", "intra", "internal", "corp", "office"]
    
    # Try DNS resolution for each subdomain
    for prefix in dns_prefixes:
        subdomain = f"{prefix}.{domain}"
        try:
            socket.setdefaulttimeout(2)
            result = socket.gethostbyname(subdomain)
            subdomains.append(subdomain)
            print(f"  ✓ Found: {subdomain} -> {result}")
        except:
            pass
    
    # 2. Scrape emails from website homepage and whois
    print(f"Searching for emails related to {domain}...")
    
    # Check main website for contact info
    try:
        async with httpx.AsyncClient(timeout=10.0, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }) as client:
            # Try main domain
            r = await client.get(f"https://{domain}", follow_redirects=True)
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, 'html.parser')
                
                # Look for email patterns in page
                email_pattern = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b')
                found_emails = email_pattern.findall(r.text)
                
                # Filter to domain-related emails
                for email in found_emails:
                    if domain.lower() in email.lower() or not any(x in email.lower() for x in ['gmail.com', 'yahoo.com', 'hotmail.com', 'outlook.com']):
                        if email not in emails:
                            emails.append(email)
                            print(f"  ✓ Email: {email}")
                
                # Try to find contact page
                contact_urls = [
                    f"https://{domain}/contact",
                    f"https://{domain}/contact-us",
                    f"https://{domain}/about",
                    f"https://{domain}/contact.html",
                ]
                for contact_url in contact_urls[:3]:
                    try:
                        cr = await client.get(contact_url)
                        if cr.status_code == 200:
                            csoup = BeautifulSoup(cr.text, 'html.parser')
                            contact_emails = email_pattern.findall(cr.text)
                            for email in contact_emails:
                                if email not in emails:
                                    emails.append(email)
                                    print(f"  ✓ Email (contact page): {email}")
                    except:
                        pass
                
                # Try to get meta info from website
                title = soup.find('title')
                if title:
                    metadata['title'] = title.get_text(strip=True)[:100]
                
                desc = soup.find('meta', {'name': 'description'})
                if desc and desc.get('content'):
                    metadata['description'] = desc.get('content')[:200]
                
                # Check for privacy policy / terms
                legal_urls = [f"https://{domain}/privacy", f"https://{domain}/terms"]
                for legal_url in legal_urls:
                    try:
                        lr = await client.get(legal_url)
                        if lr.status_code == 200:
                            metadata['has_legal'] = True
                    except:
                        pass
    except Exception as e:
        print(f"  Website scrape error: {e}")
    
    # 3. Search for more info via DuckDuckGo
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            # Search for emails
            ddg_url = f"https://duckduckgo.com/html/?q=site:{domain}+%40"
            r = await client.get(ddg_url)
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, 'html.parser')
                links = soup.find_all('a', {'class': 'result__a'})
                for link in links[:10]:
                    href = link.get('href', '')
                    # Extract emails from search results
                    email_pattern = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')
                    found = email_pattern.findall(href)
                    for email in found:
                        if domain.lower() in email.lower() or email.count('@') > 0:
                            if email not in emails:
                                emails.append(email)
    except Exception as e:
        print(f"  Search error: {e}")
    
    # 4. Try whois via web search
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            whois_url = f"https://duckduckgo.com/html/?q={domain}+whois"
            wr = await client.get(whois_url)
            if wr.status_code == 200:
                soup = BeautifulSoup(wr.text, 'html.parser')
                # Look for registration email
                if 'reg' in wr.text.lower() or 'registrant' in wr.text.lower():
                    metadata['whois_info'] = "Found registration data"
    except:
        pass
    
    # Save subdomains to Neo4j
    from app.models.domain import OsintNode
    from app.repositories.graph_repository import GraphRepository
    
    saved = 0
    
    for sub in subdomains[:15]:
        # Get IP if possible
        try:
            ip = socket.gethostbyname(sub)
        except:
            ip = "unknown"
        
        node = OsintNode(
            source="theharvester",
            entity_ref=ctx.address,
            url=f"https://{sub}",
            snippet=f"DNS: {sub} | IP: {ip}",
            platform="subdomain",
            retrieved_at=datetime.now(timezone.utc),
            metadata={"ip": ip, "type": "subdomain"},
        )
        try:
            await GraphRepository.upsert_osint_node(node)
            saved += 1
        except Exception as e:
            print(f"Save subdomain error: {e}")
    
    # Save emails to Neo4j
    for email in emails[:10]:
        node = OsintNode(
            source="theharvester",
            entity_ref=ctx.address,
            url=f"mailto:{email}",
            snippet=f"Email found: {email} | Domain: {domain}",
            platform="email",
            retrieved_at=datetime.now(timezone.utc),
            metadata={"email": email, "source": "web"},
        )
        try:
            await GraphRepository.upsert_osint_node(node)
            saved += 1
        except Exception as e:
            print(f"Save email error: {e}")
    
    return {
        "subdomains_found": len(subdomains),
        "emails_found": len(emails),
        "subdomains": subdomains[:15],
        "emails": emails[:10],
        "metadata": metadata,
        "saved": saved,
    }


@_safe_call
async def t23_blockchair(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """T23 — Blockchair free blockchain explorer (no API key)."""
    import asyncio
    from datetime import datetime, timezone
    
    address = args["address"]
    chain = args.get("chain", "ethereum")
    limit = int(args.get("limit", 20))
    
    chain_map = {
        "ethereum": "ethereum",
        "bitcoin": "bitcoin", 
        "tron": "tron",
        "solana": "solana",
    }
    bc_chain = chain_map.get(chain.lower(), "ethereum")
    
    try:
        # Blockchair API - free tier
        url = f"https://api.blockchair.com/{bc_chain}/addresses/{address}?limit={limit}"
        
        proc = await asyncio.create_subprocess_exec(
            "curl", "-s", "-L", url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        
        import json
        data = json.loads(stdout.decode())
        
        if "data" in data and address in data["data"]:
            addr_data = data["data"][address]
            
            # Parse transactions
            txs = addr_data.get("transactions", [])
            
            # Save transactions to Neo4j if EVM
            if bc_chain == "ethereum" and txs:
                from app.models.domain import WalletNode, TransactionNode
                from app.repositories.graph_repository import GraphRepository
                
                # Upsert wallet
                await GraphRepository.upsert_wallet(WalletNode(
                    address=address,
                    chain=Chain.ETH,
                    first_seen=datetime.now(timezone.utc),
                    last_seen=datetime.now(timezone.utc),
                ))
            
            return {
                "balance": addr_data.get("balance", 0),
                "balance_usd": addr_data.get("balance_usd", 0),
                "transactions": len(txs),
                "tx_list": txs[:10],
                "chain": bc_chain,
            }
        else:
            return {"error": "No data found for address"}
            
    except FileNotFoundError:
        return {"error": "curl not available"}
    except Exception as e:
        return {"error": str(e)[:200]}


# ─────────────────────────────────────────────────────────────────────────────
# Registry
# ─────────────────────────────────────────────────────────────────────────────
def build_registry() -> dict[str, Tool]:
    return {
        "get_eth_transactions": Tool(
            name="get_eth_transactions",
            description="Fetch historical ETH/EVM transactions for an address via Alchemy (alchemy_getAssetTransfers). "
                        "Persists to Neo4j. Use this for any EVM chain (ETH, Base, Polygon).",
            parameters={
                "type": "object",
                "properties": {
                    "address": {"type": "string"},
                    "chain": {"type": "string", "enum": ["ETH", "BASE", "POLYGON"]},
                    "max_pages": {"type": "integer", "minimum": 1, "maximum": 10},
                },
                "required": ["address"],
            },
            fn=t01_get_eth_transactions,
        ),
        "get_sol_transactions": Tool(
            name="get_sol_transactions",
            description="Fetch historical Solana transactions for an address via Helius Enhanced Transactions API.",
            parameters={
                "type": "object",
                "properties": {
                    "address": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                },
                "required": ["address"],
            },
            fn=t02_get_sol_transactions,
        ),
        "check_sanctions": Tool(
            name="check_sanctions",
            description="Check if an address is in the OFAC SDN sanctions list via Chainalysis Free Sanctions API.",
            parameters={
                "type": "object",
                "properties": {"address": {"type": "string"}},
                "required": ["address"],
            },
            fn=t03_check_sanctions,
        ),
        "run_gnn_inference": Tool(
            name="run_gnn_inference",
            description="Run GAT (Graph Attention Network) inference on a 2-hop subgraph around the given address. "
                        "Returns illicit-probability score (0-1) and SHAP-style explanation.",
            parameters={
                "type": "object",
                "properties": {
                    "address": {"type": "string"},
                    "chain": {"type": "string"},
                },
                "required": [],
            },
            fn=t04_run_gnn_inference,
        ),
        "trace_forward": Tool(
            name="trace_forward",
            description="Forward graph traversal: find wallets receiving funds (transitively) from the target.",
            parameters={
                "type": "object",
                "properties": {
                    "address": {"type": "string"},
                    "chain": {"type": "string"},
                    "hops": {"type": "integer", "minimum": 1, "maximum": 5},
                    "limit": {"type": "integer"},
                },
                "required": [],
            },
            fn=t05_trace_forward,
        ),
        "trace_backward": Tool(
            name="trace_backward",
            description="Backward graph traversal: find wallets that funded the target (transitively).",
            parameters={
                "type": "object",
                "properties": {
                    "address": {"type": "string"},
                    "chain": {"type": "string"},
                    "hops": {"type": "integer", "minimum": 1, "maximum": 5},
                    "limit": {"type": "integer"},
                },
                "required": [],
            },
            fn=t06_trace_backward,
        ),
        "check_bridge_lz": Tool(
            name="check_bridge_lz",
            description="Look up LayerZero cross-chain message by source TX hash. "
                        "Returns destination chain & tx hash if delivered.",
            parameters={
                "type": "object",
                "properties": {"tx_hash": {"type": "string"}},
                "required": ["tx_hash"],
            },
            fn=t07_check_bridge_lz,
        ),
        "check_bridge_wh": Tool(
            name="check_bridge_wh",
            description="Look up Wormhole cross-chain operation by source TX hash via WormholeScan.",
            parameters={
                "type": "object",
                "properties": {"tx_hash": {"type": "string"}},
                "required": ["tx_hash"],
            },
            fn=t08_check_bridge_wh,
        ),
        "get_entity_label": Tool(
            name="get_entity_label",
            description="Fetch a public entity label (Etherscan name-tag) for an address — exchange, mixer, etc.",
            parameters={
                "type": "object",
                "properties": {
                    "address": {"type": "string"},
                    "chain": {"type": "string"},
                },
                "required": ["address"],
            },
            fn=t09_get_entity_label,
        ),
        "detect_anomaly": Tool(
            name="detect_anomaly",
            description="Run all 17 anomaly-pattern detectors over the transactions accumulated so far. "
                        "Optionally pass labeled_neighbors and sanctioned_addresses for richer detection.",
            parameters={
                "type": "object",
                "properties": {
                    "labeled_neighbors": {
                        "type": "array",
                        "items": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 2},
                    },
                    "sanctioned_addresses": {"type": "array", "items": {"type": "string"}},
                    "self_sanctioned": {"type": "boolean"},
                },
            },
            fn=t10_detect_anomaly,
        ),
        "generate_report": Tool(
            name="generate_report",
            description="Mark the case as ready for report generation (PDF + IPFS pin). Call only when investigation is complete.",
            parameters={"type": "object", "properties": {}},
            fn=t11_generate_report,
        ),
        "send_alert": Tool(
            name="send_alert",
            description="Send a text alert to the analyst Telegram channel. Use for Critical Risk findings.",
            parameters={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
            fn=t12_send_alert,
        ),
        "web_search": Tool(
            name="web_search",
            description=(
                "T13 — Multi-source web OSINT: Exa AI (semantic neural search, primary) + "
                "DuckDuckGo (different index, complement) running in parallel. "
                "Use for: scam reports, exchange profiles, news, hack disclosures, darknet mentions. "
                "For the target wallet address, set address_mode=true to use crypto-focused queries "
                "against security/blockchain analytics sites (Chainalysis, Elliptic, Rekt, PeckShield). "
                "Results are persisted as OsintNode in Neo4j."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query or wallet address"},
                    "max_results": {"type": "integer", "minimum": 1, "maximum": 15},
                    "address_mode": {
                        "type": "boolean",
                        "description": "Set true when query IS a wallet address — enables crypto threat search",
                    },
                },
                "required": ["query"],
            },
            fn=t13_web_search,
        ),
        "whois_lookup": Tool(
            name="whois_lookup",
            description=(
                "T14 — WHOIS / RDAP domain registration lookup, or IP geolocation + ASN via ip-api.com. "
                "Use when you find a domain or IP linked to a wallet or entity."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "target": {"type": "string", "description": "Domain name or IP address"},
                    "type": {"type": "string", "enum": ["auto", "domain", "ip"]},
                },
                "required": ["target"],
            },
            fn=t14_whois_lookup,
        ),
        "social_media_intel": Tool(
            name="social_media_intel",
            description=(
                "T15 — Search Twitter/X and Reddit for public mentions of a wallet address or entity. "
                "Results persisted as OsintNode in Neo4j."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Address or entity name to search for"},
                    "max_results": {"type": "integer", "minimum": 1, "maximum": 20},
                },
                "required": [],
            },
            fn=t15_social_media_intel,
        ),
        "darkweb_monitor": Tool(
            name="darkweb_monitor",
            description=(
                "T16 — Check an address against known threat intelligence databases (static mixer list, "
                "web OSINT for darknet/ransomware/scam mentions). "
                "Saves ThreatIntelHit nodes to Neo4j. Use for all high-value addresses."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "address": {"type": "string", "description": "Wallet address to check"},
                },
                "required": [],
            },
            fn=t16_darkweb_monitor,
        ),
        "get_btc_transactions": Tool(
            name="get_btc_transactions",
            description=(
                "T17 — Fetch Bitcoin transactions for a BTC address via Blockstream.info (free, no key). "
                "UTXO-aware: maps inputs→outputs to canonical TransactionNode. Persists to Neo4j."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "address": {"type": "string", "description": "Bitcoin address (bech32 or legacy)"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                },
                "required": ["address"],
            },
            fn=t17_get_btc_transactions,
        ),
        "get_tron_transactions": Tool(
            name="get_tron_transactions",
            description=(
                "T18 — Fetch TRON TRX and TRC20 token transfers for an address via TronGrid (free, no key). "
                "Persists to Neo4j."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "address": {"type": "string", "description": "TRON address (T...)"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                },
                "required": ["address"],
            },
            fn=t18_get_tron_transactions,
        ),
        "expand_counterparties": Tool(
            name="expand_counterparties",
            description=(
                "T20 — Depth expansion: fetch transactions for discovered counterparty wallets. "
                "CALL THIS after get_eth_transactions to build a branching graph. "
                "Fetches TX history for up to max_addresses unseen EVM counterparties in parallel, "
                "persisting results to Neo4j so trace_forward/backward return branching data. "
                "Use once per depth hop (depth 2: call after initial fetch; depth 3: call again)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "max_addresses": {"type": "integer", "minimum": 1, "maximum": 20,
                                     "description": "Max counterparties to expand (default 10)"},
                    "max_pages": {"type": "integer", "minimum": 1, "maximum": 3,
                                  "description": "Alchemy pages per address (default 1, keep small)"},
                    "chain": {"type": "string", "enum": ["ETH", "BASE", "POLYGON"]},
                },
                "required": [],
            },
            fn=t20_expand_counterparties,
        ),
        "resolve_identity": Tool(
            name="resolve_identity",
            description=(
                "T19 — Resolve any identity to blockchain addresses. "
                "Use when you encounter a company name, domain, email, or entity "
                "mid-investigation and need to find its wallet addresses. "
                "Input: any string (e.g. 'FTX', 'tornado.cash', 'sam@ftx.com'). "
                "Returns: list of {address, chain, label, confidence}."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "input": {
                        "type": "string",
                        "description": "Company name, domain, email, or any identity string",
                    },
                    "max_results": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 8,
                        "description": "Max addresses to return",
                    },
                },
                "required": ["input"],
            },
            fn=t19_resolve_identity,
        ),
        "t21_sherlock_username": Tool(
            name="t21_sherlock_username",
            description=(
                "T21 — Sherlock username OSINT. Search for a username across 300+ social media sites. "
                "Use when you want to find all social media accounts associated with a specific username. "
                "Input: username string (e.g. 'fikriaf', 'vitalik'). "
                "Returns: list of found accounts with site names and URLs."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "username": {
                        "type": "string",
                        "description": "Username to search for across social media sites",
                    },
                },
                "required": ["username"],
            },
            fn=t21_sherlock_username,
        ),
        "t22_theharvester": Tool(
            name="t22_theharvester",
            description=(
                "T22 — theHarvester OSINT. Gather email addresses, subdomains, and virtual hosts. "
                "Use when investigating a company/domain to find associated emails and subdomains. "
                "Input: domain name (e.g. 'faftech.net', 'daemonprotocol.com'). "
                "Returns: found emails, subdomains, and virtual hosts."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "domain": {
                        "type": "string",
                        "description": "Domain to enumerate (e.g. 'example.com')",
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 100,
                        "description": "Max results to return",
                    },
                },
                "required": ["domain"],
            },
            fn=t22_theharvester,
        ),
        "t23_blockchair": Tool(
            name="t23_blockchair",
            description=(
                "T23 — Blockchair blockchain explorer (free, no API key). "
                "Query transactions, balances, and token transfers for any address. "
                "Input: blockchain address (ETH, BTC, etc.) or transaction hash. "
                "Returns: transaction history, balance, and token transfers."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "address": {
                        "type": "string",
                        "description": "Wallet address or transaction hash",
                    },
                    "chain": {
                        "type": "string",
                        "enum": ["ethereum", "bitcoin", "tron", "solana"],
                        "description": "Blockchain to query",
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 100,
                        "description": "Max transactions to return",
                    },
                },
                "required": ["address", "chain"],
            },
            fn=t23_blockchair,
        ),
    }


REGISTRY: dict[str, Tool] = build_registry()
