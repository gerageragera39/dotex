from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, NamedTuple
from urllib.parse import unquote

from .manifest import load_manifest, parse_markdown_images
from .paths import WorkPaths
from .utils import read_text, write_json, write_text


class MergeInvariantError(RuntimeError):
    def __init__(self, message: str, unresolved: list[dict[str, Any]]):
        super().__init__(message)
        self.unresolved = unresolved


class Replacement(NamedTuple):
    start: int
    end: int
    text: str
    formula_id: str


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


def _formula_display_type(formula: dict[str, Any]) -> str:
    manual = (formula.get("display_type_manual") or "").strip()
    auto = (formula.get("display_type_auto") or formula.get("display_type") or "inline").strip()
    return manual if manual in {"inline", "display"} else (auto if auto in {"inline", "display"} else "inline")


def _replacement(formula: dict[str, Any], config: dict[str, Any], wp: WorkPaths) -> str:
    selected = (formula.get("selected_latex") or "").strip()
    if selected:
        key = "display_wrapper" if _formula_display_type(formula) == "display" else "inline_wrapper"
        return config.get("merge", {}).get(key, "{latex}").format(latex=selected)
    policy = config.get("merge", {}).get("invalid_formula_policy", "keep_image_with_todo")
    if policy == "drop_with_todo":
        return f"<!-- TODO_FORMULA_{formula['id']}: formula OCR/validation failed. -->"
    return _png_todo_replacement(formula, wp)


def validate_replacements_no_overlap(replacements: Iterable[tuple[int, int, str, str] | Replacement]) -> list[dict[str, Any]]:
    """Return overlap/range problems for replacement spans.

    The merge stage must never apply overlapping ranges because replacing from the
    back can otherwise delete unrelated text between two formula placeholders.
    """
    problems: list[dict[str, Any]] = []
    normalized: list[Replacement] = []
    for item in replacements:
        r = item if isinstance(item, Replacement) else Replacement(item[0], item[1], item[2], str(item[3]))
        if r.start < 0 or r.end < r.start:
            problems.append({"reason": "invalid replacement range", "formula_ids": [r.formula_id], "start": r.start, "end": r.end})
        normalized.append(r)
    ordered = sorted(normalized, key=lambda r: (r.start, r.end))
    for prev, cur in zip(ordered, ordered[1:]):
        if cur.start < prev.end:
            problems.append(
                {
                    "reason": "overlapping replacements",
                    "formula_ids": [prev.formula_id, cur.formula_id],
                    "ranges": [[prev.start, prev.end], [cur.start, cur.end]],
                }
            )
    return problems


def _overlaps_existing(start: int, end: int, replacements: list[Replacement]) -> bool:
    return any(start < r.end and r.start < end for r in replacements)


def _position(formula: dict[str, Any]) -> tuple[int | None, int | None]:
    pos = formula.get("position") or {}
    start, end = pos.get("start"), pos.get("end")
    return (start if isinstance(start, int) else None, end if isinstance(end, int) else None)


def _choose_formula_for_image(
    img_start: int,
    img_end: int,
    matches: list[dict[str, Any]],
    used_formula_ids: set[str],
) -> dict[str, Any] | None:
    unused = [f for f in matches if str(f.get("id")) not in used_formula_ids]
    if not unused:
        return None
    exact = [f for f in unused if _position(f) == (img_start, img_end)]
    if exact:
        return exact[0]

    def distance(formula: dict[str, Any]) -> tuple[int, str]:
        start, end = _position(formula)
        if start is None:
            return (10**12, str(formula.get("id")))
        return (abs(start - img_start) + (abs((end or start) - img_end) if end is not None else 0), str(formula.get("id")))

    return sorted(unused, key=distance)[0]


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

    replacements: list[Replacement] = []
    used_formula_ids: set[str] = set()
    unresolved: list[dict[str, Any]] = []
    images = parse_markdown_images(text)
    for img in images:
        matches = [f for f in formulas if _dest_matches_formula(img.dest, f, wp.root, markdown_dir)]
        if not matches:
            continue
        match = _choose_formula_for_image(img.start, img.end, matches, used_formula_ids)
        if not match:
            unresolved.append({"dest": img.dest, "original": img.original, "reason": "all matching formulas already used", "formula_ids": [f.get("id") for f in matches]})
            continue
        fid = str(match.get("id"))
        if _overlaps_existing(img.start, img.end, replacements):
            unresolved.append({"reason": "overlap skipped", "formula_ids": [fid], "range": [img.start, img.end]})
            continue
        replacements.append(Replacement(img.start, img.end, _replacement(match, config, wp), fid))
        used_formula_ids.add(fid)

    # Fallback to historical exact offsets/matches only for formulas not paired
    # with parsed Markdown images, and only when the range is unused.
    for formula in formulas:
        fid = str(formula.get("id"))
        if fid in used_formula_ids:
            continue
        original = formula.get("original_match", "")
        start, end = _position(formula)
        repl = _replacement(formula, config, wp)
        candidate_ranges: list[tuple[int, int]] = []
        if start is not None and end is not None and text[start:end] == original:
            candidate_ranges.append((start, end))
        if original:
            idx = text.find(original)
            if idx >= 0:
                candidate_ranges.append((idx, idx + len(original)))
        for start2, end2 in candidate_ranges:
            if _overlaps_existing(start2, end2, replacements):
                unresolved.append({"reason": "fallback replacement overlaps existing replacement", "formula_ids": [fid], "range": [start2, end2]})
                continue
            replacements.append(Replacement(start2, end2, repl, fid))
            used_formula_ids.add(fid)
            break

    overlap_problems = validate_replacements_no_overlap(replacements)
    if overlap_problems:
        unresolved.extend(overlap_problems)
        write_json(wp.root / "merge-unresolved.json", unresolved)
        if strict:
            raise MergeInvariantError("Formula merge replacements overlap; see merge-unresolved.json", unresolved)
        # Defensive: never apply ambiguous overlapping ranges in non-strict mode.
        bad_ids = {fid for item in overlap_problems for fid in item.get("formula_ids", [])}
        replacements = [r for r in replacements if r.formula_id not in bad_ids]

    for r in sorted(replacements, key=lambda item: item.start, reverse=True):
        text = text[: r.start] + r.text + text[r.end :]

    missing = [str(f.get("id")) for f in formulas if str(f.get("id")) not in used_formula_ids]
    unresolved.extend(scan_forbidden_formula_refs(text, manifest, workdir, config))
    if missing:
        unresolved.extend({"formula_ids": [fid], "reason": "formula image match not found during merge"} for fid in missing)
    if unresolved:
        write_json(wp.root / "merge-unresolved.json", unresolved)
        if strict:
            raise MergeInvariantError("Formula merge invariant failed; see merge-unresolved.json", unresolved)

    return write_text(wp.final_md, text)
