from __future__ import annotations

from typing import Any


def formula_matches_id_range(
    formula: dict[str, Any],
    only_id: str | None = None,
    from_id: str | None = None,
    to_id: str | None = None,
) -> bool:
    formula_id = str(formula.get("id", ""))
    if only_id and formula_id != only_id:
        return False
    if from_id and formula_id < from_id:
        return False
    if to_id and formula_id > to_id:
        return False
    return True


def filter_formulas(
    formulas: list[dict[str, Any]],
    only_id: str | None = None,
    limit: int | None = None,
    from_id: str | None = None,
    to_id: str | None = None,
) -> list[dict[str, Any]]:
    selected = [
        formula
        for formula in formulas
        if formula_matches_id_range(formula, only_id=only_id, from_id=from_id, to_id=to_id)
    ]
    if limit is not None:
        if limit < 0:
            raise ValueError("limit must be >= 0")
        selected = selected[:limit]
    return selected
