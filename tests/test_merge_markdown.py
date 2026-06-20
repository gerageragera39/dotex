from pathlib import Path

from docx2xelatex.config import DEFAULT_CONFIG
from docx2xelatex.merge_markdown import merge_markdown
from docx2xelatex.utils import write_json


def test_merge_replaces_by_position(tmp_path: Path):
    text = "A ![](media/a.wmf) and ![](media/a.wmf)"
    md = tmp_path / "text.md"
    md.write_text(text, encoding="utf-8")
    first = text.index("![]")
    second = text.index("![]", first + 1)
    manifest = {
        "version": 1,
        "markdown": str(md),
        "workdir": str(tmp_path),
        "formulas": [
            {
                "id": "f0001",
                "original_match": "![](media/a.wmf)",
                "position": {"start": first, "end": first + len("![](media/a.wmf)")},
                "display_type": "inline",
                "selected_latex": "x_1",
            },
            {
                "id": "f0002",
                "original_match": "![](media/a.wmf)",
                "position": {"start": second, "end": second + len("![](media/a.wmf)")},
                "display_type": "inline",
                "selected_latex": None,
            },
        ],
    }
    (tmp_path / "formulas").mkdir()
    write_json(tmp_path / "formulas" / "manifest.json", manifest)
    out = merge_markdown(tmp_path, DEFAULT_CONFIG)
    final = out.read_text(encoding="utf-8")
    assert r"\(x_1\)" in final
    assert "TODO_FORMULA_f0002" in final
