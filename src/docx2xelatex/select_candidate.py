from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .latex_clean import braces_balanced, looks_like_refusal
from .manifest import load_manifest, save_manifest


def is_bad_candidate(candidate: dict[str, Any], config: dict[str, Any]) -> tuple[bool, str | None]:
    latex = (candidate.get("latex") or "").strip()
    if not latex:
        return True, "empty"
    if looks_like_refusal(latex):
        return True, "model refusal"
    if not braces_balanced(latex):
        return True, "unbalanced braces/brackets"
    for pat in config.get("candidate_selection", {}).get("reject_patterns", []):
        if re.search(pat, latex):
            return True, f"reject pattern: {pat}"
    # Markdown or prose leakage guard.
    if "```" in latex or re.search(r"^\s{0,3}#{1,6}\s", latex, flags=re.M):
        return True, "markdown leakage"
    words = re.findall(r"[A-Za-zА-Яа-яЁё]{3,}", latex)
    commands = re.findall(r"\\[A-Za-z]+", latex)
    prose_words = max(0, len(words) - len(commands))
    max_expl = int(config.get("candidate_selection", {}).get("max_explanation_chars", 20))
    if prose_words >= 8 and len(re.sub(r"\\[A-Za-z]+", "", latex)) > max_expl * 4:
        return True, "looks like explanatory text"
    return False, None


def select_candidates(workdir: str | Path, config: dict[str, Any]) -> dict[str, Any]:
    manifest = load_manifest(workdir)
    priority = config.get("candidate_selection", {}).get("priority", ["docx2tex", "ollama_qwen"])
    order = {source: idx for idx, source in enumerate(priority)}
    for formula in manifest.get("formulas", []):
        chosen = None
        rejected: list[dict[str, str]] = []
        candidates = sorted(formula.get("candidates", []), key=lambda c: order.get(c.get("source", ""), 999))
        for candidate in candidates:
            bad, reason = is_bad_candidate(candidate, config)
            if bad:
                rejected.append({"source": candidate.get("source", "unknown"), "reason": reason or "bad"})
                continue
            if candidate.get("validation_status") == "valid":
                chosen = candidate
                break
        formula["selection_rejected"] = rejected
        if chosen:
            formula["selected_latex"] = chosen.get("latex")
            formula["selected_source"] = chosen.get("source")
            formula["validation_status"] = "valid"
            formula["validation_error"] = None
        else:
            formula["selected_latex"] = formula.get("selected_latex") if formula.get("selected_latex") else None
            formula["selected_source"] = formula.get("selected_source") if formula.get("selected_latex") else None
            formula["validation_status"] = "invalid"
            formula["validation_error"] = "no valid candidate selected"
    save_manifest(workdir, manifest)
    return manifest
