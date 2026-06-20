from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .paths import WorkPaths
from .utils import read_json, read_text, write_json


@dataclass
class MarkdownImage:
    alt: str
    dest: str
    attrs: str
    original: str
    start: int
    end: int


def _find_closing_bracket(text: str, start: int) -> int:
    escaped = False
    for i in range(start, len(text)):
        ch = text[i]
        if escaped:
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            continue
        if ch == "]":
            return i
    return -1


def parse_markdown_images(markdown: str) -> list[MarkdownImage]:
    """Parse Markdown image links without assuming simple regex paths.

    Supports ![](path), ![alt](path){attrs}, angle-bracket destinations, spaces,
    Cyrillic, Windows drive paths, escaped characters and balanced parentheses inside paths.
    """
    images: list[MarkdownImage] = []
    i = 0
    n = len(markdown)
    while i < n - 3:
        if markdown[i] != "!" or markdown[i + 1] != "[":
            i += 1
            continue
        alt_end = _find_closing_bracket(markdown, i + 2)
        if alt_end < 0 or alt_end + 1 >= n or markdown[alt_end + 1] != "(":
            i += 1
            continue
        alt = markdown[i + 2 : alt_end]
        dest_start = alt_end + 2
        j = dest_start
        dest = ""
        if j < n and markdown[j] == "<":
            j += 1
            begin = j
            escaped = False
            while j < n:
                ch = markdown[j]
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == ">" and j + 1 < n and markdown[j + 1] == ")":
                    dest = markdown[begin:j]
                    j += 2
                    break
                j += 1
            else:
                i += 1
                continue
        else:
            begin = j
            depth = 0
            escaped = False
            while j < n:
                ch = markdown[j]
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == "(":
                    depth += 1
                elif ch == ")":
                    if depth == 0:
                        dest = markdown[begin:j]
                        j += 1
                        break
                    depth -= 1
                j += 1
            else:
                i += 1
                continue
        attrs_start = j
        while j < n and markdown[j].isspace() and markdown[j] != "\n":
            j += 1
        attrs = ""
        if j < n and markdown[j] == "{":
            depth = 1
            k = j + 1
            while k < n and depth:
                if markdown[k] == "{":
                    depth += 1
                elif markdown[k] == "}":
                    depth -= 1
                k += 1
            if depth == 0:
                attrs = markdown[j:k]
                j = k
            else:
                j = attrs_start
        original = markdown[i:j]
        images.append(MarkdownImage(alt=alt, dest=dest.strip(), attrs=attrs, original=original, start=i, end=j))
        i = j
    return images


def _display_guess(markdown: str, start: int, end: int) -> str:
    line_start = markdown.rfind("\n", 0, start) + 1
    line_end = markdown.find("\n", end)
    if line_end == -1:
        line_end = len(markdown)
    before = markdown[line_start:start].strip()
    after = markdown[end:line_end].strip()
    return "display" if not before and not after else "inline"


def _resolve_image_path(dest: str, markdown_path: Path, workdir: Path) -> Path:
    raw = dest.strip().strip('"').strip("'")
    p = Path(raw)
    if p.is_absolute():
        return p
    candidates = [markdown_path.parent / raw, workdir / raw]
    for c in candidates:
        if c.exists():
            return c.resolve()
    return candidates[0].resolve()


def _is_formula_image(dest: str, extensions: Iterable[str]) -> bool:
    lower = dest.lower().split("?", 1)[0].split("#", 1)[0]
    return any(lower.endswith(ext.lower()) for ext in extensions)


def create_manifest(markdown: str | Path, workdir: str | Path, config: dict[str, Any], force: bool = False) -> dict[str, Any]:
    wp = WorkPaths.from_workdir(workdir)
    wp.ensure()
    md_path = Path(markdown).expanduser().resolve()
    text = read_text(md_path)
    exts = config.get("images", {}).get("formula_extensions", [".wmf", ".emf"])
    formulas: list[dict[str, Any]] = []
    for img in parse_markdown_images(text):
        if not _is_formula_image(img.dest, exts):
            continue
        fid = f"f{len(formulas) + 1:04d}"
        resolved = _resolve_image_path(img.dest, md_path, wp.root)
        formulas.append(
            {
                "id": fid,
                "original_match": img.original,
                "alt": img.alt,
                "markdown_path": img.dest,
                "image_path": str(resolved),
                "display_type": _display_guess(text, img.start, img.end),
                "position": {"start": img.start, "end": img.end},
                "png_path": str(wp.png_dir / f"{fid}.png"),
                "candidates": [],
                "selected_latex": None,
                "selected_source": None,
                "validation_status": "pending",
                "validation_error": None,
            }
        )
    manifest = {"version": 1, "markdown": str(md_path), "workdir": str(wp.root), "formulas": formulas}
    if wp.manifest_json.exists() and not force:
        # Manifest creation is intentionally deterministic. Existing OCR/validation data
        # should not be overwritten accidentally; use --force to rebuild from Markdown.
        return read_json(wp.manifest_json)
    write_json(wp.manifest_json, manifest)
    return manifest


def load_manifest(workdir: str | Path) -> dict[str, Any]:
    return read_json(WorkPaths.from_workdir(workdir).manifest_json)


def save_manifest(workdir: str | Path, manifest: dict[str, Any]) -> Path:
    return write_json(WorkPaths.from_workdir(workdir).manifest_json, manifest)
