from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Protocol


@dataclass
class Candidate:
    source: str
    latex: str
    raw: str | None = None
    score: float | None = None
    validation_status: str | None = None
    validation_error: str | None = None
    artifacts: dict[str, str] | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return {k: v for k, v in data.items() if v is not None}


class FormulaEngine(Protocol):
    source: str

    def recognize(self, image_path: str) -> Candidate:
        ...


def has_candidate(formula: dict[str, Any], source: str) -> bool:
    return any(c.get("source") == source for c in formula.get("candidates", []))
