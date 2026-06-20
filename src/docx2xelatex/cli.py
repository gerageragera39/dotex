from __future__ import annotations

import json
import shutil
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Optional

import typer

from .build_latex import build as build_stage
from .config import load_config, write_default_config
from .engines.docx2tex_tex import add_docx2tex_candidates as add_docx2tex_stage
from .engines.ollama_qwen import run_ocr
from .image_convert import render_images as render_images_stage
from .latex_validate import validate_manifest
from .manifest import create_manifest, load_manifest
from .merge_markdown import merge_markdown as merge_stage
from .pandoc_stage import run_pandoc_docx_to_markdown
from .paths import WorkPaths
from .report import generate_report
from .select_candidate import select_candidates
from .utils import command_exists, write_json

app = typer.Typer(help="Local privacy-first DOCX → Markdown → formula OCR → clean XeLaTeX pipeline.", no_args_is_help=True)


def _cfg(config: Optional[Path]) -> dict:
    return load_config(config)


def _echo_json(data: dict) -> None:
    typer.echo(json.dumps(data, ensure_ascii=False, indent=2))


@app.command()
def doctor(config: Optional[Path] = typer.Option(None, "--config", help="YAML config path.")) -> None:
    """Check local tools and Ollama model availability. Installs nothing."""
    cfg = _cfg(config)
    ollama = cfg.get("ollama", {})
    report: dict[str, object] = {
        "python": {"version": sys.version.split()[0], "ok": sys.version_info >= (3, 11)},
        "pandoc": {"path": shutil.which("pandoc"), "ok": command_exists("pandoc")},
        "magick": {"path": shutil.which("magick"), "ok": command_exists("magick")},
        "xelatex": {"path": shutil.which(cfg.get("latex", {}).get("engine", "xelatex")), "ok": command_exists(cfg.get("latex", {}).get("engine", "xelatex"))},
        "ollama": {"base_url": ollama.get("base_url"), "ok": False, "model": ollama.get("model"), "model_ok": False},
    }
    base = str(ollama.get("base_url", "http://localhost:11434")).rstrip("/")
    try:
        host = __import__("urllib.parse").parse.urlparse(base).hostname
        if host not in {"localhost", "127.0.0.1", "::1"}:
            raise RuntimeError("non-local Ollama URL refused")
        with urllib.request.urlopen(f"{base}/api/tags", timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        models = [m.get("name") for m in data.get("models", [])]
        report["ollama"] = {"base_url": base, "ok": True, "model": ollama.get("model"), "model_ok": ollama.get("model") in models, "available_models": models}
    except Exception as exc:
        report["ollama"] = {"base_url": base, "ok": False, "model": ollama.get("model"), "model_ok": False, "error": str(exc)}
    _echo_json(report)


@app.command("init-config")
def init_config(out: Path = typer.Option(..., "--out", help="Output YAML config path.")) -> None:
    path = write_default_config(out)
    typer.echo(f"Wrote {path}")


@app.command("inspect-docx")
def inspect_docx(input_path: Path = typer.Option(..., "--input", help="DOCX file."), workdir: Path = typer.Option(..., "--workdir"), config: Optional[Path] = typer.Option(None, "--config")) -> None:
    """Inspect DOCX container counts without printing document text."""
    _cfg(config)
    wp = WorkPaths.from_workdir(workdir)
    wp.ensure()
    counts = {"media_wmf": 0, "media_emf": 0, "media_png": 0, "media_other": 0, "ole_embeddings": 0, "omml_oMath": 0, "omml_oMathPara": 0}
    with zipfile.ZipFile(input_path) as zf:
        names = zf.namelist()
        for name in names:
            low = name.lower()
            if low.startswith("word/media/"):
                if low.endswith(".wmf"):
                    counts["media_wmf"] += 1
                elif low.endswith(".emf"):
                    counts["media_emf"] += 1
                elif low.endswith(".png"):
                    counts["media_png"] += 1
                else:
                    counts["media_other"] += 1
            if low.startswith("word/embeddings/oleobject") and low.endswith(".bin"):
                counts["ole_embeddings"] += 1
        for name in names:
            if name.startswith("word/") and name.endswith(".xml"):
                xml = zf.read(name).decode("utf-8", errors="ignore")
                counts["omml_oMath"] += xml.count("<m:oMath")
                counts["omml_oMathPara"] += xml.count("<m:oMathPara")
    result = {"input": str(input_path), "counts": counts}
    write_json(wp.root / "inspect_docx.json", result)
    _echo_json(result)


@app.command("pandoc-md")
def pandoc_md(input_path: Path = typer.Option(..., "--input"), workdir: Path = typer.Option(..., "--workdir"), config: Optional[Path] = typer.Option(None, "--config"), force: bool = typer.Option(False, "--force")) -> None:
    out = run_pandoc_docx_to_markdown(input_path, workdir, _cfg(config), force=force)
    typer.echo(f"Wrote {out}")


@app.command("manifest")
def manifest_cmd(markdown: Path = typer.Option(..., "--markdown"), workdir: Path = typer.Option(..., "--workdir"), config: Optional[Path] = typer.Option(None, "--config"), force: bool = typer.Option(False, "--force")) -> None:
    m = create_manifest(markdown, workdir, _cfg(config), force=force)
    typer.echo(f"Manifest: {WorkPaths.from_workdir(workdir).manifest_json} ({len(m.get('formulas', []))} formulas)")


@app.command("render-images")
def render_images(workdir: Path = typer.Option(..., "--workdir"), config: Optional[Path] = typer.Option(None, "--config"), force: bool = typer.Option(False, "--force")) -> None:
    m = render_images_stage(workdir, _cfg(config), force=force)
    typer.echo(f"Rendered/checked {len(m.get('formulas', []))} formula images")


@app.command("ocr")
def ocr(
    workdir: Path = typer.Option(..., "--workdir"),
    config: Optional[Path] = typer.Option(None, "--config"),
    force: bool = typer.Option(False, "--force"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Inspect what would be OCRed."),
    progress: bool = typer.Option(True, "--progress/--no-progress", help="Show tqdm-style progress and status hints."),
    verbose: bool = typer.Option(False, "--verbose", help="Print per-formula start/skip/done messages."),
    timeout_seconds: Optional[int] = typer.Option(None, "--timeout-seconds", help="Override Ollama per-formula request timeout."),
) -> None:
    if dry_run:
        m = load_manifest(workdir)
        todo = [
            f["id"]
            for f in m.get("formulas", [])
            if force
            or not any(
                c.get("source") == "ollama_qwen"
                and c.get("validation_status") != "error"
                and (c.get("latex") or "").strip()
                for c in f.get("candidates", [])
            )
        ]
        status_files = {f["id"]: str(WorkPaths.from_workdir(workdir).ocr_dir / f"{f['id']}_ollama_qwen.json") for f in m.get("formulas", [])}
        _echo_json({"would_ocr": todo, "count": len(todo), "status_files": status_files, "sequential": True})
        return
    cfg = _cfg(config)
    if timeout_seconds is not None:
        cfg.setdefault("ollama", {})["timeout_seconds"] = timeout_seconds
    m = run_ocr(workdir, cfg, force=force, progress=progress, verbose=verbose)
    typer.echo(f"OCR candidates recorded for {len(m.get('formulas', []))} formulas")


@app.command("add-docx2tex-candidates")
def add_docx2tex_candidates(workdir: Path = typer.Option(..., "--workdir"), docx2tex_tex: Path = typer.Option(..., "--docx2tex-tex"), config: Optional[Path] = typer.Option(None, "--config"), force: bool = typer.Option(False, "--force")) -> None:
    m = add_docx2tex_stage(workdir, docx2tex_tex, _cfg(config), force=force)
    typer.echo(f"docx2tex candidates processed; formulas={len(m.get('formulas', []))}")


@app.command("validate")
def validate(workdir: Path = typer.Option(..., "--workdir"), config: Optional[Path] = typer.Option(None, "--config"), force: bool = typer.Option(False, "--force"), dry_run: bool = typer.Option(False, "--dry-run")) -> None:
    if dry_run:
        m = load_manifest(workdir)
        _echo_json({"candidate_count": sum(len(f.get("candidates", [])) for f in m.get("formulas", []))})
        return
    m = validate_manifest(workdir, _cfg(config), force=force)
    typer.echo(f"Validated candidates for {len(m.get('formulas', []))} formulas")


@app.command("select")
def select(workdir: Path = typer.Option(..., "--workdir"), config: Optional[Path] = typer.Option(None, "--config")) -> None:
    m = select_candidates(workdir, _cfg(config))
    selected = sum(1 for f in m.get("formulas", []) if f.get("selected_latex"))
    typer.echo(f"Selected {selected}/{len(m.get('formulas', []))} formulas")


@app.command("report")
def report(workdir: Path = typer.Option(..., "--workdir"), config: Optional[Path] = typer.Option(None, "--config")) -> None:
    out = generate_report(workdir, _cfg(config))
    typer.echo(f"Wrote {out}")


@app.command("merge")
def merge(workdir: Path = typer.Option(..., "--workdir"), config: Optional[Path] = typer.Option(None, "--config")) -> None:
    out = merge_stage(workdir, _cfg(config))
    typer.echo(f"Wrote {out}")


@app.command("build")
def build_cmd(workdir: Path = typer.Option(..., "--workdir"), config: Optional[Path] = typer.Option(None, "--config"), force: bool = typer.Option(False, "--force")) -> None:
    result = build_stage(workdir, _cfg(config), force=force)
    _echo_json(result)


@app.command("full")
def full(input_path: Path = typer.Option(..., "--input"), workdir: Path = typer.Option(..., "--workdir"), config: Optional[Path] = typer.Option(None, "--config"), force: bool = typer.Option(False, "--force")) -> None:
    cfg = _cfg(config)
    wp = WorkPaths.from_workdir(workdir)
    wp.ensure()
    run_pandoc_docx_to_markdown(input_path, workdir, cfg, force=force)
    create_manifest(wp.text_md, workdir, cfg, force=force)
    render_images_stage(workdir, cfg, force=force)
    run_ocr(workdir, cfg, force=force)
    validate_manifest(workdir, cfg, force=force)
    select_candidates(workdir, cfg)
    generate_report(workdir, cfg)
    merge_stage(workdir, cfg)
    result = build_stage(workdir, cfg, force=force)
    typer.echo("Full pipeline finished. Per-formula failures, if any, are recorded in manifest/report.")
    _echo_json(result)


if __name__ == "__main__":
    app()
