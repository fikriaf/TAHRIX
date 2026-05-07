"""LLM provider abstraction.

Default: OpenAI-compatible Chat Completions API (works for OpenAI, Anthropic via
proxy, OpenRouter, local LM Studio / Ollama with OpenAI-compatible mode).
Tool calling uses the OpenAI function-calling schema.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.core.config import settings
from app.core.exceptions import ConfigurationError, ExternalAPIError
from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class LLMToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResponse:
    content: str | None
    tool_calls: list[LLMToolCall]
    raw: dict[str, Any]
    finish_reason: str | None = None
    usage: dict[str, int] | None = None


class LLMProvider:
    """Thin async wrapper over openai-python client (works with any OpenAI-compatible endpoint)."""

    def __init__(self) -> None:
        if not settings.llm_api_key:
            raise ConfigurationError("LLM_API_KEY missing")
        from openai import AsyncOpenAI
        self._client = AsyncOpenAI(
            api_key=settings.llm_api_key.get_secret_value(),
            base_url=str(settings.llm_base_url),
            timeout=60.0,
            max_retries=3,
        )
        self.model = settings.llm_model

        self._fallback_client = None
        if settings.llm_fallback_url:
            from openai import AsyncOpenAI
            self._fallback_client = AsyncOpenAI(
                api_key=(settings.llm_fallback_api_key.get_secret_value() if settings.llm_fallback_api_key else "dummy"),
                base_url=settings.llm_fallback_url,
                timeout=120.0,
                max_retries=2,
            )

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict | None = "auto",
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: dict | None = None,
    ) -> LLMResponse:
        try:
            resp = await self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=tools or None,
                tool_choice=tool_choice if tools else None,
                temperature=temperature if temperature is not None else settings.llm_temperature,
                max_tokens=max_tokens or settings.llm_max_tokens,
                response_format=response_format,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("Primary LLM failed, trying fallback", error=str(e))
            if self._fallback_client:
                try:
                    resp = await self._fallback_client.chat.completions.create(
                        model=settings.llm_fallback_model,
                        messages=messages,
                        temperature=temperature if temperature is not None else settings.llm_temperature,
                        max_tokens=max_tokens or settings.llm_max_tokens,
                    )
                    logger.info("Fallback LLM succeeded")
                except Exception as fe:
                    raise ExternalAPIError(f"Both primary and fallback LLM failed. Primary: {e}, Fallback: {fe}", provider="llm") from fe
            else:
                raise ExternalAPIError(f"LLM request failed: {e}", provider="llm") from e

        choice = resp.choices[0]
        msg = choice.message
        tool_calls: list[LLMToolCall] = []
        for tc in (msg.tool_calls or []):
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            tool_calls.append(LLMToolCall(
                id=tc.id, name=tc.function.name, arguments=args,
            ))
        return LLMResponse(
            content=msg.content,
            tool_calls=tool_calls,
            raw=resp.model_dump() if hasattr(resp, "model_dump") else {},
            finish_reason=choice.finish_reason,
            usage=resp.usage.model_dump() if resp.usage else None,
        )

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict | None = "auto",
        temperature: float | None = None,
        max_tokens: int | None = None,
    ):
        """Async generator yielding SSE-style dicts from the streaming LLM.

        Yields dicts with keys:
          type: "reasoning" | "content" | "tool_call" | "usage" | "done"
          + type-specific fields (text, tool_name, tool_args, usage_data, etc.)
        """
        try:
            stream = await self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=tools or None,
                tool_choice=tool_choice if tools else None,
                temperature=temperature if temperature is not None else settings.llm_temperature,
                max_tokens=max_tokens or settings.llm_max_tokens,
                stream=True,
            )
        except Exception as e:
            yield {"type": "error", "text": str(e)}
            return

        # Accumulate tool calls across chunks
        tool_calls_acc: dict[int, dict[str, Any]] = {}

        async for chunk in stream:
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            delta = choice.delta

            # Reasoning tokens
            if hasattr(delta, "reasoning") and delta.reasoning:
                yield {"type": "reasoning", "text": delta.reasoning}

            # Content tokens
            if delta.content:
                yield {"type": "content", "text": delta.content}

            # Tool call deltas (accumulate across chunks)
            if delta.tool_calls:
                for tc_delta in delta.tool_calls:
                    idx = tc_delta.index if tc_delta.index is not None else 0
                    if idx not in tool_calls_acc:
                        tool_calls_acc[idx] = {
                            "id": tc_delta.id or "",
                            "name": "",
                            "arguments": "",
                        }
                    if tc_delta.id:
                        tool_calls_acc[idx]["id"] = tc_delta.id
                    if tc_delta.function:
                        if tc_delta.function.name:
                            tool_calls_acc[idx]["name"] += tc_delta.function.name
                        if tc_delta.function.arguments:
                            tool_calls_acc[idx]["arguments"] += tc_delta.function.arguments

            # Finish reason — emit accumulated tool calls
            if choice.finish_reason:
                # Emit any accumulated tool calls
                for idx in sorted(tool_calls_acc.keys()):
                    tc = tool_calls_acc[idx]
                    try:
                        args = json.loads(tc["arguments"] or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    yield {
                        "type": "tool_call",
                        "tool_call_id": tc["id"],
                        "tool_name": tc["name"],
                        "tool_args": args,
                    }

                # Usage from last chunk
                usage_data = None
                if chunk.usage:
                    usage_data = {
                        "prompt_tokens": chunk.usage.prompt_tokens,
                        "completion_tokens": chunk.usage.completion_tokens,
                        "total_tokens": chunk.usage.total_tokens,
                    }

                yield {
                    "type": "done",
                    "finish_reason": choice.finish_reason,
                    "usage": usage_data,
                }

    async def aclose(self) -> None:
        await self._client.close()


_provider: LLMProvider | None = None


def get_llm() -> LLMProvider:
    global _provider
    if _provider is None:
        _provider = LLMProvider()
    return _provider
