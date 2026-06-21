from __future__ import annotations

import importlib.util
import os
import re
import shlex
import shutil
import sys
from pathlib import Path
from typing import Any

from ..gpu_diagnostics import onnxruntime_status, torch_status
from ..latex_clean import clean_latex_candidate
from ..subprocess_utils import run_command
from .base import Candidate

TEXTELLER_REQUIRED_MODULES = {
    "optimum": 'pip install "optimum[onnxruntime]>=1.24.0"',
    "cv2": "pip install opencv-python-headless>=4.11.0.86",
    "pyclipper": "pip install pyclipper>=1.3.0.post6",
    "shapely": "pip install shapely>=2.1.0",
    "torch": "pip install torch>=2.6.0",
    "torchvision": "pip install torchvision>=0.21.0",
    "transformers": "pip install transformers==4.47",
    "wget": "pip install wget>=3.2",
    "ray": 'pip install "ray[serve]>=2.44.1"',
}


def texteller_missing_modules() -> list[str]:
    missing = []
    for module in TEXTELLER_REQUIRED_MODULES:
        try:
            if importlib.util.find_spec(module) is None:
                missing.append(module)
        except ModuleNotFoundError:
            missing.append(module)
    return missing


def texteller_install_hint(missing: list[str]) -> str | None:
    if not missing:
        return None
    if "optimum" in missing:
        return TEXTELLER_REQUIRED_MODULES["optimum"]
    return "pip install -e external/TexTeller && pip install " + " ".join(sorted(missing))


class TexTellerUnavailable(RuntimeError):
    pass


def _repo_path(config: dict[str, Any]) -> Path:
    return Path(str(config.get("texteller", {}).get("repo_path", "external/TexTeller"))).expanduser()


def _command_from_config(config: dict[str, Any], image_path: str | Path) -> list[str]:
    texteller = config.get("texteller", {})
    command = texteller.get("command") or texteller.get("cli_command")
    image = str(image_path)
    if command:
        if isinstance(command, str):
            return [part.format(image_path=image, image=image) for part in shlex.split(command)]
        if isinstance(command, list):
            return [str(part).format(image_path=image, image=image) for part in command]
        raise ValueError("texteller.command must be a string or list")
    if shutil.which("texteller"):
        return ["texteller", "inference", image]
    return [sys.executable, "-m", "texteller.cli", "inference", image]


def _looks_like_latex_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    low = stripped.lower()
    noise_tokens = ("progress", "download", "loaded", "loading", "elapsed", "it/s", "%|", "warning", "error:", "footer", "done", "saved")
    if any(tok in low for tok in noise_tokens):
        return False
    if re.match(r"^[\[\]=>#.*\-\s]*\d+%", stripped):
        return False
    return bool(re.search(r"\\[A-Za-z]+|[_^{}=+\-*/<>]|\d", stripped))


def _extract_latex(stdout: str) -> str:
    text = stdout.strip()
    fenced = re.search(r"```(?:latex|tex|math)?\s*(.*?)\s*```", text, flags=re.S | re.I)
    if fenced:
        return fenced.group(1).strip()
    # Prefer single-line labelled predictions; stop at the line, not all footer text.
    for line in text.splitlines():
        m = re.search(r"(?:predicted\s+latex|latex|formula|result)\s*[:：]\s*(.+)$", line, flags=re.I)
        if m and _looks_like_latex_line(m.group(1)):
            return m.group(1).strip()
    lines = [line.strip() for line in text.splitlines() if _looks_like_latex_line(line)]
    if not lines:
        return ""
    # TexTeller CLIs usually print progress first and the prediction near the end;
    # choose the last plausible math line, not an arbitrary footer/progress line.
    return lines[-1]


def texteller_status(config: dict[str, Any]) -> dict[str, Any]:
    texteller = config.get("texteller", {})
    repo = _repo_path(config)
    cli_path = shutil.which("texteller")
    try:
        import_ok = importlib.util.find_spec("texteller") is not None
    except ModuleNotFoundError:
        import_ok = False
    repo_exists = repo.exists()
    enabled = bool(texteller.get("enabled", True))
    missing_modules = texteller_missing_modules() if enabled else []
    has_entrypoint = bool(cli_path) or import_ok or repo_exists
    deps_ok = not missing_modules
    ok = has_entrypoint and deps_ok
    if not enabled:
        label = "disabled"
    elif not has_entrypoint:
        label = "missing"
    elif not deps_ok:
        label = "missing_dependencies"
    elif cli_path or import_ok:
        label = "available"
    else:
        label = "repo_found"
    status: dict[str, Any] = {
        "enabled": enabled,
        "repo_path": str(repo),
        "repo_exists": repo_exists,
        "cli_path": cli_path,
        "import_ok": import_ok,
        "package_import_ok": import_ok,
        "missing_modules": missing_modules,
        "install_hint": texteller_install_hint(missing_modules) if enabled else None,
        "ok": ok if enabled else True,
        "will_run": bool(enabled and ok),
        "status": label,
        "torch": torch_status() if enabled else None,
        "onnxruntime": onnxruntime_status() if enabled else None,
    }
    if enabled and not has_entrypoint:
        status["warning"] = "TexTeller is enabled but no CLI/import/repo was found; clone or install TexTeller, or disable texteller.enabled."
    elif enabled and missing_modules:
        status["warning"] = f"TexTeller unavailable: missing module {missing_modules[0]}. Install: {status['install_hint']}"
    elif enabled and status.get("onnxruntime") and not status["onnxruntime"].get("cuda_provider_available"):
        status["gpu_warning"] = "ONNX Runtime CUDAExecutionProvider is not available; TexTeller may use CPU even when PyTorch CUDA works."
    return status


class TexTellerEngine:
    source = "texteller"

    def __init__(self, config: dict[str, Any]):
        texteller = config.get("texteller", {})
        self.config = config
        self.repo_path = _repo_path(config)
        self.timeout = int(texteller.get("timeout_seconds", 180))
        status = texteller_status(config)
        if not status["ok"]:
            raise TexTellerUnavailable(str(status.get("warning", "TexTeller is unavailable")))

    def build_command(self, image_path: str | Path) -> list[str]:
        """Single adapter point for TexTeller CLI shape changes.

        Override it via config:

            texteller:
              command: ["python", "-m", "texteller.cli", "inference", "{image_path}"]

        or as a shell-like string. The `{image_path}` token is substituted.
        """
        return _command_from_config(self.config, image_path)

    def recognize(self, image_path: str | Path) -> Candidate:
        cmd = self.build_command(image_path)
        env = os.environ.copy()
        if self.repo_path.exists():
            env["PYTHONPATH"] = str(self.repo_path) + os.pathsep + env.get("PYTHONPATH", "")
        cwd = self.repo_path if self.repo_path.exists() else None
        proc = run_command(cmd, cwd=cwd, env=env, timeout=self.timeout)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or f"TexTeller exited with code {proc.returncode}")
        raw = _extract_latex(proc.stdout)
        artifacts = {"stdout": proc.stdout.strip()}
        if proc.stderr.strip():
            artifacts["stderr"] = proc.stderr.strip()
        return Candidate(source=self.source, latex=clean_latex_candidate(raw), raw=raw, artifacts=artifacts)
