from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Template

from .manifest import load_manifest
from .paths import WorkPaths
from .utils import write_text


def _template_text() -> str:
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "templates" / "report.html.j2"
        if candidate.exists():
            return candidate.read_text(encoding="utf-8")
    return """<!doctype html><meta charset='utf-8'><h1>Formula report</h1>{% for f in formulas %}<h2>{{ f.id }}</h2><pre>{{ f.selected_latex }}</pre>{% endfor %}"""


def _rel(path: str | None, start: Path) -> str | None:
    if not path:
        return None
    try:
        return Path(path).resolve().relative_to(start.resolve()).as_posix()
    except Exception:
        try:
            return Path(path).resolve().relative_to(start.parent.resolve()).as_posix()
        except Exception:
            return Path(path).as_posix()


def generate_report(workdir: str | Path, config: dict[str, Any]) -> Path:
    wp = WorkPaths.from_workdir(workdir)
    wp.ensure()
    manifest = load_manifest(workdir)
    rows: list[dict[str, Any]] = []
    for formula in manifest.get("formulas", []):
        artifacts = []
        for c in formula.get("candidates", []):
            artifacts_map = c.get("artifacts") or {}
            c["preview_rel"] = _rel(artifacts_map.get("preview_png"), wp.report_dir)
            for label, p in artifacts_map.items():
                artifacts.append({"label": f"{c.get('source')} {label}", "href": _rel(p, wp.report_dir)})
        status = formula.get("validation_status") or "pending"
        row = dict(formula)
        row["row_class"] = "valid" if status == "valid" else "invalid" if status == "invalid" else "pending"
        row["png_rel"] = _rel(formula.get("png_path"), wp.report_dir)
        selected = next((c for c in row.get("candidates", []) if c.get("candidate_key") == row.get("selected_candidate_key")), None)
        row["selected_preview_rel"] = _rel(((selected or {}).get("artifacts") or {}).get("preview_png"), wp.report_dir)
        row["artifacts"] = artifacts
        rows.append(row)
    html = Template(_template_text()).render(formulas=rows, manifest_path=str(wp.manifest_json))
    return write_text(wp.report_html, html)
