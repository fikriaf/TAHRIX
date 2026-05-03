"""Tahrix Agent - AI Assistant API (non-streaming)."""

from __future__ import annotations

import json
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.models.sql import InvestigationCase, User
from app.models.enums import Chain
from app.repositories.graph_repository import GraphRepository
from app.api.v1.dependencies import get_current_user
from app.api.v1.dependencies import get_db
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/agent", tags=["agent"])


class AgentChatRequest(BaseModel):
    message: str
    case_id: str | None = None


class AgentChatResponse(BaseModel):
    response: str
    sources: list[dict[str, Any]] | None = None


SYSTEM_PROMPT = """You are TAHRIX Agent, an AI assistant for blockchain crime investigation.

You have access to:
- Current case data (address, chain, risk score, GNN, anomalies, sanctions)
- Graph data (nodes, edges, relationships)
- Investigation events and logs
- Label/intel database
- All tool capabilities

Guidelines:
- Answer questions about the current investigation
- Provide insights from graph data and risk analysis
- Explain what tools can be used
- Summarize findings clearly
- Use markdown for formatting
- If you need to run a tool, explain what you'd do
- Be concise but thorough"""


@router.post("/chat", response_model=AgentChatResponse)
async def agent_chat(
    body: AgentChatRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> AgentChatResponse:
    """Chat with Tahrix Agent AI assistant."""
    from app.agent.llm import get_llm
    from app.agent.tools import REGISTRY, ToolContext
    
    # Get case context
    case = None
    subgraph = None
    
    if body.case_id:
        try:
            case_id_uuid = uuid.UUID(body.case_id)
            case = await db.get(InvestigationCase, case_id_uuid)
            if case:
                chain = Chain(case.input_chain) if case.input_chain else Chain.ETH
                subgraph = await GraphRepository.get_subgraph(
                    address=case.input_address,
                    chain=chain,
                    max_hops=case.depth or 3,
                )
        except ValueError:
            pass

    # Build context messages
    context_messages = []
    
    # Add case context
    if case:
        context = f"""Current Case:
- Address: {case.input_address}
- Chain: {case.input_chain}
- Status: {case.status}
- Risk Score: {case.risk_score or '—'}/100
- Risk Grade: {case.risk_grade or '—'}
- GNN Score: {case.gnn_score or '—'}
- Anomalies: {', '.join(case.anomaly_codes) if case.anomaly_codes else 'None'}
- Sanctions: {'HIT' if case.sanctions_hit else 'Clear'}
- Iterations: {case.iterations or 0}
- Summary: {case.summary or 'No summary'}"""

        if subgraph:
            nodes = subgraph.get("nodes", [])
            edges = subgraph.get("edges", [])
            context += f"\n\nGraph: {len(nodes)} nodes, {len(edges)} edges"
            
            node_types = {}
            for n in nodes:
                t = n.get("node_type") or n.get("type", "Unknown")
                node_types[t] = node_types.get(t, 0) + 1
            context += f"\nNode Types: {node_types}"

        context_messages.append({"role": "system", "content": context})

    context_messages.append({"role": "system", "content": SYSTEM_PROMPT})
    context_messages.append({"role": "user", "content": body.message})

    # Add tool definitions
    tools_schema = []
    for name, tool in REGISTRY.items():
        if hasattr(tool, "json_schema"):
            tools_schema.append({
                "type": "function",
                "function": {
                    "name": name,
                    "description": tool.description or f"Tool {name}",
                    "parameters": tool.json_schema,
                },
            })

    try:
        llm = get_llm()
        
        response = await llm.chat(
            messages=context_messages,
            tools=tools_schema if tools_schema else None,
            tool_choice="auto" if tools_schema else None,
            temperature=0.7,
            max_tokens=2000,
        )
        
        final_response = response.content or "No response from AI."
        
        # If tool calls, execute and add to context
        if response.tool_calls:
            for tc in response.tool_calls:
                tool_name = tc.name
                tool_args = tc.arguments
                tool_func = REGISTRY.get(tool_name)
                
                if tool_func:
                    ctx = ToolContext(
                        case_id=str(case.id) if case else "agent",
                        address=case.input_address if case else "unknown",
                        chain="ETH",
                        seen_addresses=set(),
                        transactions=[],
                        bridge_events=[],
                        anomaly_flags=[],
                    )
                    
                    try:
                        result = await tool_func(tool_args, ctx)
                        result_str = json.dumps(result)[:1000] if result else "No result"
                    except Exception as te:
                        result_str = f"Error: {str(te)}"
                    
                    context_messages.append({
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [{
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(tc.arguments),
                            },
                        }],
                    })
                    context_messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result_str,
                    })
            
            # Get final response after tool execution
            final_resp = await llm.chat(
                messages=context_messages,
                temperature=0.7,
                max_tokens=2000,
            )
            final_response = final_resp.content or "Tool executed but no final response."

        return AgentChatResponse(response=final_response, sources=None)
        
    except Exception as e:
        return AgentChatResponse(response=f"Error: {str(e)}", sources=None)