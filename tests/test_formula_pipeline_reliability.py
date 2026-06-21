from __future__ import annotations

import json
import threading
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from http.server import ThreadingHTTPServer

import pytest

from docx2xelatex.audit import audit_workdir
from docx2xelatex.config import DEFAULT_CONFIG
from docx2xelatex.latex_clean import generate_repair_candidates
from docx2xelatex.latex_validate import validate_formula_candidate
from docx2xelatex.manifest import set_display_type_manual
from docx2xelatex.merge_markdown import Replacement, merge_markdown, validate_replacements_no_overlap
from docx2xelatex.review_server import ReviewHandler
from docx2xelatex.select_candidate import compile_manual_candidate, is_bad_candidate, select_candidate, select_candidates
from docx2xelatex.utils import write_json
from docx2xelatex.visual_compare import visual_similarity


def _manifest(tmp_path: Path, text: str, formulas: list[dict]) -> Path:
    md = tmp_path / "text.md"
    md.write_text(text, encoding="utf-8")
    (tmp_path / "formulas" / "png").mkdir(parents=True)
    data = {"version": 1, "markdown": str(md), "workdir": str(tmp_path), "formulas": formulas}
    write_json(tmp_path / "formulas" / "manifest.json", data)
    return md


def test_duplicate_image_path_merge_preserves_exact_text(tmp_path: Path):
    text = "A ![](media/a.wmf) and ![](media/a.wmf) after"
    first = text.index("![]")
    second = text.index("![]", first + 1)
    _manifest(
        tmp_path,
        text,
        [
            {"id": "f0001", "original_match": "![](media/a.wmf)", "markdown_path": "media/a.wmf", "png_path": str(tmp_path / "formulas/png/f0001.png"), "position": {"start": first, "end": first + len("![](media/a.wmf)")}, "display_type": "inline", "selected_latex": "x_1"},
            {"id": "f0002", "original_match": "![](media/a.wmf)", "markdown_path": "media/a.wmf", "png_path": str(tmp_path / "formulas/png/f0002.png"), "position": {"start": second, "end": second + len("![](media/a.wmf)")}, "display_type": "inline", "selected_latex": None},
        ],
    )
    final = merge_markdown(tmp_path, DEFAULT_CONFIG).read_text(encoding="utf-8")
    assert final == "A \\(x_1\\) and ![](formulas/png/f0002.png)\n<!-- TODO_FORMULA_f0002: formula OCR/validation failed; PNG preview kept instead of WMF/EMF. --> after"


def test_validate_replacements_no_overlap_detects_overlap():
    problems = validate_replacements_no_overlap([Replacement(0, 5, "a", "f1"), Replacement(4, 8, "b", "f2")])
    assert problems and problems[0]["reason"] == "overlapping replacements"


def test_validation_latex_hash_invalidates_stale_artifacts(tmp_path: Path, monkeypatch):
    import docx2xelatex.latex_validate as lv

    calls = []

    def fake_run(cmd, cwd=None, timeout=None, **kwargs):
        calls.append(cmd)
        tex = Path(cwd) / cmd[-1]
        tex.with_suffix(".pdf").write_bytes(b"pdf")
        tex.with_suffix(".log").write_text("ok", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="", cmd=cmd, timed_out=False)

    monkeypatch.setattr(lv.shutil, "which", lambda name: "/bin/true")
    monkeypatch.setattr(lv, "run_command", fake_run)
    monkeypatch.setattr(lv, "render_pdf_preview", lambda *a, **k: None)
    r1 = validate_formula_candidate("x", "f0001", "pix2tex", 1, tmp_path, DEFAULT_CONFIG)
    r1b = validate_formula_candidate("x", "f0001", "pix2tex", 1, tmp_path, DEFAULT_CONFIG)
    r2 = validate_formula_candidate("y", "f0001", "pix2tex", 1, tmp_path, DEFAULT_CONFIG)
    assert r1["latex_hash"] == r1b["latex_hash"]
    assert r2["latex_hash"] != r1["latex_hash"]
    assert len(calls) == 2
    assert r1["tex"] != r2["tex"]


def test_inline_and_display_validation_wrappers(tmp_path: Path, monkeypatch):
    import docx2xelatex.latex_validate as lv

    monkeypatch.setattr(lv.shutil, "which", lambda name: "/bin/true")
    monkeypatch.setattr(lv, "render_pdf_preview", lambda *a, **k: None)

    def fake_run(cmd, cwd=None, timeout=None, **kwargs):
        tex = Path(cwd) / cmd[-1]
        tex.with_suffix(".pdf").write_bytes(b"pdf")
        tex.with_suffix(".log").write_text("ok", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="", cmd=cmd, timed_out=False)

    monkeypatch.setattr(lv, "run_command", fake_run)
    inline = validate_formula_candidate("x+1", "f1", "src", 1, tmp_path, DEFAULT_CONFIG, display_type="inline", force=True)
    display = validate_formula_candidate("x+1", "f2", "src", 1, tmp_path, DEFAULT_CONFIG, display_type="display", force=True)
    assert "Текст до \\( x+1 \\) текст после." in Path(inline["tex"]).read_text(encoding="utf-8")
    assert "\\[\nx+1\n\\]" in Path(display["tex"]).read_text(encoding="utf-8")


def test_repair_candidate_and_bad_original_rejected():
    bad = r"\(s \in S\)htarrow A^{}\{1\}=Y"
    assert is_bad_candidate({"latex": bad}, DEFAULT_CONFIG)[0]
    repairs = generate_repair_candidates(bad)
    assert any(r"\rightarrow" in r and r"A^{}" not in r for r in repairs)


