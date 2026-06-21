from __future__ import annotations

import hashlib
import re
import shutil
from pathlib import Path
from typing import Any

from jinja2 import Template

from .build_latex import render_latex_header, validate_latex_config
from .formula_filter import filter_formulas
from .latex_clean import clean_latex_candidate, contains_embedded_math_wrappers, generate_repair_candidates
from .manifest import formula_display_type, load_manifest, save_manifest
from .paths import WorkPaths
from .subprocess_utils import run_command
from .utils import read_text, write_text

VALIDATE_TEMPLATE = r"""\documentclass[{{ fontsize }}]{{ '{' }}{{ documentclass }}{{ '}' }}
{{ header }}
\pagestyle{empty}
\begin{document}
{{ body }}
\end{document}
"""


def normalized_latex_hash(latex: str) -> str:
    normalized = clean_latex_candidate(latex or "")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _safe_name(source: str, index: int, latex_hash: str) -> str:
    return f"candidate_{re.sub(r'[^A-Za-z0-9_.-]+', '_', source)}_{index}_{latex_hash[:12]}"


def _body_for_formula(latex: str, display_type: str, wrapper_mode: str = "auto") -> str:
    display = display_type == "display"
    if wrapper_mode == "inline":
        display = False
    elif wrapper_mode == "display":
        display = True
    if display:
        return "\\[\n" + latex + "\n\\]"
    return "Текст до \\( " + latex + " \\) текст после."


def _validation_document(latex: str, display_type: str, config: dict[str, Any], wrapper_mode: str = "auto") -> str:
    validate_latex_config(config)
    latex_cfg = config.get("latex", {})
    return Template(VALIDATE_TEMPLATE).render(
        fontsize=latex_cfg.get("fontsize", "12pt"),
        documentclass=latex_cfg.get("documentclass", "article"),
        header=render_latex_header(config),
        body=_body_for_formula(latex, display_type, wrapper_mode),
    )


def _summarize_latex_error(log_path: Path, stdout: str, stderr: str) -> str:
    text = ""
    if log_path.exists():
        text = log_path.read_text(encoding="utf-8", errors="replace")
    text = text or stdout or stderr
    lines = []
    for line in text.splitlines():
        if line.startswith("!") or "Undefined control sequence" in line or "Emergency stop" in line:
            lines.append(line.strip())
        if len(lines) >= 8:
            break
    return "\n".join(lines) or (text[-1200:] if text else "xelatex failed")


