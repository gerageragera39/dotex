from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .latex_clean import braces_balanced, contains_embedded_math_wrappers, looks_like_refusal
from .latex_validate import validate_formula_candidate
from .manifest import formula_display_type, load_manifest, save_manifest, set_display_type_manual
from .visual_compare import score_candidate_visual


def is_bad_candidate(candidate: dict[str, Any], config: dict[str, Any]) -> tuple[bool, str | None]:
    latex = (candidate.get("latex") or "").strip()
    if not latex:
        return True, "empty"
    if looks_like_refusal(latex):
        return True, "model refusal"
    if contains_embedded_math_wrappers(latex):
        return True, "embedded math wrappers"
    if re.search(r"\\\)\s*(?:h?t?arrow|rightarrow|leftarrow)|\\\)htarrow", latex):
        return True, "broken wrapper/arrow fragment"
    if not braces_balanced(latex):
        return True, "unbalanced braces/brackets"
    for pat in config.get("candidate_selection", {}).get("reject_patterns", []):
        if re.search(pat, latex):
            return True, f"reject pattern: {pat}"
    if "```" in latex or re.search(r"^\s{0,3}#{1,6}\s", latex, flags=re.M):
        return True, "markdown leakage"
    words = re.findall(r"[A-Za-zА-Яа-яЁё]{3,}", latex)
    commands = re.findall(r"\\[A-Za-z]+", latex)
    prose_words = max(0, len(words) - len(commands))
    max_expl = int(config.get("candidate_selection", {}).get("max_explanation_chars", 20))
    if prose_words >= 8 and len(re.sub(r"\\[A-Za-z]+", "", latex)) > max_expl * 4:
        return True, "looks like explanatory text"
    return False, None


def _candidate_key(candidate: dict[str, Any], index: int) -> str:
    key = candidate.get("candidate_key")
    if key:
        return str(key)
    key = f"{candidate.get('source', 'unknown')}:{candidate.get('variant', 'original')}:{index}"
    candidate["candidate_key"] = key
    return key


def _find_formula(manifest: dict[str, Any], formula_id: str) -> dict[str, Any]:
    for formula in manifest.get("formulas", []):
        if str(formula.get("id")) == str(formula_id):
            return formula
    raise KeyError(f"Formula not found: {formula_id}")


def _mark_selected(formula: dict[str, Any], candidate: dict[str, Any], key: str) -> None:
    formula["selected_latex"] = candidate.get("latex")
    formula["selected_source"] = candidate.get("source")
    formula["selected_candidate_key"] = key
    formula["validation_status"] = candidate.get("validation_status") or "pending"
    formula["validation_error"] = candidate.get("validation_error")


def select_candidates(workdir: str | Path, config: dict[str, Any], force_auto_select: bool = False) -> dict[str, Any]:
    manifest = load_manifest(workdir)
    priority = config.get("candidate_selection", {}).get("priority", ["pix2tex", "texteller", "ollama_qwen", "docx2tex"])
    order = {source: idx for idx, source in enumerate(priority)}
    strategy = config.get("candidate_selection", {}).get("strategy", "visual_best")
    threshold = float(config.get("candidate_selection", {}).get("min_visual_score", 0.70))
    for formula in manifest.get("formulas", []):
        for idx, candidate in enumerate(formula.get("candidates", []), start=1):
            _candidate_key(candidate, idx)
        if not force_auto_select and formula.get("selected_source") == "manual" and (formula.get("selected_latex") or "").strip():
            formula["selection_rejected"] = formula.get("selection_rejected", [])
            continue
        chosen = None
        rejected: list[dict[str, str]] = []
        candidates = list(formula.get("candidates", []))
        for candidate in candidates:
            bad, reason = is_bad_candidate(candidate, config)
            if bad:
                rejected.append({"source": candidate.get("source", "unknown"), "reason": reason or "bad"})
        valid = [c for c in candidates if c.get("validation_status") == "valid" and not is_bad_candidate(c, config)[0]]
        if strategy == "visual_best":
            for c in valid:
                if c.get("visual_score") is None:
                    score_candidate_visual(formula, c)
            visual = [c for c in valid if c.get("visual_score") is not None]
            visual.sort(key=lambda c: (float(c.get("visual_score") or 0), -order.get(c.get("source", ""), 999)), reverse=True)
            if visual and float(visual[0].get("visual_score") or 0) >= threshold:
                chosen = visual[0]
            else:
                for c in visual:
                    rejected.append({"source": c.get("source", "unknown"), "reason": f"visual_score below threshold: {c.get('visual_score')}"})
        if chosen is None:
            valid.sort(key=lambda c: order.get(c.get("source", ""), 999))
            chosen = valid[0] if valid else None
        formula["selection_rejected"] = rejected
        if chosen:
            key = str(chosen.get("candidate_key") or "")
            _mark_selected(formula, chosen, key)
        else:
            formula["selected_latex"] = formula.get("selected_latex") if formula.get("selected_latex") and not force_auto_select else None
            formula["selected_source"] = formula.get("selected_source") if formula.get("selected_latex") else None
            formula["validation_status"] = "invalid"
            formula["validation_error"] = "no valid candidate selected"
    save_manifest(workdir, manifest)
    return manifest


