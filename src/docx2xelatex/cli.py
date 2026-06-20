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

from .build_latex import build as build_stage, latex_doctor_checks, run_latex_smoke_test
from .config import load_config, write_default_config
from .engines.docx2tex_tex import add_docx2tex_candidates as add_docx2tex_stage
from .engines.pix2tex_engine import pix2tex_status
from .engines.texteller_engine import texteller_status
from .ocr_pipeline import candidate_priority_warnings, effective_ocr_engines, run_ocr
from .image_convert import render_images as render_images_stage
from .latex_validate import validate_manifest
from .manifest import create_manifest, load_manifest
from .merge_markdown import MergeInvariantError, merge_markdown as merge_stage
from .pandoc_stage import run_pandoc_docx_to_markdown
from .paths import WorkPaths
from .report import generate_report
from .select_candidate import select_candidates
from .subprocess_utils import run_command
from .utils import command_exists, write_json

app = typer.Typer(help="Local privacy-first DOCX → Markdown → formula OCR → clean XeLaTeX pipeline.", no_args_is_help=True)


def _cfg(config: Optional[Path]) -> dict:
    return load_config(config)


def _echo_json(data: dict) -> None:
    typer.echo(json.dumps(data, ensure_ascii=False, indent=2))


def _pix2tex_doctor_status(cfg: dict) -> dict:
    enabled = bool(cfg.get("pix2tex", {}).get("enabled", True))
    status = {**pix2tex_status(), "enabled": enabled}
    if not enabled:
        status["ok"] = True
        status["status"] = "disabled"
        status.pop("warning", None)
    else:
        status["status"] = "available" if status.get("ok") else "missing"
    return status


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
        "latex_config": latex_doctor_checks(cfg),
        "ocr": {"engines": cfg.get("ocr", {}).get("engines")},
        "effective_ocr_engines": effective_ocr_engines(cfg),
        "candidate_priority_warnings": candidate_priority_warnings(cfg),
        "texteller": texteller_status(cfg),
        "pix2tex": _pix2tex_doctor_status(cfg),
        "ollama": {"enabled": bool(ollama.get("enabled", True)), "base_url": ollama.get("base_url"), "ok": False, "model": ollama.get("model"), "model_ok": False},
    }
    base = str(ollama.get("base_url", "http://localhost:11434")).rstrip("/")
    if not bool(ollama.get("enabled", True)):
        report["ollama"] = {"enabled": False, "status": "disabled", "base_url": base, "ok": True, "model": ollama.get("model"), "model_ok": None}
    else:
        try:
            host = __import__("urllib.parse").parse.urlparse(base).hostname
            if host not in {"localhost", "127.0.0.1", "::1"}:
                raise RuntimeError("non-local Ollama URL refused")
            with urllib.request.urlopen(f"{base}/api/tags", timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            models = [m.get("name") for m in data.get("models", [])]
            report["ollama"] = {"enabled": True, "status": "available", "base_url": base, "ok": True, "model": ollama.get("model"), "model_ok": ollama.get("model") in models, "available_models": models}
        except Exception as exc:
            report["ollama"] = {"enabled": True, "status": "unavailable", "base_url": base, "ok": False, "model": ollama.get("model"), "model_ok": False, "error": str(exc)}
    _echo_json(report)


@app.command("init-config")
def init_config(out: Path = typer.Option(..., "--out", help="Output YAML config path.")) -> None:
    path = write_default_config(out)
    typer.echo(f"Wrote {path}")


@app.command("install-extras")
def install_extras(engine: str = typer.Option(..., "--engine", help="Install optional dependencies: pix2tex or texteller.")) -> None:
    """Install optional OCR dependencies into the current Python environment."""
    if engine == "pix2tex":
        cmd = [sys.executable, "-m", "pip", "install", "-e", ".[pix2tex]"]
    elif engine == "texteller":
        cmd = [sys.executable, "-m", "pip", "install", "-e", "external/TexTeller"]
        typer.echo("Installing TexTeller package from external/TexTeller ...")
        first = run_command(cmd, timeout=1200)
        if first.returncode != 0:
            _echo_json({"status": "failed", "cmd": first.cmd, "stdout": first.stdout, "stderr": first.stderr})
            raise typer.Exit(1)
        cmd = [sys.executable, "-m", "pip", "install", "-e", ".[texteller-deps]"]
    else:
        raise typer.BadParameter("engine must be pix2tex or texteller")
    result = run_command(cmd, timeout=1200)
    _echo_json({"status": "ok" if result.returncode == 0 else "failed", "cmd": result.cmd, "stdout": result.stdout[-3000:], "stderr": result.stderr[-3000:]})
    if result.returncode != 0:
        raise typer.Exit(1)


@app.command("config-show")
def config_show(config: Optional[Path] = typer.Option(None, "--config")) -> None:
    """Show merged config plus effective OCR engine plan."""
    cfg = _cfg(config)
    _echo_json({"config": cfg, "effective_ocr_engines": effective_ocr_engines(cfg), "candidate_priority_warnings": candidate_priority_warnings(cfg)})


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
    only_id: Optional[str] = typer.Option(None, "--only-id", help="Process one formula id, e.g. f0001."),
    limit: Optional[int] = typer.Option(None, "--limit", help="Process at most N formulas after id filters."),
    from_id: Optional[str] = typer.Option(None, "--from-id", help="Process formulas with id >= this value."),
    to_id: Optional[str] = typer.Option(None, "--to-id", help="Process formulas with id <= this value."),
) -> None:
    cfg = _cfg(config)
    if timeout_seconds is not None:
        cfg.setdefault("ollama", {})["timeout_seconds"] = timeout_seconds
    if dry_run:
        from .formula_filter import filter_formulas

        m = load_manifest(workdir)
        formulas = filter_formulas(list(m.get("formulas", [])), only_id=only_id, limit=limit, from_id=from_id, to_id=to_id)
        effective = effective_ocr_engines(cfg)
        engines = list(effective["will_run"])
        todo = {
            engine: [
                f["id"]
                for f in formulas
                if force
                or not any(
                    c.get("source") == engine
                    and c.get("validation_status") != "error"
                    and (c.get("latex") or "").strip()
                    for c in f.get("candidates", [])
                )
            ]
            for engine in engines
        }
        status_files = {
            f["id"]: {engine: str(WorkPaths.from_workdir(workdir).ocr_dir / f"{f['id']}_{engine}.json") for engine in engines}
            for f in formulas
        }
        _echo_json({"would_ocr": todo, "formula_count": len(formulas), "engines": engines, "effective_ocr_engines": effective, "status_files": status_files, "sequential": True})
        return
    m = run_ocr(workdir, cfg, force=force, progress=progress, verbose=verbose, only_id=only_id, limit=limit, from_id=from_id, to_id=to_id)
    typer.echo(f"OCR candidates recorded for {len(m.get('formulas', []))} formulas")


