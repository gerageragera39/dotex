from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG: dict[str, Any] = {
    "pandoc": {"from": "docx", "to": "markdown+raw_tex+tex_math_single_backslash", "wrap": "none"},
    "images": {
        "formula_extensions": [".wmf", ".emf"],
        "preserve_extensions": [".png", ".jpg", ".jpeg"],
        "imagemagick_density": 900,
        "trim": True,
        "background": "white",
    },
    "ocr": {"engines": ["pix2tex"]},
    "texteller": {
        "enabled": False,
        "repo_path": "external/TexTeller",
        "timeout_seconds": 180,
        # Override if TexTeller changes CLI shape, e.g.
        # ["python", "-m", "texteller.cli", "inference", "{image_path}"]
        "command": None,
    },
    "pix2tex": {"enabled": True, "timeout_seconds": 180},
    "ollama": {
        "enabled": False,
        "base_url": "http://localhost:11434",
        "model": "qwen3-vl:8b",
        "timeout_seconds": 1200,
        "temperature": 0,
        # Quality-first default: do not cap generated tokens unless user opts in.
        "num_predict": None,
        "force": False,
        "progress": True,
        # Quality-first default: send the original rendered PNG to the vision model.
        # Enable resize_image manually only if very large PNGs are a proven bottleneck.
        "resize_image": False,
        "max_image_side": 2400,
        "retry_empty_with_original": True,
    },
    "docx2tex": {"enabled": False, "priority": 2},
    "candidate_selection": {
        "priority": ["pix2tex", "texteller", "ollama_qwen", "docx2tex"],
        "reject_patterns": [r"\[\]\s*\[\]"],
        "max_explanation_chars": 20,
    },
    "latex": {
        "engine": "xelatex",
        "mainfont": "Times New Roman",
        "sansfont": "Arial",
        "monofont": "Consolas",
        "documentclass": "article",
        "fontsize": "12pt",
        "lang": "ru-RU",
        "main_language": "russian",
        "other_languages": ["english"],
        "build_pdf": True,
        "halt_on_error": False,
        "use_polyglossia": True,
        "use_babel": False,
        "use_unicode_math": False,
    },
    "merge": {
        "invalid_formula_policy": "keep_image_with_todo",
        "inline_wrapper": r"\({latex}\)",
        "display_wrapper": "\\[\n{latex}\n\\]",
    },
}


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(config_path: str | Path | None = None) -> dict[str, Any]:
    if config_path is None:
        return deepcopy(DEFAULT_CONFIG)
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        loaded = yaml.safe_load(f) or {}
    return deep_merge(DEFAULT_CONFIG, loaded)


def write_default_config(out: str | Path) -> Path:
    path = Path(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(DEFAULT_CONFIG, f, allow_unicode=True, sort_keys=False)
    return path
