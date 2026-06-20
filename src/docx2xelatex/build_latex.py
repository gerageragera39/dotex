from __future__ import annotations

import shutil
import subprocess
from importlib import resources
from pathlib import Path
from typing import Any

from .paths import WorkPaths
from .utils import write_text


def _header_path(workdir: Path) -> Path:
    try:
        template = resources.files("docx2xelatex").joinpath("../../templates/header.tex")
        if template.is_file():
            return Path(str(template))
    except Exception:
        pass
    # Editable/source tree fallback.
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "templates" / "header.tex"
        if candidate.exists():
            return candidate
    header = workdir / "header.tex"
    write_text(header, "% fallback header\n\\usepackage{fontspec}\n\\usepackage{amsmath,amssymb,amsfonts,mathtools}\n")
    return header


def pandoc_final_to_tex(workdir: str | Path, config: dict[str, Any], force: bool = False) -> Path:
    wp = WorkPaths.from_workdir(workdir)
    wp.ensure()
    if wp.final_tex.exists() and not force:
        return wp.final_tex
    if not wp.final_md.exists():
        raise FileNotFoundError(f"final.md not found: {wp.final_md}")
    latex = config.get("latex", {})
    cmd = [
        "pandoc",
        str(wp.final_md),
        "-f",
        "markdown+raw_tex+tex_math_single_backslash",
        "-t",
        "latex",
        "--standalone",
        "-H",
        str(_header_path(wp.root)),
        "-V",
        f"mainfont={latex.get('mainfont', 'Times New Roman')}",
        "-V",
        f"sansfont={latex.get('sansfont', 'Arial')}",
        "-V",
        f"monofont={latex.get('monofont', 'Courier New')}",
        "-V",
        f"documentclass={latex.get('documentclass', 'article')}",
        "-V",
        f"fontsize={latex.get('fontsize', '12pt')}",
        "-V",
        f"lang={latex.get('lang', 'ru-RU')}",
        "--resource-path",
        str(wp.root),
        "-o",
        str(wp.final_tex),
    ]
    proc = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        raise RuntimeError(f"pandoc final build failed ({proc.returncode})\n{proc.stdout}\n{proc.stderr}")
    return wp.final_tex


def compile_final_pdf(workdir: str | Path, config: dict[str, Any]) -> dict[str, Any]:
    wp = WorkPaths.from_workdir(workdir)
    latex = config.get("latex", {})
    if not latex.get("build_pdf", True):
        return {"status": "skipped", "pdf": None, "log": None, "error": None}
    engine = latex.get("engine", "xelatex")
    if shutil.which(engine) is None:
        return {"status": "failed", "pdf": None, "log": None, "error": f"{engine} not found"}
    if not wp.final_tex.exists():
        raise FileNotFoundError(f"final.tex not found: {wp.final_tex}")
    args = [engine, "-interaction=nonstopmode"]
    if bool(latex.get("halt_on_error", False)):
        args.append("-halt-on-error")
    args.append(wp.final_tex.name)
    last = None
    for _ in range(2):
        last = subprocess.run(args, cwd=wp.root, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=240)
        if last.returncode != 0 and latex.get("halt_on_error", False):
            break
    log = wp.root / "final.log"
    ok = wp.final_pdf.exists() and last is not None and last.returncode == 0
    err = None if ok else ((last.stdout + "\n" + last.stderr)[-2000:] if last else "xelatex was not run")
    if not log.exists() and last:
        write_text(log, last.stdout + "\n" + last.stderr)
    return {"status": "ok" if ok else "failed", "pdf": str(wp.final_pdf) if wp.final_pdf.exists() else None, "log": str(log) if log.exists() else None, "error": err}


def build(workdir: str | Path, config: dict[str, Any], force: bool = False) -> dict[str, Any]:
    tex = pandoc_final_to_tex(workdir, config, force=force)
    pdf_result = compile_final_pdf(workdir, config)
    return {"tex": str(tex), **pdf_result}
