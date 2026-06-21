from __future__ import annotations

import shutil
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Iterable, Iterator, TypeVar

from .engines.base import Candidate, FormulaEngine, has_candidate
from .engines.ollama_qwen import OllamaQwenEngine, _prepare_ocr_image
from .engines.pix2tex_engine import Pix2TexEngine, pix2tex_status
from .engines.texteller_engine import TexTellerEngine, texteller_status
from .formula_filter import filter_formulas
from .manifest import load_manifest, save_manifest
from .paths import WorkPaths
from .subprocess_utils import run_command
from .utils import write_json

T = TypeVar("T")

DEFAULT_OCR_ENGINES = ["pix2tex"]

ENGINE_CONFIG: dict[str, tuple[str, type[FormulaEngine]]] = {
    "texteller": ("texteller", TexTellerEngine),
    "pix2tex": ("pix2tex", Pix2TexEngine),
    "ollama_qwen": ("ollama", OllamaQwenEngine),
}


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


def configured_engine_names(config: dict[str, Any]) -> list[str]:
    names = config.get("ocr", {}).get("engines", DEFAULT_OCR_ENGINES)
    return [str(name) for name in names]


def _engine_enabled(config: dict[str, Any], source: str) -> bool:
    config_key, _ = ENGINE_CONFIG[source]
    return bool(config.get(config_key, {}).get("enabled", True))


def engine_availability(source: str, config: dict[str, Any]) -> tuple[bool, str | None]:
    if source == "pix2tex":
        status = pix2tex_status()
        return bool(status.get("ok")), status.get("warning")
    if source == "texteller":
        status = texteller_status(config)
        return bool(status.get("ok")), status.get("warning")
    if source == "ollama_qwen":
        # Ollama connectivity/model availability is checked by doctor; OCR request
        # itself records per-formula errors if the local server is unavailable.
        return True, None
    return False, f"Unknown OCR engine: {source}"


def effective_ocr_engines(config: dict[str, Any]) -> dict[str, Any]:
    requested = configured_engine_names(config)
    disabled: list[str] = []
    unavailable: list[dict[str, str | None]] = []
    enabled_and_available: list[str] = []
    unknown: list[str] = []
    for source in requested:
        if source not in ENGINE_CONFIG:
            unknown.append(source)
            unavailable.append({"engine": source, "reason": "unknown OCR engine"})
            continue
        if not _engine_enabled(config, source):
            disabled.append(source)
            continue
        ok, reason = engine_availability(source, config)
        if ok:
            enabled_and_available.append(source)
        else:
            unavailable.append({"engine": source, "reason": reason})
    return {
        "requested": requested,
        "enabled_and_available": enabled_and_available,
        "disabled": disabled,
        "unavailable": unavailable,
        "unknown": unknown,
        "will_run": enabled_and_available,
    }




