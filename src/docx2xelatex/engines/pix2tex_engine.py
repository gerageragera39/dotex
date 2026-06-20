from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

from ..latex_clean import clean_latex_candidate
from .base import Candidate


class Pix2TexUnavailable(RuntimeError):
    pass


def _pix2tex_api_available() -> bool:
    try:
        return importlib.util.find_spec("pix2tex") is not None and importlib.util.find_spec("pix2tex.cli") is not None
    except ModuleNotFoundError:
        return False


def pix2tex_status() -> dict[str, Any]:
    ok = _pix2tex_api_available()
    return {
        "enabled_dependency": ok,
        "ok": ok,
        "warning": None if ok else "pix2tex is not installed; install optional dependency with `pip install pix2tex[gui]` or `pip install pix2tex`.",
    }


class Pix2TexEngine:
    source = "pix2tex"

    def __init__(self, config: dict[str, Any]):
        pix_cfg = config.get("pix2tex", {})
        self.timeout = int(pix_cfg.get("timeout_seconds", 180))
        self._model = None
        if not _pix2tex_api_available():
            raise Pix2TexUnavailable("pix2tex is not installed")

    def _load_model(self):
        if self._model is None:
            from pix2tex.cli import LatexOCR  # type: ignore[import-not-found]

            self._model = LatexOCR()
        return self._model

    def recognize(self, image_path: str | Path) -> Candidate:
        model = self._load_model()
        path = Path(image_path)
        raw: str
        try:
            from PIL import Image  # type: ignore[import-not-found]

            with Image.open(path) as image:
                raw = str(model(image))
        except Exception:
            # Some pix2tex releases accept a path-like value directly; keep this
            # fallback so the adapter remains compatible across versions.
            raw = str(model(str(path)))
        return Candidate(source=self.source, latex=clean_latex_candidate(raw), raw=raw)
