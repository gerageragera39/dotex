from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

from docx2xelatex.config import DEFAULT_CONFIG
from docx2xelatex.engines.base import Candidate
from docx2xelatex.ocr_pipeline import run_ocr
from docx2xelatex.utils import write_json


def test_run_ocr_uses_parallel_workers(tmp_path: Path, monkeypatch):
    png_dir = tmp_path / "formulas" / "png"
    png_dir.mkdir(parents=True)
    formulas = []
    for i in range(4):
        png = png_dir / f"f{i+1:04d}.png"
        png.write_bytes(b"not really an image")
        formulas.append({"id": f"f{i+1:04d}", "png_path": str(png), "candidates": []})
    write_json(tmp_path / "formulas" / "manifest.json", {"version": 1, "workdir": str(tmp_path), "formulas": formulas})

    active = 0
    max_active = 0
    lock = threading.Lock()

    class FakeEngine:
        source = "pix2tex"

        def __init__(self, config: dict[str, Any]):
            pass

        def recognize(self, image_path: str | Path) -> Candidate:
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
            time.sleep(0.05)
            with lock:
                active -= 1
            return Candidate(source="pix2tex", latex="x", raw="x")

    monkeypatch.setattr("docx2xelatex.ocr_pipeline.pix2tex_status", lambda: {"ok": True})
    monkeypatch.setattr("docx2xelatex.ocr_pipeline._create_engine", lambda source, config: FakeEngine(config))
    cfg = {**DEFAULT_CONFIG, "ocr": {"engines": ["pix2tex"], "max_workers": 3}, "pix2tex": {"enabled": True}}
    manifest = run_ocr(tmp_path, cfg, force=True, progress=False)
    assert max_active > 1
    assert sum(len(f.get("candidates", [])) for f in manifest["formulas"]) == 4
