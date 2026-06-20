from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import unquote

from .manifest import load_manifest, parse_markdown_images
from .paths import WorkPaths
from .utils import read_text, write_json, write_text


class MergeInvariantError(RuntimeError):
    def __init__(self, message: str, unresolved: list[dict[str, Any]]):
        super().__init__(message)
        self.unresolved = unresolved


def _normalize_ref(value: str | None) -> str:
    raw = unquote(str(value or "").strip().strip("<>").strip('"').strip("'"))
    return raw.replace("\\", "/").lower()


def _basename(value: str | None) -> str:
    norm = _normalize_ref(value).split("?", 1)[0].split("#", 1)[0]
    return norm.rsplit("/", 1)[-1]


def _path_variants(value: str | None, workdir: Path, markdown_dir: Path) -> set[str]:
    if not value:
        return set()
    raw = unquote(str(value).strip().strip("<>").strip('"').strip("'"))
    variants = {_normalize_ref(raw)}
    p = Path(raw)
    candidates = [p]
    if not p.is_absolute():
        candidates.extend([markdown_dir / raw, workdir / raw])
    for candidate in candidates:
        try:
            variants.add(_normalize_ref(str(candidate.resolve())))
        except Exception:
            variants.add(_normalize_ref(str(candidate)))
        try:
            variants.add(_normalize_ref(str(candidate.relative_to(workdir))))
        except Exception:
            pass
    base = _basename(raw)
    if base:
        variants.add(base)
    return {v for v in variants if v}


def _formula_variants(formula: dict[str, Any], workdir: Path, markdown_dir: Path) -> set[str]:
    variants: set[str] = set()
    for key in ("markdown_path", "image_path", "png_path"):
        variants |= _path_variants(formula.get(key), workdir, markdown_dir)
    original = formula.get("original_match") or ""
    for img in parse_markdown_images(original):
        variants |= _path_variants(img.dest, workdir, markdown_dir)
    return variants


def _dest_matches_formula(dest: str, formula: dict[str, Any], workdir: Path, markdown_dir: Path) -> bool:
    dest_variants = _path_variants(dest, workdir, markdown_dir)
    formula_variants = _formula_variants(formula, workdir, markdown_dir)
    if dest_variants & formula_variants:
        return True
    return bool(_basename(dest) and _basename(dest) in {_basename(formula.get("markdown_path")), _basename(formula.get("image_path"))})


def _formula_exts(config: dict[str, Any]) -> list[str]:
    return [str(ext).lower() for ext in config.get("images", {}).get("formula_extensions", [".wmf", ".emf"])]


def _is_forbidden_formula_dest(dest: str, config: dict[str, Any]) -> bool:
    lower = _normalize_ref(dest).split("?", 1)[0].split("#", 1)[0]
    return any(lower.endswith(ext) for ext in _formula_exts(config))


def _markdown_image(dest: str, alt: str = "") -> str:
    safe_dest = dest.replace("\\", "/")
    return f"![{alt}]({safe_dest})"


def _png_todo_replacement(formula: dict[str, Any], wp: WorkPaths) -> str:
    png = Path(formula.get("png_path") or (wp.png_dir / f"{formula['id']}.png"))
    try:
        png_ref = png.resolve().relative_to(wp.root.resolve()).as_posix()
    except Exception:
        png_ref = png.as_posix()
    todo = f"<!-- TODO_FORMULA_{formula['id']}: formula OCR/validation failed; PNG preview kept instead of WMF/EMF. -->"
    return f"{_markdown_image(png_ref)}\n{todo}"


def _replacement(formula: dict[str, Any], config: dict[str, Any], wp: WorkPaths) -> str:
    selected = (formula.get("selected_latex") or "").strip()
    if selected:
        key = "display_wrapper" if formula.get("display_type") == "display" else "inline_wrapper"
        return config.get("merge", {}).get(key, "{latex}").format(latex=selected)
    policy = config.get("merge", {}).get("invalid_formula_policy", "keep_image_with_todo")
    if policy == "drop_with_todo":
        return f"<!-- TODO_FORMULA_{formula['id']}: formula OCR/validation failed. -->"
    return _png_todo_replacement(formula, wp)


