from __future__ import annotations

import json
from pathlib import Path

from docx2xelatex.config import DEFAULT_CONFIG
from docx2xelatex.engines.texteller_engine import _command_from_config, _extract_latex
from docx2xelatex.formula_filter import filter_formulas
from docx2xelatex.select_candidate import select_candidates


def test_default_multi_engine_config():
    assert DEFAULT_CONFIG["ocr"]["engines"] == ["pix2tex"]
    assert DEFAULT_CONFIG["pix2tex"]["enabled"] is True
    assert DEFAULT_CONFIG["texteller"]["enabled"] is False
    assert DEFAULT_CONFIG["ollama"]["enabled"] is False
    assert DEFAULT_CONFIG["candidate_selection"]["priority"] == ["pix2tex", "texteller", "ollama_qwen", "docx2tex"]
    assert DEFAULT_CONFIG["ollama"]["timeout_seconds"] == 1200


def test_filter_formulas_by_id_range_and_limit():
    formulas = [{"id": f"f{i:04d}"} for i in range(1, 6)]
    assert [f["id"] for f in filter_formulas(formulas, from_id="f0002", to_id="f0004", limit=2)] == ["f0002", "f0003"]
    assert [f["id"] for f in filter_formulas(formulas, only_id="f0005")] == ["f0005"]


def test_select_first_valid_candidate_by_priority(tmp_path: Path):
    manifest = {
        "formulas": [
            {
                "id": "f0001",
                "candidates": [
                    {"source": "ollama_qwen", "latex": "o", "validation_status": "valid"},
                    {"source": "pix2tex", "latex": "p", "validation_status": "valid"},
                    {"source": "texteller", "latex": "", "validation_status": "invalid"},
                ],
            }
        ]
    }
    formulas = tmp_path / "formulas"
    formulas.mkdir()
    (formulas / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    selected = select_candidates(tmp_path, DEFAULT_CONFIG)
    formula = selected["formulas"][0]
    assert formula["selected_source"] == "pix2tex"
    assert formula["selected_latex"] == "p"


def test_texteller_output_extraction_and_configured_command():
    stdout = "Predicted LaTeX: ```\n\\frac{a}{b}\n```\n"
    assert _extract_latex(stdout) == r"\frac{a}{b}"
    cfg = {"texteller": {"command": ["python", "-m", "texteller.cli", "inference", "{image_path}"]}}
    assert _command_from_config(cfg, "x.png") == ["python", "-m", "texteller.cli", "inference", "x.png"]