def candidate_priority_warnings(config: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    priority = [str(x) for x in config.get("candidate_selection", {}).get("priority", [])]
    effective = effective_ocr_engines(config)
    disabled = set(effective.get("disabled", []))
    unavailable = {str(item.get("engine")): item.get("reason") for item in effective.get("unavailable", [])}
    for source in priority:
        if source in disabled:
            warnings.append(f"candidate_selection.priority contains disabled engine {source}; existing candidates can still be selected, but OCR will not run it.")
        elif source in unavailable:
            warnings.append(f"candidate_selection.priority contains unavailable engine {source}: {unavailable[source]}")
    return warnings

def _has_usable_candidate(formula: dict[str, Any], source: str, variant: str | None = None) -> bool:
    for candidate in formula.get("candidates", []):
        if candidate.get("source") != source:
            continue
        if variant is not None and candidate.get("variant", "original") != variant:
            continue
        if candidate.get("validation_status") == "error":
            continue
        if (candidate.get("latex") or "").strip():
            return True
    return False


def _candidate_empty_reason(candidate: Candidate, source: str) -> str | None:
    raw = (candidate.raw or "").strip()
    latex = (candidate.latex or "").strip()
    if not raw:
        return f"empty raw response from {source}"
    if not latex:
        return "empty LaTeX after cleaning; inspect raw OCR response"
    return None



def _ocr_variants(config: dict[str, Any]) -> list[str]:
    variants = config.get("images", {}).get("ocr_variants", ["original"])
    if isinstance(variants, str):
        variants = [variants]
    cleaned = [str(v) for v in variants if str(v).strip()]
    return cleaned or ["original"]


def _make_ocr_variant(png: Path, formula_id: str, variant: str, wp: WorkPaths, config: dict[str, Any]) -> Path:
    if variant == "original":
        return png
    out_dir = wp.ocr_dir / "variants" / formula_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{variant}.png"
    if out.exists() and out.stat().st_mtime >= png.stat().st_mtime:
        return out
    padding = int(config.get("images", {}).get("padding_px", 24) or 0)
    background = str(config.get("images", {}).get("background", "white"))
    if shutil.which("magick"):
        cmd = ["magick", str(png), "-background", background, "-alpha", "remove", "-alpha", "off"]
        if variant == "padded":
            cmd.extend(["-bordercolor", background, "-border", str(padding)])
        elif variant == "trimmed_padded":
            cmd.extend(["-trim", "+repage", "-bordercolor", background, "-border", str(padding)])
        elif variant == "grayscale_contrast":
            cmd.extend(["-colorspace", "Gray", "-contrast-stretch", "2%x2%", "-bordercolor", background, "-border", str(padding)])
        elif variant == "binarized":
            cmd.extend(["-colorspace", "Gray", "-threshold", "60%", "-bordercolor", background, "-border", str(padding)])
        else:
            return png
        cmd.append(str(out))
        proc = run_command(cmd, timeout=120)
        if proc.returncode == 0 and out.exists():
            return out
    try:
        from PIL import Image, ImageOps, ImageEnhance  # type: ignore[import-not-found]

        im = Image.open(png).convert("RGB")
        if variant in {"trimmed_padded", "grayscale_contrast", "binarized"}:
            im = ImageOps.crop(im, border=0)
        if variant in {"grayscale_contrast", "binarized"}:
            im = ImageEnhance.Contrast(ImageOps.grayscale(im)).enhance(2.0)
        if variant == "binarized":
            im = im.point(lambda x: 255 if x > 153 else 0)
        if variant in {"padded", "trimmed_padded", "grayscale_contrast", "binarized"} and padding > 0:
            im = ImageOps.expand(im, border=padding, fill=background)
        im.save(out)
        return out
    except Exception:
        return png


def _write_ocr_status(raw_path: Path, source: str, payload: dict[str, Any]) -> None:
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(raw_path, {"source": source, **payload})


def _create_engine(source: str, config: dict[str, Any]) -> FormulaEngine:
    try:
        _, engine_cls = ENGINE_CONFIG[source]
    except KeyError as exc:
        raise ValueError(f"Unknown OCR engine: {source}") from exc
    return engine_cls(config)  # type: ignore[call-arg]


def _ocr_image_for_engine(source: str, png: Path, formula_id: str, wp: WorkPaths, config: dict[str, Any]) -> Path:
    if source == "ollama_qwen":
        return _prepare_ocr_image(png, formula_id, wp, config)
    return png


def _recognize_with_engine(engine: FormulaEngine, source: str, image: Path, png: Path, config: dict[str, Any], verbose: bool, progress: bool) -> tuple[Candidate, bool, str | None]:
    candidate = engine.recognize(image)
    empty_reason = _candidate_empty_reason(candidate, source)
    retried_original = False
    if (
        source == "ollama_qwen"
        and empty_reason
        and bool(config.get("ollama", {}).get("retry_empty_with_original", True))
        and image.resolve() != png.resolve()
    ):
        if verbose or progress:
            print(f"retry: {empty_reason}; retrying original PNG", file=sys.stderr, flush=True)
        candidate = engine.recognize(png)
        retried_original = True
        empty_reason = _candidate_empty_reason(candidate, source)
    if empty_reason:
        candidate.validation_status = "error"
        candidate.validation_error = empty_reason
    return candidate, retried_original, empty_reason



def _ocr_max_workers(config: dict[str, Any]) -> int:
    try:
        value = int(config.get("ocr", {}).get("max_workers", 1) or 1)
    except Exception:
        value = 1
    return max(1, value)


_thread_local = threading.local()


def _thread_engine(source: str, config: dict[str, Any]) -> FormulaEngine:
    engines = getattr(_thread_local, "engines", None)
    if engines is None:
        engines = {}
        _thread_local.engines = engines
    if source not in engines:
        engines[source] = _create_engine(source, config)
    return engines[source]


def _progress_futures(futures, enabled: bool, desc: str):
    iterator = as_completed(futures)
    if not enabled:
        return iterator
    try:
        from tqdm.auto import tqdm

        return tqdm(iterator, total=len(futures), desc=desc, unit="task", dynamic_ncols=True)
    except Exception:
        return iterator


def _ocr_task(
    source: str,
    formula: dict[str, Any],
    variant: str,
    workdir: str | Path,
    config: dict[str, Any],
    verbose: bool,
    progress: bool,
) -> dict[str, Any]:
    wp = WorkPaths.from_workdir(workdir)
    png = Path(formula.get("png_path") or "")
    raw_path = wp.ocr_dir / f"{formula['id']}_{source}_{variant}.json"
    if not png.exists():
        error = f"PNG not found: {png}"
        _write_ocr_status(raw_path, source, {"status": "error", "formula_id": formula["id"], "variant": variant, "error": error, "started_at": time.time(), "finished_at": time.time()})
        return {"formula_id": formula["id"], "variant": variant, "candidate": Candidate(source=source, latex="", raw=None, validation_status="error", validation_error=error).to_dict() | {"variant": variant}}
    started_at = time.time()
    try:
        engine = _thread_engine(source, config)
        variant_png = _make_ocr_variant(png, formula["id"], variant, wp, config)
        ocr_image = _ocr_image_for_engine(source, variant_png, formula["id"], wp, config)
        _write_ocr_status(
            raw_path,
            source,
            {
                "status": "running",
                "formula_id": formula["id"],
                "variant": variant,
                "png_path": str(png),
                "variant_png_path": str(variant_png),
                "ocr_image_path": str(ocr_image),
                "started_at": started_at,
            },
        )
        if verbose:
            print(f"start {source} {formula['id']} {variant}: {ocr_image}", file=sys.stderr, flush=True)
        candidate, retried_original, empty_reason = _recognize_with_engine(engine, source, ocr_image, png, config, verbose=verbose, progress=progress)
        elapsed = time.time() - started_at
        _write_ocr_status(
            raw_path,
            source,
            {
                "status": "done" if not empty_reason else "empty_latex",
                "formula_id": formula["id"],
                "variant": variant,
                "png_path": str(png),
                "variant_png_path": str(variant_png),
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
        data = candidate.to_dict()
        data["variant"] = variant
        if verbose:
            msg = "done" if not empty_reason else "empty"
            print(f"{msg} {source} {formula['id']} {variant}: {elapsed:.1f}s", file=sys.stderr, flush=True)
        return {"formula_id": formula["id"], "variant": variant, "candidate": data}
    except Exception as exc:
        elapsed = time.time() - started_at
        _write_ocr_status(
            raw_path,
            source,
            {
                "status": "error",
                "formula_id": formula["id"],
                "variant": variant,
                "png_path": str(png),
                "elapsed_seconds": round(elapsed, 3),
                "error": str(exc),
                "started_at": started_at,
                "finished_at": time.time(),
            },
        )
        if verbose or progress:
            print(f"error {source} {formula['id']} {variant}: {exc}", file=sys.stderr, flush=True)
        return {"formula_id": formula["id"], "variant": variant, "candidate": Candidate(source=source, latex="", raw=None, validation_status="error", validation_error=str(exc)).to_dict() | {"variant": variant}}


def run_ocr(
    workdir: str | Path,
    config: dict[str, Any],
    force: bool = False,
    progress: bool | None = None,
    verbose: bool = False,
    only_id: str | None = None,
    limit: int | None = None,
    from_id: str | None = None,
    to_id: str | None = None,
) -> dict[str, Any]:
    wp = WorkPaths.from_workdir(workdir)
    wp.ensure()
    manifest = load_manifest(workdir)
    if progress is None:
        progress = bool(config.get("ollama", {}).get("progress", True))

    formulas = filter_formulas(
        list(manifest.get("formulas", [])),
        only_id=only_id,
        limit=limit,
        from_id=from_id,
        to_id=to_id,
    )
    effective = effective_ocr_engines(config)
    engine_names = list(effective["will_run"])
    max_workers = _ocr_max_workers(config)
    if progress:
        mode = "parallel" if max_workers > 1 else "sequential"
        print(
            f"OCR: selected_formulas={len(formulas)}, requested_engines={effective['requested']}, mode={mode}, max_workers={max_workers}",
            file=sys.stderr,
            flush=True,
        )
        print(f"OCR effective engines: {engine_names}", file=sys.stderr, flush=True)
        for source in effective.get("disabled", []):
            print(f"skip engine {source}: disabled", file=sys.stderr, flush=True)
        for item in effective.get("unavailable", []):
            print(f"skip engine {item.get('engine')}: {item.get('reason')}", file=sys.stderr, flush=True)

    for item in effective.get("unavailable", []):
        source = str(item.get("engine"))
        reason = str(item.get("reason") or "unavailable")
        if source in ENGINE_CONFIG and _engine_enabled(config, source):
            for formula in formulas:
                _write_ocr_status(
                    wp.ocr_dir / f"{formula['id']}_{source}.json",
                    source,
                    {"status": "skipped_unavailable", "formula_id": formula["id"], "error": reason, "started_at": time.time(), "finished_at": time.time()},
                )

    for source in engine_names:
        try:
            engine = _create_engine(source, config)
        except Exception as exc:
            if verbose or progress:
                print(f"skip engine {source}: {exc}", file=sys.stderr, flush=True)
            for formula in formulas:
                _write_ocr_status(
                    wp.ocr_dir / f"{formula['id']}_{source}.json",
                    source,
                    {"status": "skipped_unavailable", "formula_id": formula["id"], "error": str(exc), "started_at": time.time(), "finished_at": time.time()},
                )
            continue

        variants = _ocr_variants(config)
        max_workers = _ocr_max_workers(config)
        if force or any(has_candidate(f, source) for f in formulas):
            for formula in formulas:
                if force or has_candidate(formula, source):
                    formula["candidates"] = [c for c in formula.get("candidates", []) if c.get("source") != source]
            save_manifest(workdir, manifest)
        tasks: list[tuple[dict[str, Any], str]] = []
        skipped = 0
        for formula in formulas:
            for variant in variants:
                raw_path = wp.ocr_dir / f"{formula['id']}_{source}_{variant}.json"
                if _has_usable_candidate(formula, source, variant) and not force:
                    skipped += 1
                    if not raw_path.exists():
                        existing = next((c for c in formula.get("candidates", []) if c.get("source") == source and c.get("variant", "original") == variant), {})
                        _write_ocr_status(
                            raw_path,
                            source,
                            {
                                "status": "skipped_existing",
                                "formula_id": formula["id"],
                                "variant": variant,
                                "latex": existing.get("latex", ""),
                                "note": "Candidate already exists in manifest; use --force to re-run OCR.",
                            },
                        )
                    if verbose:
                        print(f"skip {source} {formula['id']} {variant}: existing candidate", file=sys.stderr, flush=True)
                    continue
                tasks.append((formula, variant))
        pending_formulas = {str(f.get("id")) for f, _ in tasks}
        if progress:
            mode = "parallel" if max_workers > 1 else "sequential"
            print(
                f"OCR engine {source}: total_formulas={len(formulas)}, tasks={len(tasks)}, pending_formulas={len(pending_formulas)}, "
                f"skipped_tasks={skipped}, mode={mode}, max_workers={max_workers}, variants={variants}",
                file=sys.stderr,
                flush=True,
            )
        if not tasks:
            continue
        by_id = {str(f.get("id")): f for f in formulas}
        if max_workers == 1:
            for formula, variant in _progress(tasks, bool(progress), f"{source} OCR"):
                result = _ocr_task(source, formula, variant, workdir, config, verbose=verbose, progress=bool(progress))
                target = by_id.get(str(result.get("formula_id")))
                if target is not None:
                    target.setdefault("candidates", []).append(result["candidate"])
                    save_manifest(workdir, manifest)
        else:
            with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix=f"docx2xelatex-{source}") as executor:
                futures = [executor.submit(_ocr_task, source, formula, variant, workdir, config, verbose, bool(progress)) for formula, variant in tasks]
                for future in _progress_futures(futures, bool(progress), f"{source} OCR"):
                    result = future.result()
                    target = by_id.get(str(result.get("formula_id")))
                    if target is not None:
                        target.setdefault("candidates", []).append(result["candidate"])
            save_manifest(workdir, manifest)
    save_manifest(workdir, manifest)
    return manifest
