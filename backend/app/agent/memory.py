"""Agent memory: short-term (Redis) + long-term (Neo4j case events).

Short-term memory holds the *current* iteration's working set: visited addresses,
tool calls already made, hypothesis state. TTL = 1 hour.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.db.redis import cache_get_json, cache_set_json


def _key(case_id: str) -> str:
    return f"agent:mem:{case_id}"


@dataclass
class AgentMemory:
    case_id: str
    visited: set[str] = field(default_factory=set)
    tool_history: list[dict[str, Any]] = field(default_factory=list)
    hypotheses: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "visited": list(self.visited),
            "tool_history": self.tool_history,
            "hypotheses": self.hypotheses,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "AgentMemory":
        return cls(
            case_id=d["case_id"],
            visited=set(d.get("visited", [])),
            tool_history=d.get("tool_history", []),
            hypotheses=d.get("hypotheses", []),
        )

    async def save(self, ttl_seconds: int = 3600) -> None:
        await cache_set_json(_key(self.case_id), self.to_dict(), ttl_seconds)

    @classmethod
    async def load(cls, case_id: str) -> "AgentMemory":
        data = await cache_get_json(_key(case_id))
        if data:
            return cls.from_dict(data)
        return cls(case_id=case_id)
