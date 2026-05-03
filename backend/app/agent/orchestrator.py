"""Agent Orchestrator — Cognitive Reasoning Loop (THINK → ACT → OBSERVE → REFLECT).

The orchestrator drives an LLM through repeated tool calls. Each iteration:
  • THINK : prompt the LLM with current evidence + memory; expect tool calls
  • ACT   : execute the requested tool(s)
  • OBSERVE: append tool results back into the conversation
  • REFLECT: ask the LLM (briefly) whether to continue or stop

Stopping criteria:
  • LLM responds with no tool call AND content (final analysis)
  • Iteration count ≥ INVESTIGATION_MAX_ITERATIONS
  • Hypothesis confidence ≥ INVESTIGATION_CONFIDENCE_THRESHOLD
  • Critical sanctions hit (immediate stop)
"""

from __future__ import annotations

import json
import time
from typing import Any, Awaitable, Callable
from uuid import UUID

from app.agent.hypothesis import HypothesisManager
from app.agent.llm import LLMResponse, get_llm
from app.agent.memory import AgentMemory
from app.agent.tools import REGISTRY, ToolContext
from app.core.config import settings
from app.core.logging import get_logger
from app.models.enums import Chain

logger = get_logger(__name__)

# Callback type: receives a single event dict, returns None
OnEventCallback = Callable[[dict[str, Any]], Awaitable[None]]


SYSTEM_PROMPT = """You are TAHRIX, an autonomous blockchain crime investigator.

Your job: investigate a wallet address by orchestrating tools to gather evidence,
detect suspicious patterns, run GNN inference, and arrive at a Risk Assessment.

Always follow the cognitive loop: THINK about what's missing → call ONE OR MORE
TOOLS to fill the gap → OBSERVE the results → REFLECT and continue or stop.

── TOOL REFERENCE ──────────────────────────────────────────────────────────────
CHAIN INTELLIGENCE (on-chain data):
  get_eth_transactions   — ETH/EVM TX history (Alchemy). Use for ETH, BASE, POLYGON, BNB, ARB.
  get_sol_transactions   — Solana TX history (Helius).
  get_btc_transactions   — Bitcoin UTXO TX history (Blockstream, free). Use for BTC addresses.
  get_tron_transactions  — TRON TRX + TRC20 transfers (TronGrid, free). Use for T... addresses.
  resolve_identity       — T19: resolve company/domain/email/name → wallet addresses via Exa.
                           Use mid-investigation when you discover a new entity name.
  trace_forward          — Forward graph traversal: who received funds FROM the target?
  trace_backward         — Backward graph traversal: who SENT funds TO the target?
  expand_counterparties  — T20: DEPTH EXPANSION. Fetches TX history for discovered counterparty
                           wallets in parallel, branching the graph to the next hop level.
                           Call AFTER get_eth_transactions at each depth level.
  get_entity_label       — Etherscan name-tag: exchange, mixer, darknet? (EVM chains only)
  check_bridge_lz        — LayerZero cross-chain message lookup by TX hash.
  check_bridge_wh        — Wormhole cross-chain operation lookup by TX hash.

RISK SIGNALS:
  check_sanctions        — OFAC SDN sanctions check (Chainalysis). ALWAYS call first.
  detect_anomaly         — Run all 17 pattern detectors (P01-P17) over accumulated TXs.
  run_gnn_inference      — Graph Attention Network illicit-probability score (0-1) + SHAP.
  darkweb_monitor        — T16: check address against threat intel DB + darkweb OSINT.

OPEN-SOURCE INTELLIGENCE (OSINT):
  web_search             — T13: DuckDuckGo search for scam reports, news, exchange profiles.
  whois_lookup           — T14: RDAP domain WHOIS or ip-api.com IP geolocation + ASN.
  social_media_intel     — T15: Twitter/X + Reddit public mentions of address or entity.
  sherlock_username      — T21: Search username across 300+ social media sites (e.g. 'fikriaf').
  theharvester           — T22: Find emails & subdomains for a domain (e.g. 'example.com').
  blockchair             — T23: Free blockchain explorer (no API key) - query ETH/BTC/Tron addresses.

OUTPUT:
  generate_report        — Mark case ready for PDF report + IPFS pin. Call LAST.
  send_alert             — Telegram alert to analyst. Call only for CRITICAL risk.

── INVESTIGATIVE PLAYBOOK ───────────────────────────────────────────────────────
Always adapt to evidence, but follow this general order:
  1. check_sanctions — if hit, stop immediately and escalate.
  2. get_eth_transactions / get_sol_transactions / get_btc_transactions / get_tron_transactions
     — pull TX history for the correct chain.
  3. expand_counterparties — IMPORTANT: call this after step 2 to fetch TX for discovered
     counterparties (depth 2). For depth ≥ 3, call again to expand one more hop.
  4. trace_forward + trace_backward — map counterparty network (2-3 hops).
  5. get_entity_label on top counterparties — identify exchanges, mixers, darknet.
  6. check_bridge_lz / check_bridge_wh — follow cross-chain hops.
  7. darkweb_monitor — check threat intel for any high-value address.
  8. web_search / social_media_intel — OSINT on suspicious entities found.
  9. detect_anomaly — run all 17 patterns over all accumulated data.
  10. run_gnn_inference — get final ML illicit-probability score.
  11. send_alert if CRITICAL. Then generate_report.

── FINAL ANSWER FORMAT ──────────────────────────────────────────────────────────
IMPORTANT: After running your investigation tools, you MUST provide a final analysis.
STOP calling tools and respond with a comprehensive report including:
  • Risk verdict: LOW | MEDIUM | HIGH | CRITICAL
  • Evidence summary: what you found (transactions, OSINT, anomalies, GNN score)
  • Threat assessment: specific concerns, indicators, patterns
  • Confidence: 0.0–1.0
  • Recommended action: what the analyst should do next
  • Key data: include numbers (e.g., "86 OSINT mentions found", "3 counterparty addresses")
Do NOT just say "low risk" — explain WHY with specific findings.

Efficiency rules:
  • Never call the same tool twice with identical parameters.
  • For BTC addresses (start with 1, 3, or bc1), use get_btc_transactions.
  • For TRON addresses (start with T), use get_tron_transactions.
  • For EVM addresses (0x...), use get_eth_transactions.
  • For Solana addresses (base58, 32–44 chars), use get_sol_transactions.
  • If you encounter a company/entity name mid-investigation, use resolve_identity first."""


