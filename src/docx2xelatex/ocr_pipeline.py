from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any, Iterable, Iterator, TypeVar

from .engines.base import Candidate, FormulaEngine, has_candidate
from .engines.ollama_qwen import OllamaQwenEngine, _prepare_ocr_image
from .engines.pix2tex_engine import Pix2TexEngine, pix2tex_status
from .engines.texteller_engine import TexTellerEngine, texteller_status
from .formula_filter import filter_formulas
from .manifest import load_manifest, save_manifest
from .paths import WorkPaths
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

def _has_usable_candidate(formula: dict[str, Any], source: str) -> bool:
    for candidate in formula.get("candidates", []):
        if candidate.get("source") != source:
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
    if progress:
        print(
            f"OCR: selected_formulas={len(formulas)}, requested_engines={effective['requested']}, sequential=true",
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

        pending = [f for f in formulas if force or not _has_usable_candidate(f, source)]
        if progress:
            print(
                f"OCR engine {source}: total={len(formulas)}, pending={len(pending)}, skipped_existing={len(formulas) - len(pending)}",
                file=sys.stderr,
                flush=True,
            )
        for formula in _progress(formulas, bool(progress), f"{source} OCR"):
            raw_path = wp.ocr_dir / f"{formula['id']}_{source}.json"
            if _has_usable_candidate(formula, source) and not force:
                if not raw_path.exists():
                    existing = next((c for c in formula.get("candidates", []) if c.get("source") == source), {})
                    _write_ocr_status(
                        raw_path,
                        source,
                        {
                            "status": "skipped_existing",
                            "formula_id": formula["id"],
                            "latex": existing.get("latex", ""),
                            "note": "Candidate already exists in manifest; use --force to re-run OCR.",
                        },
                    )
                if verbose:
                    print(f"skip {source} {formula['id']}: existing candidate", file=sys.stderr, flush=True)
                continue
            if force or has_candidate(formula, source):
                formula["candidates"] = [c for c in formula.get("candidates", []) if c.get("source") != source]
            png = Path(formula.get("png_path") or "")
            if not png.exists():
                error = f"PNG not found: {png}"
                formula.setdefault("candidates", []).append(
                    Candidate(source=source, latex="", raw=None, validation_status="error", validation_error=error).to_dict()
                )
                _write_ocr_status(raw_path, source, {"status": "error", "formula_id": formula["id"], "error": error, "started_at": time.time(), "finished_at": time.time()})
                save_manifest(workdir, manifest)
                continue
            started_at = time.time()
            try:
                ocr_image = _ocr_image_for_engine(source, png, formula["id"], wp, config)
                _write_ocr_status(
                    raw_path,
                    source,
                    {
                        "status": "running",
                        "formula_id": formula["id"],
                        "png_path": str(png),
                        "ocr_image_path": str(ocr_image),
                        "started_at": started_at,
                    },
                )
                if verbose:
                    print(f"start {source} {formula['id']}: {ocr_image}", file=sys.stderr, flush=True)
                candidate, retried_original, empty_reason = _recognize_with_engine(
                    engine,
                    source,
                    ocr_image,
                    png,
                    config,
                    verbose=verbose,
                    progress=bool(progress),
                )
                elapsed = time.time() - started_at
                _write_ocr_status(
                    raw_path,
                    source,
                    {
                        "status": "done" if not empty_reason else "empty_latex",
                        "formula_id": formula["id"],
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
                    print(f"{msg} {source} {formula['id']}: {elapsed:.1f}s", file=sys.stderr, flush=True)
            except Exception as exc:
                elapsed = time.time() - started_at
                formula.setdefault("candidates", []).append(
                    Candidate(source=source, latex="", raw=None, validation_status="error", validation_error=str(exc)).to_dict()
                )
                _write_ocr_status(
                    raw_path,
                    source,
                    {
                        "status": "error",
                        "formula_id": formula["id"],
                        "png_path": str(png),
                        "elapsed_seconds": round(elapsed, 3),
                        "error": str(exc),
                        "started_at": started_at,
                        "finished_at": time.time(),
                    },
                )
                save_manifest(workdir, manifest)
                if verbose or progress:
                    print(f"error {source} {formula['id']}: {exc}", file=sys.stderr, flush=True)
    save_manifest(workdir, manifest)
    return manifest
