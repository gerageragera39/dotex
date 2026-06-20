from __future__ import annotations

from copy import deepcopy

from docx2xelatex.config import DEFAULT_CONFIG
from docx2xelatex.engines.texteller_engine import texteller_status
from docx2xelatex.ocr_pipeline import effective_ocr_engines


def test_effective_ocr_skips_disabled_engine_even_if_requested(monkeypatch):
    cfg = deepcopy(DEFAULT_CONFIG)
    cfg["ocr"]["engines"] = ["texteller", "pix2tex", "ollama_qwen"]
    cfg["texteller"]["enabled"] = False
    cfg["ollama"]["enabled"] = False
    monkeypatch.setattr("docx2xelatex.ocr_pipeline.pix2tex_status", lambda: {"ok": True})
    effective = effective_ocr_engines(cfg)
    assert effective["will_run"] == ["pix2tex"]
    assert set(effective["disabled"]) == {"texteller", "ollama_qwen"}


def test_texteller_missing_optimum_has_install_hint(monkeypatch):
    cfg = deepcopy(DEFAULT_CONFIG)
    cfg["texteller"]["enabled"] = True
    monkeypatch.setattr("docx2xelatex.engines.texteller_engine.texteller_missing_modules", lambda: ["optimum"])
    status = texteller_status(cfg)
    assert status["status"] == "missing_dependencies"
    assert "optimum" in status["missing_modules"]
    assert 'pip install "optimum[onnxruntime]>=1.24.0"' == status["install_hint"]
    assert status["will_run"] is False
