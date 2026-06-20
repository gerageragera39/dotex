from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class WorkPaths:
    root: Path

    @classmethod
    def from_workdir(cls, workdir: str | Path) -> "WorkPaths":
        root = Path(workdir).expanduser().resolve()
        return cls(root=root)

    @property
    def text_md(self) -> Path:
        return self.root / "text.md"

    @property
    def media_dir(self) -> Path:
        return self.root / "media"

    @property
    def formulas_dir(self) -> Path:
        return self.root / "formulas"

    @property
    def manifest_json(self) -> Path:
        return self.formulas_dir / "manifest.json"

    @property
    def png_dir(self) -> Path:
        return self.formulas_dir / "png"

    @property
    def ocr_dir(self) -> Path:
        return self.formulas_dir / "ocr"

    @property
    def validate_dir(self) -> Path:
        return self.formulas_dir / "validate"

    @property
    def report_dir(self) -> Path:
        return self.root / "report"

    @property
    def report_html(self) -> Path:
        return self.report_dir / "formulas.html"

    @property
    def final_md(self) -> Path:
        return self.root / "final.md"

    @property
    def final_tex(self) -> Path:
        return self.root / "final.tex"

    @property
    def final_pdf(self) -> Path:
        return self.root / "final.pdf"

    def ensure(self) -> None:
        for p in [self.root, self.media_dir, self.formulas_dir, self.png_dir, self.ocr_dir, self.validate_dir, self.report_dir]:
            p.mkdir(parents=True, exist_ok=True)