def add_manual_candidate(workdir: str | Path, formula_id: str, latex: str, display_type: str | None = None) -> dict[str, Any]:
    manifest = load_manifest(workdir)
    formula = _find_formula(manifest, formula_id)
    if display_type:
        set_display_type_manual(formula, display_type)
    idx = 1 + sum(1 for c in formula.get("candidates", []) if c.get("source") == "manual")
    candidate = {
        "source": "manual",
        "variant": "manual",
        "raw": latex,
        "latex": latex.strip(),
        "validation_status": "pending",
        "validation_error": None,
        "candidate_key": f"manual:manual:{idx}",
    }
    formula.setdefault("candidates", []).append(candidate)
    save_manifest(workdir, manifest)
    return candidate


def compile_manual_candidate(workdir: str | Path, formula_id: str, latex: str, config: dict[str, Any]) -> dict[str, Any]:
    manifest = load_manifest(workdir)
    formula = _find_formula(manifest, formula_id)
    candidate = add_manual_candidate(workdir, formula_id, latex)
    manifest = load_manifest(workdir)
    formula = _find_formula(manifest, formula_id)
    # Re-find the newly added manual candidate.
    idx = len(formula.get("candidates", []))
    candidate = formula["candidates"][idx - 1]
    result = validate_formula_candidate(candidate.get("latex", ""), formula_id, "manual", idx, workdir, config, force=True, display_type=formula_display_type(formula))
    candidate["validation_status"] = result["status"]
    candidate["validation_error"] = result["error"]
    candidate["latex_hash"] = result.get("latex_hash")
    candidate["artifacts"] = {k: v for k, v in result.items() if k in {"tex", "pdf", "log", "preview_png", "latex_hash"} and v}
    save_manifest(workdir, manifest)
    return {**candidate, "result": result}


def select_candidate(
    workdir: str | Path,
    formula_id: str,
    candidate_key: str | None = None,
    source: str | None = None,
    index: int | None = None,
    latex: str | None = None,
    config: dict[str, Any] | None = None,
    display_type: str | None = None,
) -> dict[str, Any]:
    if latex is not None:
        if config is not None:
            compiled = compile_manual_candidate(workdir, formula_id, latex, config)
            candidate_key = compiled.get("candidate_key")
        else:
            c = add_manual_candidate(workdir, formula_id, latex, display_type=display_type)
            candidate_key = c.get("candidate_key")
    manifest = load_manifest(workdir)
    formula = _find_formula(manifest, formula_id)
    if display_type:
        set_display_type_manual(formula, display_type)
    target: tuple[dict[str, Any], str] | None = None
    for idx, candidate in enumerate(formula.get("candidates", []), start=1):
        key = _candidate_key(candidate, idx)
        if candidate_key and key == candidate_key:
            target = (candidate, key)
            break
        if source and candidate.get("source") == source and (index is None or idx == index):
            target = (candidate, key)
            break
    if target is None:
        raise KeyError("Candidate not found")
    _mark_selected(formula, target[0], target[1])
    save_manifest(workdir, manifest)
    return formula
