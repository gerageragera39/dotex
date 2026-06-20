from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..latex_clean import clean_latex_candidate
from ..manifest import load_manifest, save_manifest
from .base import Candidate, has_candidate


def extract_math_fragments(tex: str) -> list[str]:
    fragments: list[str] = []
    patterns = [
        r"\\\[(.*?)\\\]",
        r"\$\$(.*?)\$\$",
        r"\\begin\{(?:equation\*?|align\*?|gather\*?|multline\*?)\}(.*?)\\end\{(?:equation\*?|align\*?|gather\*?|multline\*?)\}",
        r"\\\((.*?)\\\)",
        r"(?<!\\)\$(?!\$)(.*?)(?<!\\)\$",
    ]
    for pat in patterns:
        for m in re.finditer(pat, tex, flags=re.S):
            candidate = clean_latex_candidate(m.group(1))
            if candidate:
                fragments.append(candidate)
    return fragments


def add_docx2tex_candidates(workdir: str | Path, docx2tex_tex: str | Path, config: dict[str, Any], force: bool = False) -> dict[str, Any]:
    manifest = load_manifest(workdir)
    text = Path(docx2tex_tex).read_text(encoding="utf-8", errors="replace")
    fragments = extract_math_fragments(text)
    for formula, latex in zip(manifest.get("formulas", []), fragments, strict=False):
        if has_candidate(formula, "docx2tex") and not force:
            continue
        if force:
            formula["candidates"] = [c for c in formula.get("candidates", []) if c.get("source") != "docx2tex"]
        formula.setdefault("candidates", []).append(Candidate(source="docx2tex", latex=latex, raw=latex).to_dict())
    manifest["docx2tex_added"] = {"source_tex": str(Path(docx2tex_tex).resolve()), "fragments_found": len(fragments)}
    save_manifest(workdir, manifest)
    return manifest
