from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from docx2xelatex.build_latex import LatexConfigError, pandoc_final_to_tex, render_latex_header, validate_latex_config
from docx2xelatex.config import DEFAULT_CONFIG


def test_generated_header_does_not_contain_both_babel_and_polyglossia():
    header = render_latex_header(DEFAULT_CONFIG)
    assert r"\usepackage{polyglossia}" in header
    assert "babel" not in header


def test_mathtools_appears_before_unicode_math_if_enabled():
    cfg = deepcopy(DEFAULT_CONFIG)
    cfg["latex"]["use_unicode_math"] = True
    header = render_latex_header(cfg)
    assert header.index(r"\usepackage{mathtools}") < header.index(r"\usepackage{unicode-math}")


def test_config_default_monofont_is_consolas():
    assert DEFAULT_CONFIG["latex"]["monofont"] == "Consolas"


def test_generated_header_contains_cyrillicfonttt():
    header = render_latex_header(DEFAULT_CONFIG)
    assert r"\newfontfamily\cyrillicfonttt{Consolas}[Script=Cyrillic]" in header


def test_latex_config_validation_rejects_babel_and_polyglossia_together():
    cfg = deepcopy(DEFAULT_CONFIG)
    cfg["latex"]["use_babel"] = True
    cfg["latex"]["use_polyglossia"] = True
    with pytest.raises(LatexConfigError):
        validate_latex_config(cfg)


def test_pandoc_xelatex_polyglossia_build_avoids_lang_and_font_variables(monkeypatch, tmp_path: Path):
    (tmp_path / "final.md").write_text("Тест", encoding="utf-8")
    captured = {}

    class Proc:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(cmd, text, stdout, stderr):
        captured["cmd"] = cmd
        (tmp_path / "final.tex").write_text("ok", encoding="utf-8")
        return Proc()

    monkeypatch.setattr("docx2xelatex.build_latex.subprocess.run", fake_run)
    pandoc_final_to_tex(tmp_path, DEFAULT_CONFIG, force=True)
    cmd = captured["cmd"]
    assert "-V" in cmd
    variables = [cmd[i + 1] for i, part in enumerate(cmd) if part == "-V"]
    assert "documentclass=article" in variables
    assert "fontsize=12pt" in variables
    assert not any(v.startswith("lang=") for v in variables)
    assert not any(v.startswith("mainfont=") for v in variables)
    assert not any(v.startswith("sansfont=") for v in variables)
    assert not any(v.startswith("monofont=") for v in variables)