@app.command("add-docx2tex-candidates")
def add_docx2tex_candidates(workdir: Path = typer.Option(..., "--workdir"), docx2tex_tex: Path = typer.Option(..., "--docx2tex-tex"), config: Optional[Path] = typer.Option(None, "--config"), force: bool = typer.Option(False, "--force")) -> None:
    m = add_docx2tex_stage(workdir, docx2tex_tex, _cfg(config), force=force)
    typer.echo(f"docx2tex candidates processed; formulas={len(m.get('formulas', []))}")


@app.command("validate")
def validate(
    workdir: Path = typer.Option(..., "--workdir"),
    config: Optional[Path] = typer.Option(None, "--config"),
    force: bool = typer.Option(False, "--force"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    only_id: Optional[str] = typer.Option(None, "--only-id", help="Validate one formula id, e.g. f0001."),
    limit: Optional[int] = typer.Option(None, "--limit", help="Validate at most N formulas after id filters."),
    from_id: Optional[str] = typer.Option(None, "--from-id", help="Validate formulas with id >= this value."),
    to_id: Optional[str] = typer.Option(None, "--to-id", help="Validate formulas with id <= this value."),
) -> None:
    if dry_run:
        from .formula_filter import filter_formulas

        m = load_manifest(workdir)
        formulas = filter_formulas(list(m.get("formulas", [])), only_id=only_id, limit=limit, from_id=from_id, to_id=to_id)
        _echo_json({"formula_count": len(formulas), "candidate_count": sum(len(f.get("candidates", [])) for f in formulas)})
        return
    m = validate_manifest(workdir, _cfg(config), force=force, only_id=only_id, limit=limit, from_id=from_id, to_id=to_id)
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
def merge(
    workdir: Path = typer.Option(..., "--workdir"),
    config: Optional[Path] = typer.Option(None, "--config"),
    strict: bool = typer.Option(True, "--strict/--no-strict", help="Fail if any manifest formula WMF/EMF reference remains."),
) -> None:
    try:
        out = merge_stage(workdir, _cfg(config), strict=strict)
        typer.echo(f"Wrote {out}")
    except MergeInvariantError as exc:
        _echo_json({"status": "failed", "error": str(exc), "unresolved": exc.unresolved})
        raise typer.Exit(1)
    except RuntimeError as exc:
        _echo_json({"status": "failed", "error": str(exc)})
        raise typer.Exit(1)


@app.command("test-latex")
def test_latex(workdir: Path = typer.Option(..., "--workdir"), config: Optional[Path] = typer.Option(None, "--config")) -> None:
    """Compile a minimal Russian XeLaTeX document with monospace Cyrillic and math."""
    result = run_latex_smoke_test(workdir, _cfg(config))
    _echo_json(result)


@app.command("build")
def build_cmd(workdir: Path = typer.Option(..., "--workdir"), config: Optional[Path] = typer.Option(None, "--config"), force: bool = typer.Option(False, "--force")) -> None:
    try:
        result = build_stage(workdir, _cfg(config), force=force)
        _echo_json(result)
    except MergeInvariantError as exc:
        _echo_json({"status": "failed", "error": str(exc), "unresolved": exc.unresolved})
        raise typer.Exit(1)
    except RuntimeError as exc:
        _echo_json({"status": "failed", "error": str(exc)})
        raise typer.Exit(1)



def _formula_summary(manifest: dict) -> dict:
    formulas = list(manifest.get("formulas", []))
    unresolved_ids = [str(f.get("id")) for f in formulas if not (f.get("selected_latex") or "").strip()]
    return {
        "formula_total": len(formulas),
        "formula_selected": len(formulas) - len(unresolved_ids),
        "formula_unresolved": len(unresolved_ids),
        "unresolved_ids": unresolved_ids,
    }


@app.command("full")
def full(input_path: Path = typer.Option(..., "--input"), workdir: Path = typer.Option(..., "--workdir"), config: Optional[Path] = typer.Option(None, "--config"), force: bool = typer.Option(False, "--force")) -> None:
    cfg = _cfg(config)
    wp = WorkPaths.from_workdir(workdir)
    wp.ensure()
    try:
        run_pandoc_docx_to_markdown(input_path, workdir, cfg, force=force)
        manifest = create_manifest(wp.text_md, workdir, cfg, force=force)
        render_images_stage(workdir, cfg, force=force)
        run_ocr(workdir, cfg, force=force)
        validate_manifest(workdir, cfg, force=force)
        manifest = select_candidates(workdir, cfg)
        generate_report(workdir, cfg)
        merge_stage(workdir, cfg, strict=True)
        result = build_stage(workdir, cfg, force=force)
        summary = _formula_summary(manifest)
        status = "ok" if result.get("status") in {"ok", "skipped"} else "failed"
        _echo_json({"status": status, **summary, **result})
        if status == "failed":
            raise typer.Exit(1)
    except MergeInvariantError as exc:
        manifest = load_manifest(workdir) if wp.manifest_json.exists() else {"formulas": []}
        _echo_json({"status": "failed", **_formula_summary(manifest), "error": str(exc), "unresolved": exc.unresolved})
        raise typer.Exit(1)
    except RuntimeError as exc:
        manifest = load_manifest(workdir) if wp.manifest_json.exists() else {"formulas": []}
        _echo_json({"status": "failed", **_formula_summary(manifest), "error": str(exc)})
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
