from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from docx2xelatex.build_latex import pandoc_final_to_tex
from docx2xelatex.config import DEFAULT_CONFIG
from docx2xelatex.merge_markdown import MergeInvariantError, merge_markdown
from docx2xelatex.utils import write_json


def _write_case(tmp_path: Path, markdown_image: str, *, selected: str | None = "x^2", image_path: str | None = None, png_path: str | None = None):
    text = f"Before\n\n{markdown_image}\n\nAfter"
    md = tmp_path / "text.md"
    md.write_text(text, encoding="utf-8")
    start = text.index(markdown_image)
    (tmp_path / "formulas").mkdir()
    (tmp_path / "formulas" / "png").mkdir(parents=True, exist_ok=True)
    manifest = {
        "version": 1,
        "markdown": str(md),
        "workdir": str(tmp_path),
        "formulas": [
            {
                "id": "f0006",
                "original_match": markdown_image,
                "markdown_path": "media/image6.wmf",
                "image_path": image_path or str(tmp_path / "media" / "image6.wmf"),
                "png_path": png_path or str(tmp_path / "formulas" / "png" / "f0006.png"),
                "display_type": "display",
                "position": {"start": start, "end": start + len(markdown_image)},
                "selected_latex": selected,
                "selected_source": "pix2tex" if selected else None,
                "validation_status": "valid" if selected else "invalid",
                "candidates": [],
            }
        ],
    }
    write_json(tmp_path / "formulas" / "manifest.json", manifest)
    return manifest


def test_merge_replaces_image_path_with_backslashes(tmp_path: Path):
    _write_case(tmp_path, r"![](media\image6.wmf)")
    out = merge_markdown(tmp_path, DEFAULT_CONFIG)
    final = out.read_text(encoding="utf-8")
    assert "image6.wmf" not in final
    assert "x^2" in final


def test_merge_replaces_image_path_with_forward_slashes(tmp_path: Path):
    _write_case(tmp_path, "![](media/image6.wmf)")
    final = merge_markdown(tmp_path, DEFAULT_CONFIG).read_text(encoding="utf-8")
    assert "image6.wmf" not in final
    assert "x^2" in final


def test_merge_replaces_absolute_path(tmp_path: Path):
    abs_path = tmp_path / "media" / "image6.wmf"
    _write_case(tmp_path, f"![]({abs_path})", image_path=str(abs_path))
    final = merge_markdown(tmp_path, DEFAULT_CONFIG).read_text(encoding="utf-8")
    assert "image6.wmf" not in final
    assert "x^2" in final


def test_merge_replaces_relative_build_media_path(tmp_path: Path):
    _write_case(tmp_path, "![](build/media/image6.wmf)")
    final = merge_markdown(tmp_path, DEFAULT_CONFIG).read_text(encoding="utf-8")
    assert "image6.wmf" not in final
    assert "x^2" in final


def test_merge_selected_latex_removes_image6_wmf(tmp_path: Path):
    _write_case(tmp_path, "![](media/image6.wmf)", selected=r"\\frac{a}{b}")
    final = merge_markdown(tmp_path, DEFAULT_CONFIG).read_text(encoding="utf-8")
    assert "image6.wmf" not in final
    assert r"\\frac{a}{b}" in final


def test_unresolved_formula_uses_png_todo_not_wmf(tmp_path: Path):
    _write_case(tmp_path, "![](media/image6.wmf)", selected=None)
    final = merge_markdown(tmp_path, DEFAULT_CONFIG).read_text(encoding="utf-8")
    assert "image6.wmf" not in final
    assert "formulas/png/f0006.png" in final
    assert "TODO_FORMULA_f0006" in final


def test_strict_merge_fails_if_manifest_formula_remains_wmf(tmp_path: Path):
    _write_case(tmp_path, "![](other/image7.wmf)")
    manifest_path = tmp_path / "formulas" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["formulas"][0]["markdown_path"] = "media/image6.wmf"
    manifest["formulas"][0]["image_path"] = str(tmp_path / "media" / "image6.wmf")
    manifest["formulas"][0]["original_match"] = "![](media/image6.wmf)"
    write_json(manifest_path, manifest)
    with pytest.raises(MergeInvariantError):
        merge_markdown(tmp_path, DEFAULT_CONFIG, strict=True)
    assert (tmp_path / "merge-unresolved.json").exists()


def test_build_refuses_final_md_with_formula_wmf_before_pandoc(tmp_path: Path, monkeypatch):
    _write_case(tmp_path, "![](media/image6.wmf)")
    (tmp_path / "final.md").write_text("![](media/image6.wmf)", encoding="utf-8")

    def fail_run(*args, **kwargs):
        raise AssertionError("pandoc must not run when final.md has formula WMF")

    monkeypatch.setattr("docx2xelatex.build_latex.run_command", fail_run)
    with pytest.raises(MergeInvariantError):
        pandoc_final_to_tex(tmp_path, DEFAULT_CONFIG, force=True)
