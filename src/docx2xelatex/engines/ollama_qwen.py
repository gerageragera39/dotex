from __future__ import annotations

import base64
import json
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Iterable, Iterator, TypeVar

from ..latex_clean import clean_latex_candidate
from ..manifest import load_manifest, save_manifest
from ..paths import WorkPaths
from ..subprocess_utils import run_command
from ..utils import write_json
from .base import Candidate, has_candidate

FORMULA_OCR_PROMPT = """You are a mathematical OCR engine.

Convert the formula in the image to LaTeX.

Rules:
- Return ONLY LaTeX.
- Do NOT include explanations.
- Do NOT include Markdown fences.
- Do NOT include $...$, \\( ... \\), or \\[ ... \\] delimiters.
- Preserve Greek letters, indices, superscripts, fractions, matrices, brackets.
- Use standard LaTeX compatible with amsmath.
- If the formula is multiline, use \\begin{aligned} ... \\end{aligned}.
- If you are uncertain, still output the best LaTeX approximation.
"""

T = TypeVar("T")


def _require_localhost(base_url: str) -> None:
    parsed = urllib.parse.urlparse(base_url)
    host = parsed.hostname or ""
    if host not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError(f"Refusing non-local Ollama URL: {base_url}. Only localhost is allowed.")


def _progress(items: list[T], enabled: bool, desc: str) -> Iterable[T]:
    if not enabled:
        return items
    try:
        from tqdm.auto import tqdm

        return tqdm(items, desc=desc, unit="formula", dynamic_ncols=True)
    except Exception:
        total = len(items)

        def iterator() -> Iterator[T]:
            for idx, item in enumerate(items, start=1):
                fid = item.get("id", "?") if isinstance(item, dict) else "?"
                print(f"[{idx}/{total}] {desc}: {fid}", file=sys.stderr, flush=True)
                yield item

        return iterator()


def _prepare_ocr_image(png_path: Path, formula_id: str, wp: WorkPaths, config: dict[str, Any]) -> Path:
    """Optionally create a bounded-size OCR input image.

    Quality-first default is to use the original rendered PNG. Resizing is opt-in
    because small/blank OCR outputs are worse than slow but faithful OCR.
    """
    ollama = config.get("ollama", {})
    if not bool(ollama.get("resize_image", False)):
        return png_path
    max_side = int(ollama.get("max_image_side", 1600) or 0)
    if max_side <= 0:
        return png_path
    out_dir = wp.ocr_dir / "input"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{formula_id}.png"
    if out.exists() and out.stat().st_mtime >= png_path.stat().st_mtime:
        return out
    if shutil.which("magick") is None:
        return png_path
    cmd = [
        "magick",
        str(png_path),
        "-background",
        str(config.get("images", {}).get("background", "white")),
        "-alpha",
        "remove",
        "-alpha",
        "off",
        "-resize",
        f"{max_side}x{max_side}>",
        str(out),
    ]
    proc = run_command(cmd)
    if proc.returncode != 0 or not out.exists():
        return png_path
    return out