class AgentOrchestrator:
    def __init__(self, *, case_id: str, address: str, chain: Chain, depth: int = 3, is_osint_only: bool = False) -> None:
        self.case_id = case_id
        self.address = address
        self.chain = chain
        self.depth = depth
        self.is_osint_only = is_osint_only
        self.memory = AgentMemory(case_id=case_id)
        self.hypotheses = HypothesisManager()
        self.tool_ctx = ToolContext(
            case_id=case_id, address=address, chain=chain,
            seen_addresses={address}, transactions=[],
            bridge_events=[], anomaly_flags=[],
        )
        self._llm = get_llm()
        
        # Different initial prompt for OSINT-only entities
        if is_osint_only:
            initial_msg = (
                f"Case ID: {case_id}\n"
                f"Target entity: {address} (OSINT-only, NOT a wallet address)\n"
                f"Investigation depth: {depth} hops max\n\n"
                f"IMPORTANT: This is an OSINT-only investigation. The target is a company/entity name, "
                f"not a blockchain wallet. When calling tools, ALWAYS use the FULL entity name - "
                f"DO NOT truncate or shorten the name. For example, if target is 'Fikri Armia Fahmi', "
                f"use 'Fikri Armia Fahmi' NOT 'Fikri Armi'.\n\n"
                f"Use these specialized OSINT tools for better results:\n"
                f"1. sherlock_username - Search '{address}' across 300+ social media sites\n"
                f"2. theharvester - Find emails & subdomains for domains you discover\n"
                f"3. blockchair - Query blockchain data for any wallet addresses found\n"
                f"4. web_search - Find scam reports, news, exchange profiles\n"
                f"5. resolve_identity - Find associated wallet addresses\n\n"
                f"Begin the OSINT investigation now."
            )
        else:
            initial_msg = (
                f"Case ID: {case_id}\n"
                f"Target address: {address} on chain {chain.value}\n"
                f"Investigation depth: {depth} hops max\n"
                f"Begin the investigation."
            )
        
        self._messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": initial_msg},
        ]
        # Critical-stop marker: set when sanctions confirm hit.
        self._critical_stop = False

    @property
    def tools_schema(self) -> list[dict[str, Any]]:
        return [t.to_openai_schema() for t in REGISTRY.values()]

    async def run(
        self,
        *,
        max_iterations: int | None = None,
        on_event: OnEventCallback | None = None,
    ) -> dict[str, Any]:
        """Run the cognitive loop.

        Args:
            max_iterations: Override the config max iterations.
            on_event: Optional async callback fired after EVERY step
                      (THINK start, each ACT result, REFLECT final).
                      Used by investigation_runner to publish live SSE events.
        """
        max_iters = max_iterations or settings.investigation_max_iterations
        iteration = 0
        events: list[dict[str, Any]] = []
        final_text: str | None = None

        async def _emit(event: dict[str, Any]) -> None:
            """Append to local list and fire callback if set."""
            events.append(event)
            if on_event is not None:
                try:
                    await on_event(event)
                except Exception:  # noqa: BLE001
                    pass  # never let callback failure break the agent

        # Seed: an initial hypothesis to drive direction.
        self.hypotheses.add(
            f"Wallet {self.address[:10]}… is involved in illicit activity",
            initial_confidence=0.4,
        )

        # Emit investigation start
        await _emit({
            "type": "status",
            "phase": "START",
            "iteration": 0,
            "max_iterations": max_iters,
            "address": self.address,
            "chain": self.chain.value,
            "confidence": self.hypotheses.max_confidence(),
        })

        while iteration < max_iters:
            iteration += 1
            t0 = time.perf_counter()

            # THINK — emit before LLM call
            await _emit({
                "type": "think",
                "phase": "THINK",
                "iteration": iteration,
                "confidence": self.hypotheses.max_confidence(),
            })

            think_msg = {"role": "user", "content": f"[Iteration {iteration}/{max_iters}] "
                          f"Continue. Current top hypothesis confidence: "
                          f"{self.hypotheses.max_confidence():.2f}"} \
                if iteration > 1 else None
            if think_msg:
                self._messages.append(think_msg)

            response: LLMResponse = await self._llm.chat(
                self._messages, tools=self.tools_schema, tool_choice="auto",
            )

            # If the LLM returned a final text answer, we're done.
            if not response.tool_calls and response.content:
                final_text = response.content.strip()
                ev = {
                    "type": "reflect",
                    "iteration": iteration, "phase": "REFLECT",
                    "tool": None,
                    "result": {"final": final_text, "usage": response.usage},
                    "duration_ms": int((time.perf_counter() - t0) * 1000),
                }
                await _emit(ev)
                break

            # ACT + OBSERVE
            self._messages.append({
                "role": "assistant",
                "content": response.content or "",
                "tool_calls": [
                    {"id": tc.id, "type": "function",
                     "function": {"name": tc.name,
                                  "arguments": json.dumps(tc.arguments)}}
                    for tc in response.tool_calls
                ],
            })

            for tc in response.tool_calls:
                tool = REGISTRY.get(tc.name)

                # Emit ACT (tool starting)
                await _emit({
                    "type": "act",
                    "phase": "ACT",
                    "iteration": iteration,
                    "tool": tc.name,
                    "payload": tc.arguments,
                })

                if not tool:
                    result = {"error": "unknown_tool", "name": tc.name}
                else:
                    logger.info("agent.tool.exec", iteration=iteration,
                                tool=tc.name, args=tc.arguments)
                    result = await tool.fn(tc.arguments, self.tool_ctx)

                self._messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "name": tc.name,
                    "content": json.dumps(result, default=str)[:4000],
                })

                # REFLECT — react to specific signals
                self._reflect_on_tool(tc.name, tc.arguments, result)

                # Emit OBSERVE (tool result)
                ev = {
                    "type": "observe",
                    "phase": "ACT",
                    "iteration": iteration,
                    "tool": tc.name,
                    "payload": tc.arguments,
                    "result": _truncate_for_log(result),
                    "duration_ms": int((time.perf_counter() - t0) * 1000),
                    "confidence": self.hypotheses.max_confidence(),
                }
                await _emit(ev)

                if self._critical_stop:
                    final_text = ("CRITICAL: address matches OFAC sanctions list. "
                                  "Investigation halted; immediate compliance escalation required.")
                    await _emit({
                        "type": "status",
                        "phase": "CRITICAL_STOP",
                        "iteration": iteration,
                        "confidence": 1.0,
                        "message": final_text,
                    })
                    break

            if self._critical_stop:
                break

            # Hypothesis-based stopping
            if self.hypotheses.max_confidence() >= settings.investigation_confidence_threshold:
                logger.info("agent.stop.confidence",
                            confidence=self.hypotheses.max_confidence())
                await _emit({
                    "type": "status",
                    "phase": "CONFIDENCE_STOP",
                    "iteration": iteration,
                    "confidence": self.hypotheses.max_confidence(),
                })
                break

        # If no final_text was provided by LLM (it kept calling tools), force a final analysis
        if not final_text:
            logger.info("agent.no_final_text", iteration=iteration)
            await _emit({
                "type": "status",
                "phase": "GENERATING_FINAL",
                "iteration": iteration,
            })
            
            # Build comprehensive summary from collected data
            tx_count = len(self.tool_ctx.transactions)
            anom_count = len(self.tool_ctx.anomaly_flags)
            anom_codes = [f.code.value for f in self.tool_ctx.anomaly_flags]
            bridge_count = len(self.tool_ctx.bridge_events)
            
