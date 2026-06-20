from pathlib import Path

from docx2xelatex.config import DEFAULT_CONFIG
from docx2xelatex.manifest import create_manifest, parse_markdown_images


def test_parse_markdown_images_windows_paths_and_attrs():
    md = r'Text ![alt](C:\Users\Иван\work\media\image 4.wmf){width=1in} end'
    images = parse_markdown_images(md)
    assert len(images) == 1
    assert images[0].dest == r'C:\Users\Иван\work\media\image 4.wmf'
    assert images[0].attrs == "{width=1in}"
    assert images[0].original.endswith("{width=1in}")


def test_parse_markdown_images_balanced_parentheses():
    md = r'![](media/formula (old)/image(1).wmf)'
    images = parse_markdown_images(md)
    assert len(images) == 1
    assert images[0].dest == "media/formula (old)/image(1).wmf"


def test_create_manifest_formula_images(tmp_path: Path):
    (tmp_path / "media").mkdir()
    (tmp_path / "media" / "image1.wmf").write_bytes(b"fake")
    md = tmp_path / "text.md"
    md.write_text("Before\n\n![](media/image1.wmf)\n\nAfter", encoding="utf-8")
    manifest = create_manifest(md, tmp_path, DEFAULT_CONFIG, force=True)
    assert manifest["formulas"][0]["id"] == "f0001"
    assert manifest["formulas"][0]["display_type"] == "display"
    assert manifest["formulas"][0]["original_match"] == "![](media/image1.wmf)"
