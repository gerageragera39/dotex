from __future__ import annotations

import importlib.util
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from ..latex_clean import clean_latex_candidate
from .base import Candidate


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


def _extract_latex(stdout: str) -> str:
    text = stdout.strip()
    fenced = re.search(r"```(?:latex)?\s*(.*?)\s*```", text, flags=re.S | re.I)
    if fenced:
        return fenced.group(1).strip()
    prefixed = re.search(r"Predicted\s+LaTeX\s*:\s*(.*)", text, flags=re.S | re.I)
    if prefixed:
        return prefixed.group(1).strip()
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[-1] if lines else ""


def texteller_status(config: dict[str, Any]) -> dict[str, Any]:
    texteller = config.get("texteller", {})
    repo = _repo_path(config)
    cli_path = shutil.which("texteller")
    import_ok = importlib.util.find_spec("texteller") is not None
    repo_exists = repo.exists()
    enabled = bool(texteller.get("enabled", True))
    ok = bool(cli_path) or import_ok or repo_exists
    if not enabled:
        label = "disabled"
    elif cli_path or import_ok:
        label = "available"
    elif repo_exists:
        label = "repo_found"
    else:
        label = "missing"
    status: dict[str, Any] = {
        "enabled": enabled,
        "repo_path": str(repo),
        "repo_exists": repo_exists,
        "cli_path": cli_path,
        "import_ok": import_ok,
        "ok": ok if enabled else True,
        "status": label,
    }
    if enabled and not ok:
        status["warning"] = "TexTeller is enabled but no CLI/import/repo was found; clone or install TexTeller, or disable texteller.enabled."
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
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=self.timeout,
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or f"TexTeller exited with code {proc.returncode}")
        raw = _extract_latex(proc.stdout)
        artifacts = {"stdout": proc.stdout.strip()}
        if proc.stderr.strip():
            artifacts["stderr"] = proc.stderr.strip()
        return Candidate(source=self.source, latex=clean_latex_candidate(raw), raw=raw, artifacts=artifacts)
