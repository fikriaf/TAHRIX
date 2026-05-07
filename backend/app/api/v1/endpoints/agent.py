"""Tahrix Agent - AI Assistant API (streaming + non-streaming)."""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
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
    history: list[dict[str, str]] | None = None  # Conversational memory


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


def _estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token for mixed text."""
    return max(1, len(text) // 4)


async def _build_chat_context(
    body: AgentChatRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> tuple[list[dict[str, Any]], Any | None, dict[str, Any]]:
    """Build message context for agent chat. Returns (messages, case, meta).
    
    If history exists (conversational mode), skip case context injection.
    Case context only injected for first message in a session.
    """
    context_messages: list[dict[str, Any]] = []
    meta: dict[str, Any] = {"has_context": False, "history_turns": len(body.history or [])}
    
    # If history exists, this is a follow-up message - use conversational memory
    if body.history:
        # Add system prompt for continuity
        context_messages.append({
            "role": "system", 
            "content": SYSTEM_PROMPT + "\n\nContinue the conversation based on previous context."
        })
        # Add previous conversation
        for h in body.history[-10:]:  # Keep last 10 turns to manage token usage
            if h.get("role") in ("user", "assistant"):
                context_messages.append({"role": h["role"], "content": h["content"]})
        # Add current message
        context_messages.append({"role": "user", "content": body.message})
        
        # Estimate tokens
        input_text = "".join(m.get("content", "") for m in context_messages)
        meta["input_tokens_est"] = _estimate_tokens(input_text)
        return context_messages, None, meta
    
    # First message - inject full case context
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

        node_count = 0
        edge_count = 0
        if subgraph:
            nodes = subgraph.get("nodes", [])
            edges = subgraph.get("edges", [])
            node_count = len(nodes)
            edge_count = len(edges)
            context += f"\n\nGraph: {node_count} nodes, {edge_count} edges"
            node_types = {}
            for n in nodes:
                t = n.get("node_type") or n.get("type", "Unknown")
                node_types[t] = node_types.get(t, 0) + 1
            context += f"\nNode Types: {node_types}"

        context_messages.append({"role": "system", "content": context})
        meta.update({
            "has_context": True,
            "address": case.input_address,
            "chain": case.input_chain,
            "risk_score": case.risk_score,
            "risk_grade": case.risk_grade,
            "nodes": node_count,
            "edges": edge_count,
        })

    context_messages.append({"role": "system", "content": SYSTEM_PROMPT})
    context_messages.append({"role": "user", "content": body.message})

    # Estimate input tokens from all message content
    input_text = "".join(m.get("content", "") for m in context_messages)
    meta["input_tokens_est"] = _estimate_tokens(input_text)
    return context_messages, case, meta


@router.post("/chat", response_model=AgentChatResponse)
async def agent_chat(
    body: AgentChatRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> AgentChatResponse:
    """Chat with Tahrix Agent AI assistant (non-streaming)."""
    from app.agent.llm import get_llm
    from app.agent.tools import REGISTRY, ToolContext

    context_messages, case, _meta = await _build_chat_context(body, db)

    tools_schema = []
    for name, tool in REGISTRY.items():
        try:
            tools_schema.append(tool.to_openai_schema())
        except Exception:
            pass

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
                        result = await tool_func.fn(tool_args, ctx)
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

            final_resp = await llm.chat(
                messages=context_messages,
                temperature=0.7,
                max_tokens=2000,
            )
            final_response = final_resp.content or "Tool executed but no final response."

        return AgentChatResponse(response=final_response, sources=None)

    except Exception as e:
        return AgentChatResponse(response=f"Error: {str(e)}", sources=None)


# ── Polling-based chat (works behind free reverse proxies with short timeouts) ──

import uuid as _uuid

from fastapi import HTTPException
from app.db.redis import cache_get_json, cache_set_json


async def _run_chat_job(
    job_id: str,
    messages: list[dict[str, Any]],
    meta: dict[str, Any],
) -> None:
    """Background coroutine: call LLM and store result in Redis."""
    from app.agent.llm import get_llm
    await cache_set_json(
        f"chatjob:{job_id}",
        {"status": "pending", "meta": meta},
        ttl_seconds=120,
    )
    try:
        llm = get_llm()
        response = await llm.chat(
            messages=messages,
            temperature=0.7,
            max_tokens=1500,
        )
        text = response.content or "No response from AI."
        output_tokens = _estimate_tokens(text)
        await cache_set_json(
            f"chatjob:{job_id}",
            {
                "status": "done",
                "response": text,
                "meta": {**meta, "output_tokens_est": output_tokens},
            },
            ttl_seconds=120,
        )
    except Exception as exc:
        await cache_set_json(
            f"chatjob:{job_id}",
            {
                "status": "error",
                "response": f"Error: {exc}",
                "meta": meta,
            },
            ttl_seconds=120,
        )


class ChatJobResponse(BaseModel):
    job_id: str
    meta: dict[str, Any] | None = None


class ChatJobStatus(BaseModel):
    status: str
    response: str | None = None
    meta: dict[str, Any] | None = None


@router.post("/chat-job", response_model=ChatJobResponse)
async def agent_chat_job(
    body: AgentChatRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> ChatJobResponse:
    """Start a chat job in the background; returns a job_id to poll."""
    context_messages, _case, meta = await _build_chat_context(body, db)
    job_id = str(_uuid.uuid4())
    # Store pending immediately so first poll never 404s
    await cache_set_json(
        f"chatjob:{job_id}",
        {"status": "pending", "meta": meta},
        ttl_seconds=120,
    )
    # Launch LLM call in background
    asyncio.create_task(_run_chat_job(job_id, context_messages, meta))
    return ChatJobResponse(job_id=job_id, meta=meta)


@router.get("/chat-job/{job_id}", response_model=ChatJobStatus)
async def agent_chat_job_status(job_id: str) -> ChatJobStatus:
    """Poll for chat job status / result."""
    data = await cache_get_json(f"chatjob:{job_id}")
    if data is None:
        raise HTTPException(status_code=404, detail="Job not found or expired")
    return ChatJobStatus(
        status=data.get("status", "unknown"),
        response=data.get("response"),
        meta=data.get("meta"),
    )


# ── Hybrid Streaming: background LLM stream + Redis chunks + poll endpoint ────

async def _run_stream_job(
    job_id: str,
    messages: list[dict[str, Any]],
    meta: dict[str, Any],
    tools_schema: list[dict[str, Any]] | None,
    case: Any,
) -> None:
    """Background coroutine: stream LLM response, store incremental chunks in Redis."""
    from app.agent.llm import get_llm
    from app.agent.tools import REGISTRY, ToolContext

    job_key = f"chatjob:{job_id}"
    full_content = ""
    full_reasoning = ""
    tool_calls_executed: list[dict[str, Any]] = []

    # Initial state
    state: dict[str, Any] = {
        "status": "streaming",
        "meta": meta,
        "chunks": [],          # list of {type, text} for incremental rendering
        "tool_calls": [],      # list of {name, status}
        "content": "",
        "reasoning": "",
        "usage": None,
    }
    await cache_set_json(job_key, state, ttl_seconds=180)

    def _push_chunk(chunk_type: str, data: dict[str, Any]):
        """Add a chunk and update Redis."""
        nonlocal state
        state["chunks"].append({"type": chunk_type, **data})
        # Keep only last 50 chunks to limit Redis payload size
        if len(state["chunks"]) > 50:
            state["chunks"] = state["chunks"][-50:]

    try:
        llm = get_llm()

        async for event in llm.chat_stream(
            messages=messages,
            tools=tools_schema,
            tool_choice="auto" if tools_schema else None,
            temperature=0.7,
            max_tokens=2000,
        ):
            evt_type = event.get("type")

            if evt_type == "reasoning":
                full_reasoning += event["text"]
                _push_chunk("reasoning", {"text": event["text"]})

            elif evt_type == "content":
                full_content += event["text"]
                _push_chunk("content", {"text": event["text"]})

            elif evt_type == "tool_call":
                tool_name = event["tool_name"]
                tool_args = event["tool_args"]
                tool_func = REGISTRY.get(tool_name)

                _push_chunk("tool_call", {"name": tool_name, "args": tool_args})
                state["tool_calls"].append({"name": tool_name, "status": "running"})

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
                        result = await tool_func.fn(tool_args, ctx)
                        result_str = json.dumps(result)[:1000] if result else "No result"
                    except Exception as te:
                        result_str = f"Error: {str(te)}"

                    _push_chunk("tool_result", {"name": tool_name, "result": result_str})
                    # Update tool status
                    for tc in state["tool_calls"]:
                        if tc["name"] == tool_name and tc["status"] == "running":
                            tc["status"] = "done"
                    tool_calls_executed.append({
                        "name": tool_name,
                        "args": tool_args,
                        "result": result_str,
                    })

                # Persist intermediate state
                state["content"] = full_content
                state["reasoning"] = full_reasoning
                await cache_set_json(job_key, state, ttl_seconds=180)

            elif evt_type == "done":
                usage = event.get("usage")

                # If tool calls were executed, do follow-up LLM call
                if tool_calls_executed:
                    for tc_exec in tool_calls_executed:
                        messages.append({
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [{
                                "id": "tc_" + tc_exec["name"],
                                "type": "function",
                                "function": {
                                    "name": tc_exec["name"],
                                    "arguments": json.dumps(tc_exec["args"]),
                                },
                            }],
                        })
                        messages.append({
                            "role": "tool",
                            "tool_call_id": "tc_" + tc_exec["name"],
                            "content": tc_exec["result"],
                        })

                    # Reset content — first call's content was pre-tool planning,
                    # the follow-up should synthesize tool results as the final answer
                    full_content = ""
                    full_reasoning = ""
                    _push_chunk("follow_up", {"text": "Synthesizing results..."})

                    # Add instruction so model doesn't repeat previous content
                    messages.append({
                        "role": "user",
                        "content": "Based on the tool results above, provide your final analysis. Do NOT repeat your earlier assessment — synthesize the new findings from the tools.",
                    })

                    # Stream follow-up
                    async for follow_event in llm.chat_stream(
                        messages=messages,
                        temperature=0.7,
                        max_tokens=1500,
                    ):
                        ft = follow_event.get("type")
                        if ft == "reasoning":
                            full_reasoning += follow_event["text"]
                            _push_chunk("reasoning", {"text": follow_event["text"]})
                        elif ft == "content":
                            full_content += follow_event["text"]
                            _push_chunk("content", {"text": follow_event["text"]})
                        elif ft == "done":
                            usage = follow_event.get("usage") or usage

                # Final state
                state["status"] = "done"
                state["content"] = full_content
                state["reasoning"] = full_reasoning
                state["usage"] = usage
                state["chunks"] = []  # Clear chunks — frontend has all content now
                if usage:
                    state["meta"] = {**meta, "prompt_tokens": usage.get("prompt_tokens"), "completion_tokens": usage.get("completion_tokens")}
                await cache_set_json(job_key, state, ttl_seconds=180)

            elif evt_type == "error":
                state["status"] = "error"
                state["content"] = f"Error: {event['text']}"
                state["chunks"] = []
                await cache_set_json(job_key, state, ttl_seconds=180)
                return

            # Persist after each event (so poll can see incremental content)
            state["content"] = full_content
            state["reasoning"] = full_reasoning
            await cache_set_json(job_key, state, ttl_seconds=180)

    except Exception as exc:
        state["status"] = "error"
        state["content"] = f"Error: {exc}"
        state["chunks"] = []
        await cache_set_json(job_key, state, ttl_seconds=180)


class ChatStreamJobResponse(BaseModel):
    job_id: str
    meta: dict[str, Any] | None = None


class ChatStreamJobStatus(BaseModel):
    status: str
    content: str = ""
    reasoning: str = ""
    chunks: list[dict[str, Any]] = []
    tool_calls: list[dict[str, Any]] = []
    usage: dict[str, Any] | None = None
    meta: dict[str, Any] | None = None


@router.post("/chat-stream-job", response_model=ChatStreamJobResponse)
async def agent_chat_stream_job(
    body: AgentChatRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> ChatStreamJobResponse:
    """Start a streaming chat job; returns job_id to poll for incremental chunks."""
    from app.agent.tools import REGISTRY

    context_messages, case, meta = await _build_chat_context(body, db)

    tools_schema = []
    for name, tool in REGISTRY.items():
        try:
            tools_schema.append(tool.to_openai_schema())
        except Exception:
            pass

    job_id = str(_uuid.uuid4())
    # Store initial state
    await cache_set_json(
        f"chatjob:{job_id}",
        {"status": "streaming", "meta": meta, "chunks": [], "tool_calls": [],
         "content": "", "reasoning": "", "usage": None},
        ttl_seconds=180,
    )
    # Launch background streaming job
    asyncio.create_task(_run_stream_job(job_id, context_messages, meta, tools_schema if tools_schema else None, case))
    return ChatStreamJobResponse(job_id=job_id, meta=meta)


@router.get("/chat-stream-job/{job_id}", response_model=ChatStreamJobStatus)
async def agent_chat_stream_job_status(job_id: str) -> ChatStreamJobStatus:
    """Poll for streaming chat job incremental status."""
    data = await cache_get_json(f"chatjob:{job_id}")
    if data is None:
        raise HTTPException(status_code=404, detail="Job not found or expired")
    return ChatStreamJobStatus(
        status=data.get("status", "unknown"),
        content=data.get("content", ""),
        reasoning=data.get("reasoning", ""),
        chunks=data.get("chunks", []),
        tool_calls=data.get("tool_calls", []),
        usage=data.get("usage"),
        meta=data.get("meta"),
    )