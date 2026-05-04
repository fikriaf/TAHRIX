"""
TAHRIX Agent — Hybrid Streaming Backend (FastAPI + Redis)

Architecture:
  POST /chat-stream-job       -> Create job, return job_id
  GET  /chat-stream-job/{id}  -> Poll for incremental chunks
  Background coroutine        -> Stream LLM, execute tools, store chunks in Redis

Required imports:
  from app.core.cache import cache_get_json, cache_set_json
  from app.agent.llm import get_llm
  from app.agent.tools import REGISTRY, ToolContext
"""

import asyncio
import json
import uuid as _uuid
from typing import Any, Annotated
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

# Adjust these imports to your project structure
from app.core.cache import cache_get_json, cache_set_json
from app.agent.llm import get_llm
from app.agent.tools import REGISTRY, ToolContext
from app.api.deps import get_db, get_current_user
from app.models.domain import User

router = APIRouter()


# ── Pydantic Models ──────────────────────────────────────────────────────────

class AgentChatRequest(BaseModel):
    message: str
    case_id: str | None = None
    history: list[dict[str, Any]] | None = None

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


# ── Background Coroutine ─────────────────────────────────────────────────────

async def _run_stream_job(
    job_id: str,
    messages: list[dict[str, Any]],
    meta: dict[str, Any],
    tools_schema: list[dict[str, Any]] | None,
    case: Any,
) -> None:
    """Background coroutine: stream LLM response, store incremental chunks in Redis."""
    job_key = f"chatjob:{job_id}"
    full_content = ""
    full_reasoning = ""
    tool_calls_executed: list[dict[str, Any]] = []

    # Initial state
    state: dict[str, Any] = {
        "status": "streaming",
        "meta": meta,
        "chunks": [],
        "tool_calls": [],
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
                        # CRITICAL: Use .fn — Tool dataclass is not callable
                        result = await tool_func.fn(tool_args, ctx)
                        result_str = json.dumps(result)[:1000] if result else "No result"
                    except Exception as te:
                        result_str = f"Error: {str(te)}"

                    _push_chunk("tool_result", {"name": tool_name, "result": result_str})
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

                    # Reset content — first call's content was pre-tool planning
                    full_content = ""
                    full_reasoning = ""
                    _push_chunk("follow_up", {"text": "Synthesizing results..."})

                    # Instruction so model doesn't repeat previous content
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

            # Persist after each event
            state["content"] = full_content
            state["reasoning"] = full_reasoning
            await cache_set_json(job_key, state, ttl_seconds=180)

    except Exception as exc:
        state["status"] = "error"
        state["content"] = f"Error: {exc}"
        state["chunks"] = []
        await cache_set_json(job_key, state, ttl_seconds=180)


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/chat-stream-job", response_model=ChatStreamJobResponse)
async def agent_chat_stream_job(
    body: AgentChatRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> ChatStreamJobResponse:
    from app.agent.tools import REGISTRY  # Import here to avoid circular imports

    # Build context (adapt _build_chat_context to your project)
    context_messages, case, meta = await _build_chat_context(body, db)

    # Prepare tool schemas
    tools_schema = []
    for name, tool in REGISTRY.items():
        try:
            tools_schema.append(tool.to_openai_schema())
        except Exception:
            pass

    # Create job
    job_id = str(_uuid.uuid4())
    await cache_set_json(f"chatjob:{job_id}", {
        "status": "streaming",
        "meta": meta,
        "chunks": [],
        "tool_calls": [],
        "content": "",
        "reasoning": "",
        "usage": None,
    }, ttl_seconds=180)

    # Launch background coroutine
    asyncio.create_task(_run_stream_job(
        job_id, context_messages, meta,
        tools_schema if tools_schema else None, case
    ))

    return ChatStreamJobResponse(job_id=job_id, meta=meta)


@router.get("/chat-stream-job/{job_id}", response_model=ChatStreamJobStatus)
async def agent_chat_stream_job_status(
    job_id: str,
    user: Annotated[User, Depends(get_current_user)],
) -> ChatStreamJobStatus:
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