def test_manual_candidate_compile_and_select_survives_auto_select(tmp_path: Path, monkeypatch):
    text = "![](media/a.wmf)"
    _manifest(tmp_path, text, [{"id": "f0001", "original_match": text, "markdown_path": "media/a.wmf", "png_path": str(tmp_path / "formulas/png/f0001.png"), "position": {"start": 0, "end": len(text)}, "display_type": "inline", "candidates": []}])
    import docx2xelatex.select_candidate as sc

    monkeypatch.setattr(sc, "validate_formula_candidate", lambda *a, **k: {"status": "valid", "error": None, "latex_hash": "h", "tex": "t", "pdf": "p", "log": "l", "preview_png": "prev.png"})
    compiled = compile_manual_candidate(tmp_path, "f0001", "x", DEFAULT_CONFIG)
    selected = select_candidate(tmp_path, "f0001", candidate_key=compiled["candidate_key"])
    assert selected["selected_source"] == "manual"
    m = select_candidates(tmp_path, DEFAULT_CONFIG)
    assert m["formulas"][0]["selected_source"] == "manual"


def test_visual_score_selection_prefers_better_preview(tmp_path: Path):
    Image = pytest.importorskip("PIL.Image")
    orig = tmp_path / "orig.png"
    same = tmp_path / "same.png"
    diff = tmp_path / "diff.png"
    Image.new("L", (20, 10), 255).save(orig)
    Image.new("L", (20, 10), 255).save(same)
    Image.new("L", (20, 10), 0).save(diff)
    assert visual_similarity(orig, same) > visual_similarity(orig, diff)
    _manifest(
        tmp_path,
        "![](media/a.wmf)",
        [{"id": "f0001", "png_path": str(orig), "selected_latex": None, "candidates": [
            {"source": "pix2tex", "latex": "bad", "validation_status": "valid", "artifacts": {"preview_png": str(diff)}},
            {"source": "texteller", "latex": "good", "validation_status": "valid", "artifacts": {"preview_png": str(same)}},
        ]}],
    )
    m = select_candidates(tmp_path, DEFAULT_CONFIG, force_auto_select=True)
    assert m["formulas"][0]["selected_latex"] == "good"


def test_texteller_stdout_parser_ignores_noise():
    from docx2xelatex.engines.texteller_engine import _extract_latex

    noisy = "Loading model\n50%|#####| 1/2\nPredicted LaTeX: x^2 + y^2\nfooter done"
    assert _extract_latex(noisy) == "x^2 + y^2"


def test_display_type_manual_override_affects_merge(tmp_path: Path):
    text = "A ![](media/a.wmf)"
    _manifest(tmp_path, text, [{"id": "f0001", "original_match": "![](media/a.wmf)", "markdown_path": "media/a.wmf", "position": {"start": 2, "end": len(text)}, "display_type_auto": "inline", "display_type": "inline", "selected_latex": "x"}])
    manifest = json.loads((tmp_path / "formulas/manifest.json").read_text(encoding="utf-8"))
    set_display_type_manual(manifest["formulas"][0], "display")
    write_json(tmp_path / "formulas/manifest.json", manifest)
    final = merge_markdown(tmp_path, DEFAULT_CONFIG).read_text(encoding="utf-8")
    assert "\\[\nx\n\\]" in final


def test_review_api_compile_endpoint(tmp_path: Path, monkeypatch):
    text = "![](media/a.wmf)"
    _manifest(tmp_path, text, [{"id": "f0001", "original_match": text, "markdown_path": "media/a.wmf", "png_path": str(tmp_path / "formulas/png/f0001.png"), "position": {"start": 0, "end": len(text)}, "display_type": "inline", "candidates": []}])
    import docx2xelatex.review_server as rs

    monkeypatch.setattr(rs, "compile_manual_candidate", lambda *a, **k: {"validation_status": "valid", "validation_error": None, "latex_hash": "abc", "candidate_key": "manual:1", "artifacts": {"preview_png": str(tmp_path / "p.png")}})
    server = ThreadingHTTPServer(("127.0.0.1", 0), ReviewHandler)
    server.wp = SimpleNamespace(root=tmp_path, manifest_json=tmp_path / "formulas/manifest.json")
    server.config = DEFAULT_CONFIG
    th = threading.Thread(target=server.serve_forever, daemon=True)
    th.start()
    try:
        body = json.dumps({"latex": "x"}).encode()
        req = urllib.request.Request(f"http://127.0.0.1:{server.server_port}/api/formulas/f0001/compile", data=body, headers={"Content-Type": "application/json"}, method="POST")
        data = json.loads(urllib.request.urlopen(req, timeout=5).read().decode())
        assert data["validation_status"] == "valid"
        assert data["latex_hash"] == "abc"
    finally:
        server.shutdown()
        server.server_close()


def test_audit_reports_stale_artifacts(tmp_path: Path):
    tex = tmp_path / "formulas/validate/f0001/candidate_src_1_oldhash.tex"
    tex.parent.mkdir(parents=True)
    tex.write_text("old", encoding="utf-8")
    _manifest(tmp_path, "text", [{"id": "f0001", "selected_latex": "x", "selected_source": "pix2tex", "validation_status": "valid", "candidates": [{"source": "pix2tex", "latex": "x", "validation_status": "valid", "latex_hash": "stale", "artifacts": {"tex": str(tex)}}]}])
    result = audit_workdir(tmp_path, {**DEFAULT_CONFIG, "latex": {**DEFAULT_CONFIG["latex"], "build_pdf": False}})
    assert result["candidates_with_stale_artifacts"]
