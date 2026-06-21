from __future__ import annotations

from pathlib import Path
from typing import Any

from .build_latex import compile_tex
from .latex_validate import normalized_latex_hash, validate_formula_candidate
from .manifest import formula_display_type, load_manifest, save_manifest
from .merge_markdown import scan_forbidden_formula_refs
from .paths import WorkPaths


def audit_workdir(workdir: str | Path, config: dict[str, Any]) -> dict[str, Any]:
    wp = WorkPaths.from_workdir(workdir)
    manifest = load_manifest(workdir)
    formulas = list(manifest.get("formulas", []))
    stale: list[dict[str, Any]] = []
    selected_no_preview: list[str] = []
    selected_failing: list[dict[str, Any]] = []
    manual = 0
    unresolved: list[str] = []
    selected_valid = 0
    for formula in formulas:
        if formula.get("selected_source") == "manual":
            manual += 1
        if not (formula.get("selected_latex") or "").strip():
            unresolved.append(str(formula.get("id")))
        if formula.get("validation_status") == "valid" and formula.get("selected_latex"):
            selected_valid += 1
        for idx, c in enumerate(formula.get("candidates", []), start=1):
            current_hash = normalized_latex_hash(c.get("latex", ""))
            artifacts = c.get("artifacts") or {}
            if c.get("latex_hash") and c.get("latex_hash") != current_hash:
                stale.append({"formula_id": formula.get("id"), "candidate_index": idx, "reason": "latex_hash mismatch"})
            elif artifacts.get("tex") and Path(artifacts["tex"]).exists() and current_hash not in Path(artifacts["tex"]).name:
                stale.append({"formula_id": formula.get("id"), "candidate_index": idx, "reason": "artifact path missing current hash"})
        selected_key = formula.get("selected_candidate_key")
        selected_candidate = next((c for c in formula.get("candidates", []) if c.get("candidate_key") == selected_key), None)
        if formula.get("selected_latex"):
            preview = (selected_candidate or {}).get("artifacts", {}).get("preview_png") if selected_candidate else None
            if not preview:
                selected_no_preview.append(str(formula.get("id")))
            if selected_candidate and selected_candidate.get("validation_status") != "valid":
                selected_failing.append({"formula_id": formula.get("id"), "reason": selected_candidate.get("validation_error") or selected_candidate.get("validation_status")})
    final_forbidden: list[dict[str, Any]] = []
    if wp.final_md.exists():
        final_forbidden = scan_forbidden_formula_refs(wp.final_md.read_text(encoding="utf-8", errors="replace"), manifest, workdir, config)
    final_compile = {"status": "missing", "error": "final.tex not found"}
    if wp.final_tex.exists():
        final_compile = compile_tex(wp.final_tex, config)
    return {
        "total_formulas": len(formulas),
        "selected_valid_formulas": selected_valid,
        "manual_formulas": manual,
        "unresolved_todo_formulas": len(unresolved),
        "unresolved_ids": unresolved,
        "candidates_with_stale_artifacts": stale,
        "selected_candidates_without_preview": selected_no_preview,
        "selected_candidates_failing_validation": selected_failing,
        "final_md_forbidden_image_refs": final_forbidden,
        "final_tex_compile_result": final_compile,
        "status": "ok" if not (unresolved or stale or selected_failing or final_forbidden or final_compile.get("status") == "failed") else "failed",
    }
