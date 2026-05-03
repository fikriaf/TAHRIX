"""Hypothesis manager — tracks the agent's evolving beliefs.

Each hypothesis has a confidence updated via simple Bayesian-flavored evidence
accumulation: each piece of supporting evidence pulls confidence up toward 1.0
with a learning-rate gain; conflicting evidence pulls it back.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Literal


@dataclass
class Hypothesis:
    id: str
    statement: str
    confidence: float = 0.5
    status: Literal["ACTIVE", "CONFIRMED", "REJECTED"] = "ACTIVE"
    evidence_for: list[str] = field(default_factory=list)
    evidence_against: list[str] = field(default_factory=list)

    def update(self, *, support: float = 0.0, conflict: float = 0.0,
               note_for: str | None = None, note_against: str | None = None) -> None:
        # Smooth update: confidence ← confidence + lr * (support - conflict)
        lr = 0.2
        delta = (max(0.0, min(1.0, support)) - max(0.0, min(1.0, conflict))) * lr
        self.confidence = max(0.0, min(1.0, self.confidence + delta))
        if note_for:
            self.evidence_for.append(note_for)
        if note_against:
            self.evidence_against.append(note_against)
        if self.confidence >= 0.85:
            self.status = "CONFIRMED"
        elif self.confidence <= 0.15:
            self.status = "REJECTED"


class HypothesisManager:
    def __init__(self) -> None:
        self._hypotheses: dict[str, Hypothesis] = {}

    def add(self, statement: str, *, initial_confidence: float = 0.5) -> Hypothesis:
        h = Hypothesis(id=uuid.uuid4().hex[:8], statement=statement,
                       confidence=initial_confidence)
        self._hypotheses[h.id] = h
        return h

    def get(self, hid: str) -> Hypothesis | None:
        return self._hypotheses.get(hid)

    def all(self) -> list[Hypothesis]:
        return list(self._hypotheses.values())

    def max_confidence(self) -> float:
        return max((h.confidence for h in self._hypotheses.values()), default=0.0)

    def to_list(self) -> list[dict]:
        return [
            {"id": h.id, "statement": h.statement, "confidence": h.confidence,
             "status": h.status, "evidence_for": h.evidence_for[-5:],
             "evidence_against": h.evidence_against[-5:]}
            for h in self._hypotheses.values()
        ]
