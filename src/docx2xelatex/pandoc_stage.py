from __future__ import annotations

from pathlib import Path
from typing import Any

from .paths import WorkPaths
from .subprocess_utils import run_command


def run_pandoc_docx_to_markdown(input_docx: str | Path, workdir: str | Path, config: dict[str, Any], force: bool = False) -> Path:
    wp = WorkPaths.from_workdir(workdir)
    wp.ensure()
    out = wp.text_md
    if out.exists() and not force:
        return out
    pandoc_cfg = config.get("pandoc", {})
    cmd = [
        "pandoc",
        str(Path(input_docx)),
        "-f",
        pandoc_cfg.get("from", "docx"),
        "-t",
        pandoc_cfg.get("to", "markdown+raw_tex+tex_math_single_backslash"),
        "--wrap",
        str(pandoc_cfg.get("wrap", "none")),
        "--extract-media",
        str(wp.root),
        "-o",
        str(out),
    ]
    proc = run_command(cmd)
    if proc.returncode != 0:
        raise RuntimeError(f"pandoc failed ({proc.returncode})\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")
    return out