class OllamaQwenEngine:
    source = "ollama_qwen"

    def __init__(self, config: dict[str, Any]):
        ollama = config.get("ollama", {})
        self.base_url = str(ollama.get("base_url", "http://localhost:11434")).rstrip("/")
        _require_localhost(self.base_url)
        self.model = str(ollama.get("model", "qwen3-vl:8b"))
        self.timeout = int(ollama.get("timeout_seconds", 180))
        self.temperature = float(ollama.get("temperature", 0))
        self.num_predict = ollama.get("num_predict", None)

    def recognize(self, image_path: str | Path) -> Candidate:
        image_bytes = Path(image_path).read_bytes()
        options: dict[str, Any] = {"temperature": self.temperature}
        if self.num_predict is not None:
            options["num_predict"] = int(self.num_predict)
        payload = {
            "model": self.model,
            "prompt": FORMULA_OCR_PROMPT,
            "images": [base64.b64encode(image_bytes).decode("ascii")],
            "stream": False,
            "options": options,
        }
        req = urllib.request.Request(
            f"{self.base_url}/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        raw = data.get("response", "")
        return Candidate(source=self.source, latex=clean_latex_candidate(raw), raw=raw)






def _has_usable_candidate(formula: dict[str, Any], source: str) -> bool:
    for candidate in formula.get("candidates", []):
        if candidate.get("source") != source:
            continue
        if candidate.get("validation_status") == "error":
            continue
        if (candidate.get("latex") or "").strip():
            return True
    return False

def _candidate_empty_reason(candidate: Candidate) -> str | None:
    raw = (candidate.raw or "").strip()
    latex = (candidate.latex or "").strip()
    if not raw:
        return "empty raw response from Ollama"
    if not latex:
        return "empty LaTeX after cleaning; inspect raw OCR response"
    return None

def _write_ocr_status(raw_path: Path, payload: dict[str, Any]) -> None:
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(raw_path, {"source": "ollama_qwen", **payload})


def run_ocr(
    workdir: str | Path,
    config: dict[str, Any],
    force: bool = False,
    progress: bool | None = None,
    verbose: bool = False,
) -> dict[str, Any]:
    wp = WorkPaths.from_workdir(workdir)
    wp.ensure()
    manifest = load_manifest(workdir)
    ollama_cfg = config.get("ollama", {})
    if not ollama_cfg.get("enabled", True):
        return manifest
    engine = OllamaQwenEngine(config)
    force = force or bool(ollama_cfg.get("force", False))
    if progress is None:
        progress = bool(ollama_cfg.get("progress", True))

    formulas = list(manifest.get("formulas", []))
    total = len(formulas)
    pending = [f for f in formulas if force or not _has_usable_candidate(f, engine.source)]
    skipped = total - len(pending)
    if progress:
        print(
            f"OCR: total={total}, pending={len(pending)}, skipped_existing={skipped}, "
            f"model={engine.model}, sequential=true",
            file=sys.stderr,
            flush=True,
        )
        print(
            "OCR status files are written before each Ollama request: "
            f"{wp.ocr_dir / '<formula>_ollama_qwen.json'}",
            file=sys.stderr,
            flush=True,
        )

    for formula in _progress(formulas, bool(progress), "Ollama OCR"):
        raw_path = wp.ocr_dir / f"{formula['id']}_ollama_qwen.json"
        if _has_usable_candidate(formula, engine.source) and not force:
            if not raw_path.exists():
                existing = next((c for c in formula.get("candidates", []) if c.get("source") == engine.source), {})
                _write_ocr_status(
                    raw_path,
                    {
                        "status": "skipped_existing",
                        "formula_id": formula["id"],
                        "latex": existing.get("latex", ""),
                        "note": "Candidate already exists in manifest; use --force to re-run OCR.",
                    },
                )
            if verbose:
                print(f"skip {formula['id']}: existing candidate", file=sys.stderr, flush=True)
            continue
        if force or has_candidate(formula, engine.source):
            formula["candidates"] = [c for c in formula.get("candidates", []) if c.get("source") != engine.source]
        png = Path(formula.get("png_path") or "")
        if not png.exists():
            error = f"PNG not found: {png}"
            formula.setdefault("candidates", []).append(
                Candidate(source=engine.source, latex="", raw=None, validation_status="error", validation_error=error).to_dict()
            )
            _write_ocr_status(raw_path, {"status": "error", "formula_id": formula["id"], "error": error, "started_at": time.time(), "finished_at": time.time()})
            save_manifest(workdir, manifest)
            continue
        started_at = time.time()
        try:
            ocr_image = _prepare_ocr_image(png, formula["id"], wp, config)
            _write_ocr_status(
                raw_path,
                {
                    "status": "running",
                    "formula_id": formula["id"],
                    "model": engine.model,
                    "png_path": str(png),
                    "ocr_image_path": str(ocr_image),
                    "started_at": started_at,
                },
            )
            if verbose:
                print(f"start {formula['id']}: {ocr_image}", file=sys.stderr, flush=True)
            candidate = engine.recognize(ocr_image)
            empty_reason = _candidate_empty_reason(candidate)
            retried_original = False
            if (
                empty_reason
                and bool(ollama_cfg.get("retry_empty_with_original", True))
                and ocr_image.resolve() != png.resolve()
            ):
                if verbose or progress:
                    print(
                        f"retry {formula['id']}: {empty_reason}; retrying original PNG",
                        file=sys.stderr,
                        flush=True,
                    )
                _write_ocr_status(
                    raw_path,
                    {
                        "status": "retrying_original",
                        "formula_id": formula["id"],
                        "model": engine.model,
                        "png_path": str(png),
                        "ocr_image_path": str(ocr_image),
                        "error": empty_reason,
                        "started_at": started_at,
                    },
                )
                candidate = engine.recognize(png)
                retried_original = True
                empty_reason = _candidate_empty_reason(candidate)
            if empty_reason:
                candidate.validation_status = "error"
                candidate.validation_error = empty_reason
            elapsed = time.time() - started_at
            _write_ocr_status(
                raw_path,
                {
                    "status": "done" if not empty_reason else "empty_latex",
                    "formula_id": formula["id"],
                    "model": engine.model,
                    "png_path": str(png),
                    "ocr_image_path": str(ocr_image),
                    "retried_original": retried_original,
                    "elapsed_seconds": round(elapsed, 3),
                    "raw": candidate.raw,
                    "latex": candidate.latex,
                    "raw_length": len(candidate.raw or ""),
                    "latex_length": len(candidate.latex or ""),
                    "error": empty_reason,
                    "started_at": started_at,
                    "finished_at": time.time(),
                },
            )
            formula.setdefault("candidates", []).append(candidate.to_dict())
            save_manifest(workdir, manifest)
            if verbose:
                msg = "done" if not empty_reason else "empty"
                print(f"{msg} {formula['id']}: {elapsed:.1f}s", file=sys.stderr, flush=True)
        except (urllib.error.URLError, TimeoutError, Exception) as exc:
            elapsed = time.time() - started_at
            formula.setdefault("candidates", []).append(
                Candidate(source=engine.source, latex="", raw=None, validation_status="error", validation_error=str(exc)).to_dict()
            )
            _write_ocr_status(
                raw_path,
                {
                    "status": "error",
                    "formula_id": formula["id"],
                    "model": engine.model,
                    "png_path": str(png),
                    "elapsed_seconds": round(elapsed, 3),
                    "error": str(exc),
                    "started_at": started_at,
                    "finished_at": time.time(),
                },
            )
            save_manifest(workdir, manifest)
            if verbose or progress:
                print(f"error {formula['id']}: {exc}", file=sys.stderr, flush=True)
    save_manifest(workdir, manifest)
    return manifest