# Get OSINT count from memory/context
            osint_hits = 0
            for msg in self._messages:
                if msg.get("role") == "tool" and msg.get("name") in ["web_search", "social_media_intel", "sherlock_username", "theharvester"]:
                    result = msg.get("content", "")
                    if "found" in result.lower() or "results" in result.lower():
                        osint_hits += 1
            
            final_prompt = {
                "role": "user",
                "content": f"""INVESTIGATION COMPLETE — Provide final risk assessment.

TARGET: {self.address} ({self.chain.value})

EVIDENCE COLLECTED:
- Transactions analyzed: {tx_count}
- Anomaly patterns detected: {anom_codes if anom_codes else 'None'}
- Bridge/cross-chain events: {bridge_count}
- OSINT searches performed: {osint_hits}

Based on ALL tool results from this investigation, provide your final analysis with:
1. Risk verdict: LOW | MEDIUM | HIGH | CRITICAL
2. Evidence summary: What you found (transactions, counterparty behavior, OSINT, threat intel)
3. Key findings: Specific numbers, suspicious patterns, red flags
4. Confidence: 0.0-1.0 with reasoning
5. Recommended action: What should the analyst do next?

IMPORTANT: Include specific numbers and details from the evidence — do not give generic answers."""
            }
            self._messages.append(final_prompt)
            response: LLMResponse = await self._llm.chat(
                self._messages, tools=None, tool_choice=None,
            )
            if response.content:
                final_text = response.content.strip()
                
                # Score audit FIRST - validate score before final
                audit_prompt = {
                    "role": "user",
                    "content": f"""SCORE AUDIT — Validate and correct risk score.

TARGET: {self.address} ({self.chain.value})

EVIDENCE FROM INVESTIGATION:
- Transactions: {tx_count} analyzed
- Anomaly patterns: {anom_codes if anom_codes else 'None'}
- Bridge/cross-chain: {bridge_count} events
- OSINT searches: {osint_hits} performed

Your analysis:
{final_text[:1000] if final_text else "No analysis"}

Now validate the risk score. Provide ONLY JSON:

```json
{{
  "score_valid": true/false,
  "risk_verdict": "LOW|MEDIUM|HIGH|CRITICAL",
  "risk_score": 0-100,
  "score_revision_reason": "If score_valid=false, explain why"
}}
```

Rules:
- Sanctions/OFAC/mixer → CRITICAL (80-100)
- If analysis says CRITICAL but score is low → score_valid=false
- Only output JSON"""
                }
                self._messages.append(audit_prompt)
                audit_response: LLMResponse = await self._llm.chat(
                    self._messages, tools=None, tool_choice=None,
                )
                
                # Emit FINAL with validated score
                await _emit({
                    "type": "reflect",
                    "iteration": iteration,
                    "phase": "FINAL",
                    "tool": None,
                    "result": {
                        "final": final_text,
                        "audit": audit_response.content.strip() if audit_response.content else None,
                    },
                })

        await self.memory.save()

        # Emit done sentinel
        await _emit({
            "type": "done",
            "phase": "DONE",
            "iterations": iteration,
            "final_text": final_text,
        })

        return {
            "case_id": self.case_id,
            "iterations": iteration,
            "final_text": final_text,
            "events": events,
            "hypotheses": self.hypotheses.to_list(),
            "transactions_collected": len(self.tool_ctx.transactions),
            "anomaly_flags": [f.model_dump(mode="json") for f in self.tool_ctx.anomaly_flags],
            "bridge_events": [b.model_dump(mode="json") for b in self.tool_ctx.bridge_events],
        }

    # ─────────────────────────────────────────────────────────────────────
    def _reflect_on_tool(self, name: str, args: dict, result: dict) -> None:
        """Post-process tool result and update hypotheses / critical flags."""
        if not result or not isinstance(result, dict):
            return

        if name == "check_sanctions" and result.get("sanctioned"):
            self._critical_stop = True
            for h in self.hypotheses.all():
                h.update(support=1.0, note_for="OFAC sanctions hit")
            return

        if name == "run_gnn_inference":
            score = float(result.get("score", 0.0) or 0.0)
            for h in self.hypotheses.all():
                h.update(support=score, conflict=1.0 - score,
                         note_for=f"GNN={score:.2f}")

        if name == "detect_anomaly":
            n = int(result.get("count", 0) or 0)
            if n:
                for h in self.hypotheses.all():
                    h.update(support=min(0.5, 0.1 * n),
                             note_for=f"{n} anomaly flags")

        if name in {"check_bridge_lz", "check_bridge_wh"}:
            n = int(result.get("count", 0) or 0)
            if n:
                for h in self.hypotheses.all():
                    h.update(support=0.1, note_for=f"{n} bridge events")

        if name == "darkweb_monitor":
            max_sev = float(result.get("max_severity", 0.0) or 0.0)
            if max_sev > 0.5:
                for h in self.hypotheses.all():
                    h.update(support=max_sev, note_for=f"threat_intel sev={max_sev:.2f}")

        if name in {"web_search", "social_media_intel"}:
            count = int(result.get("count", 0) or 0)
            if count:
                for h in self.hypotheses.all():
                    h.update(support=0.05, note_for=f"osint {name} {count} hits")


