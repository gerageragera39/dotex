from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from .manifest import load_manifest, save_manifest
from .paths import WorkPaths
from .subprocess_utils import run_command


def render_images(workdir: str | Path, config: dict[str, Any], force: bool = False) -> dict[str, Any]:
    wp = WorkPaths.from_workdir(workdir)
    wp.ensure()
    manifest = load_manifest(workdir)
    img_cfg = config.get("images", {})
    density = str(img_cfg.get("imagemagick_density", 900))
    background = str(img_cfg.get("background", "white"))
    trim = bool(img_cfg.get("trim", True))
    for formula in manifest.get("formulas", []):
        src = Path(formula["image_path"])
        dst = Path(formula.get("png_path") or (wp.png_dir / f"{formula['id']}.png"))
        formula["png_path"] = str(dst)
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists() and not force:
            formula["png_status"] = "exists"
            continue
        if not src.exists():
            formula["png_status"] = "missing_source"
            formula["png_error"] = f"Image not found: {src}"
            continue
        try:
            if src.suffix.lower() == ".png":
                shutil.copy2(src, dst)
            else:
                cmd = ["magick", "-density", density, str(src), "-background", background, "-alpha", "remove", "-alpha", "off"]
                if trim:
                    cmd.extend(["-trim", "+repage"])
                cmd.append(str(dst))
                proc = run_command(cmd)
                if proc.returncode != 0:
                    raise RuntimeError(proc.stderr or proc.stdout or f"magick exited {proc.returncode}")
            formula["png_status"] = "ok"
            formula["png_error"] = None
        except Exception as exc:  # keep document-level pipeline alive
            formula["png_status"] = "error"
            formula["png_error"] = str(exc)
    save_manifest(workdir, manifest)
    return manifest
