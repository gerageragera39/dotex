from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from jinja2 import Template

from .manifest import load_manifest, save_manifest
from .paths import WorkPaths
from .utils import write_text

VALIDATE_TEMPLATE = r"""\documentclass{article}
\usepackage{fontspec}
\usepackage{amsmath,amssymb,amsfonts,mathtools}
\usepackage{upgreek,tensor,xfrac}
\providecommand{\Uptheta}{\Theta}
\providecommand{\Upomega}{\Omega}
\providecommand{\Updelta}{\Delta}
\providecommand{\Upphi}{\Phi}
\providecommand{\Upsigma}{\Sigma}
\pagestyle{empty}
\begin{document}
\[
{{ formula }}
\]
\end{document}
"""


def _safe_name(source: str, index: int) -> str:
    return f"candidate_{re.sub(r'[^A-Za-z0-9_.-]+', '_', source)}_{index}"


def validate_formula_candidate(
    latex: str,
    formula_id: str,
    source: str,
    index: int,
    workdir: str | Path,
    config: dict[str, Any],
    force: bool = False,
) -> dict[str, Any]:
    wp = WorkPaths.from_workdir(workdir)
    out_dir = wp.validate_dir / formula_id
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = _safe_name(source, index)
    tex_path = out_dir / f"{stem}.tex"
    pdf_path = out_dir / f"{stem}.pdf"
    log_path = out_dir / f"{stem}.log"
    if pdf_path.exists() and log_path.exists() and not force:
        return {"status": "valid", "error": None, "tex": str(tex_path), "pdf": str(pdf_path), "log": str(log_path)}
    if not latex.strip():
        return {"status": "invalid", "error": "empty candidate", "tex": str(tex_path), "pdf": None, "log": None}
    write_text(tex_path, Template(VALIDATE_TEMPLATE).render(formula=latex))
    engine = config.get("latex", {}).get("engine", "xelatex")
    if shutil.which(engine) is None:
        return {"status": "invalid", "error": f"{engine} not found", "tex": str(tex_path), "pdf": None, "log": None}
    cmd = [engine, "-interaction=nonstopmode", "-halt-on-error", tex_path.name]
    proc = subprocess.run(cmd, cwd=out_dir, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
    ok = proc.returncode == 0 and pdf_path.exists()
    if not log_path.exists():
        write_text(log_path, proc.stdout + "\n" + proc.stderr)
    error = None if ok else _summarize_latex_error(log_path, proc.stdout, proc.stderr)
    return {"status": "valid" if ok else "invalid", "error": error, "tex": str(tex_path), "pdf": str(pdf_path) if pdf_path.exists() else None, "log": str(log_path)}


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


def validate_manifest(workdir: str | Path, config: dict[str, Any], force: bool = False) -> dict[str, Any]:
    manifest = load_manifest(workdir)
    for formula in manifest.get("formulas", []):
        for idx, candidate in enumerate(formula.get("candidates", []), start=1):
            if candidate.get("validation_status") in {"valid", "invalid"} and not force:
                continue
            if candidate.get("validation_status") == "error" and not candidate.get("latex") and not force:
                continue
            try:
                result = validate_formula_candidate(candidate.get("latex", ""), formula["id"], candidate.get("source", "unknown"), idx, workdir, config, force)
                candidate["validation_status"] = result["status"]
                candidate["validation_error"] = result["error"]
                candidate["artifacts"] = {k: v for k, v in result.items() if k in {"tex", "pdf", "log"} and v}
            except Exception as exc:
                candidate["validation_status"] = "invalid"
                candidate["validation_error"] = str(exc)
    save_manifest(workdir, manifest)
    return manifest