def _truncate_for_log(obj: Any, max_len: int = 800) -> Any:
    s = json.dumps(obj, default=str)
    if len(s) <= max_len:
        return obj
    # Preserve scalar summary fields so downstream signal extraction still works
    # even when the full result (threats list, results list) is dropped.
    preserved: dict[str, Any] = {"_truncated": True, "preview": s[:max_len]}
    if isinstance(obj, dict):
        for key in ("count", "max_severity", "threat_hits", "score", "label",
                    "sanctioned", "expanded", "new_transactions", "total_seen_addresses"):
            if key in obj:
                preserved[key] = obj[key]
        # Keep the first threat entry so severity is recoverable
        if "threats" in obj and isinstance(obj["threats"], list) and obj["threats"]:
            preserved["threats"] = obj["threats"][:3]  # keep first 3
        # Keep full results for web_search so sanctions detection works
        if "results" in obj and isinstance(obj["results"], list) and obj["results"]:
            preserved["results"] = obj["results"][:10]  # keep first 10
        if "max_severity" not in preserved and "threats" in obj:
            # compute max_severity if not already provided
            sevs = [t.get("severity", 0) for t in (obj.get("threats") or []) if isinstance(t, dict)]
            if sevs:
                preserved["max_severity"] = max(sevs)
    return preserved