def scan_forbidden_formula_refs(markdown_text: str, manifest: dict[str, Any], workdir: str | Path, config: dict[str, Any]) -> list[dict[str, Any]]:
    wp = WorkPaths.from_workdir(workdir)
    markdown_dir = Path(manifest.get("markdown") or wp.text_md).parent
    formulas = list(manifest.get("formulas", []))
    unresolved: list[dict[str, Any]] = []
    for img in parse_markdown_images(markdown_text):
        if not _is_forbidden_formula_dest(img.dest, config):
            continue
        matches = [f for f in formulas if _dest_matches_formula(img.dest, f, wp.root, markdown_dir)]
        if matches:
            unresolved.append({"dest": img.dest, "original": img.original, "formula_ids": [f.get("id") for f in matches]})
    for formula in formulas:
        if (formula.get("selected_latex") or "").strip():
            original = formula.get("original_match") or ""
            if original and original in markdown_text:
                unresolved.append({"dest": formula.get("markdown_path"), "original": original, "formula_ids": [formula.get("id")], "reason": "selected formula original_match remains"})
    return unresolved


def assert_no_forbidden_formula_refs(markdown_text: str, manifest: dict[str, Any], workdir: str | Path, config: dict[str, Any]) -> None:
    unresolved = scan_forbidden_formula_refs(markdown_text, manifest, workdir, config)
    if unresolved:
        raise MergeInvariantError("Forbidden WMF/EMF formula references remain after merge", unresolved)


def merge_markdown(workdir: str | Path, config: dict[str, Any], strict: bool = True) -> Path:
    wp = WorkPaths.from_workdir(workdir)
    manifest = load_manifest(workdir)
    md_path = Path(manifest.get("markdown") or wp.text_md)
    text = read_text(md_path)
    markdown_dir = md_path.parent
    formulas = list(manifest.get("formulas", []))

    replacements: list[tuple[int, int, str, str]] = []
    used_formula_ids: set[str] = set()
    images = parse_markdown_images(text)
    for img in images:
        match = next((f for f in formulas if _dest_matches_formula(img.dest, f, wp.root, markdown_dir)), None)
        if not match:
            continue
        replacements.append((img.start, img.end, _replacement(match, config, wp), str(match.get("id"))))
        used_formula_ids.add(str(match.get("id")))

    # Fallback to historical exact offsets/matches if the Markdown parser did not
    # see a variant that still exists in the text.
    for formula in formulas:
        fid = str(formula.get("id"))
        if fid in used_formula_ids:
            continue
        original = formula.get("original_match", "")
        pos = formula.get("position") or {}
        start, end = pos.get("start"), pos.get("end")
        repl = _replacement(formula, config, wp)
        if isinstance(start, int) and isinstance(end, int) and text[start:end] == original:
            replacements.append((start, end, repl, fid))
            used_formula_ids.add(fid)
        elif original and original in text:
            idx = text.find(original)
            replacements.append((idx, idx + len(original), repl, fid))
            used_formula_ids.add(fid)

    for start, end, repl, _fid in sorted(replacements, key=lambda item: item[0], reverse=True):
        text = text[:start] + repl + text[end:]

    missing = [str(f.get("id")) for f in formulas if str(f.get("id")) not in used_formula_ids]
    unresolved = scan_forbidden_formula_refs(text, manifest, workdir, config)
    if missing:
        unresolved.extend({"formula_ids": [fid], "reason": "formula image match not found during merge"} for fid in missing)
    if unresolved:
        write_json(wp.root / "merge-unresolved.json", unresolved)
        if strict:
            raise MergeInvariantError("Formula merge invariant failed; see merge-unresolved.json", unresolved)

    return write_text(wp.final_md, text)
