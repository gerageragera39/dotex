from __future__ import annotations

from pathlib import Path
from typing import Any


def visual_similarity(original_png: str | Path | None, preview_png: str | Path | None, size: tuple[int, int] = (160, 80)) -> float | None:
    if not original_png or not preview_png:
        return None
    a = Path(original_png)
    b = Path(preview_png)
    if not a.exists() or not b.exists():
        return None
    try:
        from PIL import Image, ImageChops  # type: ignore[import-not-found]

        def load(path: Path):
            im = Image.open(path).convert("L")
            # Put dark ink on white background and normalize to common canvas.
            im.thumbnail(size)
            canvas = Image.new("L", size, 255)
            canvas.paste(im, ((size[0] - im.width) // 2, (size[1] - im.height) // 2))
            return canvas

        im1 = load(a)
        im2 = load(b)
        diff = ImageChops.difference(im1, im2)
        hist = diff.histogram()
        total = size[0] * size[1]
        mad = sum(value * count for value, count in enumerate(hist)) / (255.0 * total)
        return max(0.0, min(1.0, 1.0 - mad))
    except Exception:
        return None


def score_candidate_visual(formula: dict[str, Any], candidate: dict[str, Any]) -> float | None:
    preview = (candidate.get("artifacts") or {}).get("preview_png") or candidate.get("preview_png")
    score = visual_similarity(formula.get("png_path"), preview)
    if score is not None:
        candidate["visual_score"] = round(float(score), 4)
    return score
