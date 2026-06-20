from __future__ import annotations

from pathlib import Path
from typing import Any

from .manifest import load_manifest
from .paths import WorkPaths
from .utils import read_text, write_text


def _replacement(formula: dict[str, Any], config: dict[str, Any]) -> str:
    selected = (formula.get("selected_latex") or "").strip()
    if selected:
        key = "display_wrapper" if formula.get("display_type") == "display" else "inline_wrapper"
        return config.get("merge", {}).get(key, "{latex}").format(latex=selected)
    todo = f"<!-- TODO_FORMULA_{formula['id']}: formula OCR/validation failed; original image kept. -->"
    return f"{formula.get('original_match', '')}\n{todo}"


def merge_markdown(workdir: str | Path, config: dict[str, Any]) -> Path:
    wp = WorkPaths.from_workdir(workdir)
    manifest = load_manifest(workdir)
    md_path = Path(manifest.get("markdown") or wp.text_md)
    text = read_text(md_path)
    formulas = list(manifest.get("formulas", []))
    # Reverse by original byte/char offsets so earlier replacements do not shift later spans.
    for formula in sorted(formulas, key=lambda f: int(f.get("position", {}).get("start", -1)), reverse=True):
        repl = _replacement(formula, config)
        pos = formula.get("position") or {}
        start, end = pos.get("start"), pos.get("end")
        original = formula.get("original_match", "")
        if isinstance(start, int) and isinstance(end, int) and text[start:end] == original:
            text = text[:start] + repl + text[end:]
        elif original and original in text:
            text = text.replace(original, repl, 1)
        else:
            text += f"\n\n<!-- TODO_FORMULA_{formula['id']}: original image match not found during merge. -->\n"
    return write_text(wp.final_md, text)