def render_pdf_preview(pdf_path: str | Path, out_path: str | Path, config: dict[str, Any], force: bool = False) -> str | None:
    pdf = Path(pdf_path)
    out = Path(out_path)
    val = config.get("validation", {})
    if not bool(val.get("render_preview", True)):
        return None
    if out.exists() and not force and out.stat().st_mtime >= pdf.stat().st_mtime:
        return str(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    density = str(val.get("preview_density", 300))
    trim = bool(val.get("preview_trim", True))
    padding = int(val.get("preview_padding", 12) or 0)
    background = str(config.get("images", {}).get("background", "white"))
    if shutil.which("magick"):
        cmd = ["magick", "-density", density, str(pdf), "-background", background, "-alpha", "remove", "-alpha", "off"]
        if trim:
            cmd.extend(["-trim", "+repage"])
        if padding > 0:
            cmd.extend(["-bordercolor", background, "-border", str(padding)])
        cmd.append(str(out))
        proc = run_command(cmd, timeout=120)
        if proc.returncode == 0 and out.exists():
            return str(out)
    tmp_stem = out.with_suffix("")
    if shutil.which("pdftoppm"):
        proc = run_command(["pdftoppm", "-png", "-r", density, "-singlefile", str(pdf), str(tmp_stem)], timeout=120)
        produced = tmp_stem.with_suffix(".png")
        if proc.returncode == 0 and produced.exists():
            if produced != out:
                produced.replace(out)
            if shutil.which("magick") and (trim or padding > 0):
                cmd = ["magick", str(out), "-background", background, "-alpha", "remove", "-alpha", "off"]
                if trim:
                    cmd.extend(["-trim", "+repage"])
                if padding > 0:
                    cmd.extend(["-bordercolor", background, "-border", str(padding)])
                cmd.append(str(out))
                run_command(cmd, timeout=120)
            return str(out) if out.exists() else None
    if shutil.which("pdftocairo"):
        proc = run_command(["pdftocairo", "-png", "-r", density, "-singlefile", str(pdf), str(tmp_stem)], timeout=120)
        produced = tmp_stem.with_suffix(".png")
        if proc.returncode == 0 and produced.exists():
            if produced != out:
                produced.replace(out)
            return str(out)
    return None


def _existing_artifacts_current(tex_path: Path, pdf_path: Path, log_path: Path, expected_tex: str, latex_hash: str) -> bool:
    if not (tex_path.exists() and pdf_path.exists() and log_path.exists()):
        return False
    try:
        return read_text(tex_path) == expected_tex
    except Exception:
        return False


def validate_formula_candidate(
    latex: str,
    formula_id: str,
    source: str,
    index: int,
    workdir: str | Path,
    config: dict[str, Any],
    force: bool = False,
    display_type: str = "display",
    wrapper_mode: str = "auto",
) -> dict[str, Any]:
    wp = WorkPaths.from_workdir(workdir)
    out_dir = wp.validate_dir / formula_id
    out_dir.mkdir(parents=True, exist_ok=True)
    normalized = clean_latex_candidate(latex or "")
    latex_hash = normalized_latex_hash(normalized)
    stem = _safe_name(source, index, latex_hash)
    tex_path = out_dir / f"{stem}.tex"
    pdf_path = out_dir / f"{stem}.pdf"
    log_path = out_dir / f"{stem}.log"
    preview_path = out_dir / f"{stem}.png"
    base = {"latex_hash": latex_hash, "tex": str(tex_path), "pdf": str(pdf_path) if pdf_path.exists() else None, "log": str(log_path) if log_path.exists() else None}
    if not normalized:
        return {**base, "status": "invalid", "error": "empty candidate", "pdf": None, "log": None}
    if contains_embedded_math_wrappers(normalized):
        return {**base, "status": "invalid", "error": "embedded math wrappers in candidate", "pdf": None, "log": None}
    tex_content = _validation_document(normalized, display_type, config, wrapper_mode)
    if _existing_artifacts_current(tex_path, pdf_path, log_path, tex_content, latex_hash) and not force:
        preview = render_pdf_preview(pdf_path, preview_path, config, force=False) if pdf_path.exists() else None
        return {"status": "valid", "error": None, "tex": str(tex_path), "pdf": str(pdf_path), "log": str(log_path), "preview_png": preview, "latex_hash": latex_hash}
    write_text(tex_path, tex_content)
    engine = config.get("latex", {}).get("engine", "xelatex")
    if shutil.which(engine) is None:
        return {**base, "status": "invalid", "error": f"{engine} not found", "pdf": None, "log": None}
    cmd = [engine, "-interaction=nonstopmode", "-halt-on-error", tex_path.name]
    proc = run_command(cmd, cwd=out_dir, timeout=120)
    ok = proc.returncode == 0 and pdf_path.exists()
    if not log_path.exists():
        write_text(log_path, proc.stdout + "\n" + proc.stderr)
    error = None if ok else _summarize_latex_error(log_path, proc.stdout, proc.stderr)
    preview = render_pdf_preview(pdf_path, preview_path, config, force=True) if ok else None
    return {
        "status": "valid" if ok else "invalid",
        "error": error,
        "tex": str(tex_path),
        "pdf": str(pdf_path) if pdf_path.exists() else None,
        "log": str(log_path),
        "preview_png": preview,
        "latex_hash": latex_hash,
    }


def _candidate_key(candidate: dict[str, Any], index: int) -> str:
    return str(candidate.get("candidate_key") or f"{candidate.get('source', 'unknown')}:{candidate.get('variant', 'original')}:{index}")


def _ensure_repair_candidates(formula: dict[str, Any]) -> None:
    existing = {(c.get("source"), c.get("latex")) for c in formula.get("candidates", [])}
    additions: list[dict[str, Any]] = []
    for idx, candidate in enumerate(list(formula.get("candidates", [])), start=1):
        if candidate.get("repair_of"):
            continue
        for repaired in generate_repair_candidates(candidate.get("latex") or candidate.get("raw") or ""):
            source = f"{candidate.get('source', 'unknown')}_repair"
            key = (source, repaired)
            if key in existing:
                continue
            additions.append(
                {
                    "source": source,
                    "variant": candidate.get("variant", "repair"),
                    "raw": candidate.get("raw"),
                    "latex": repaired,
                    "repair_of": _candidate_key(candidate, idx),
                    "validation_status": "pending",
                    "validation_error": None,
                }
            )
            existing.add(key)
    formula.setdefault("candidates", []).extend(additions)


def validate_manifest(
    workdir: str | Path,
    config: dict[str, Any],
    force: bool = False,
    only_id: str | None = None,
    limit: int | None = None,
    from_id: str | None = None,
    to_id: str | None = None,
) -> dict[str, Any]:
    manifest = load_manifest(workdir)
    formulas = filter_formulas(
        list(manifest.get("formulas", [])),
        only_id=only_id,
        limit=limit,
        from_id=from_id,
        to_id=to_id,
    )
    for formula in formulas:
        _ensure_repair_candidates(formula)
        display_type = formula_display_type(formula)
        for idx, candidate in enumerate(formula.get("candidates", []), start=1):
            current_hash = normalized_latex_hash(candidate.get("latex", ""))
            artifacts = candidate.get("artifacts") or {}
            stale = candidate.get("latex_hash") != current_hash or artifacts.get("latex_hash") not in {None, current_hash}
            if candidate.get("validation_status") in {"valid", "invalid"} and not force and not stale:
                continue
            if candidate.get("validation_status") == "error" and not candidate.get("latex") and not force:
                continue
            try:
                result = validate_formula_candidate(candidate.get("latex", ""), formula["id"], candidate.get("source", "unknown"), idx, workdir, config, force, display_type=display_type)
                candidate["validation_status"] = result["status"]
                candidate["validation_error"] = result["error"]
                candidate["latex_hash"] = result.get("latex_hash")
                candidate["artifacts"] = {k: v for k, v in result.items() if k in {"tex", "pdf", "log", "preview_png", "latex_hash"} and v}
            except Exception as exc:
                candidate["validation_status"] = "invalid"
                candidate["validation_error"] = str(exc)
    save_manifest(workdir, manifest)
    return manifest
