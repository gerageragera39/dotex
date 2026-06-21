from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence


@dataclass
class CommandResult:
    cmd: list[str]
    returncode: int
    stdout: str
    stderr: str
    cwd: str | None
    timed_out: bool = False
    timeout_seconds: int | None = None


def _decode(data: bytes | str | None) -> str:
    if data is None:
        return ""
    if isinstance(data, str):
        return data
    return data.decode("utf-8", errors="replace")


def run_command(
    cmd: Sequence[str],
    cwd: str | Path | None = None,
    timeout: int | None = None,
    env: Mapping[str, str] | None = None,
    stdin_devnull: bool = True,
) -> CommandResult:
    argv = [str(part) for part in cmd]
    cwd_str = str(cwd) if cwd is not None else None
    try:
        proc = subprocess.run(
            argv,
            cwd=cwd_str,
            timeout=timeout,
            env=dict(env) if env is not None else None,
            stdin=subprocess.DEVNULL if stdin_devnull else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=False,
        )
        return CommandResult(
            cmd=argv,
            returncode=proc.returncode,
            stdout=_decode(proc.stdout),
            stderr=_decode(proc.stderr),
            cwd=cwd_str,
            timed_out=False,
            timeout_seconds=timeout,
        )
    except FileNotFoundError as exc:
        return CommandResult(
            cmd=argv,
            returncode=127,
            stdout="",
            stderr=str(exc),
            cwd=cwd_str,
            timed_out=False,
            timeout_seconds=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        return CommandResult(
            cmd=argv,
            returncode=-1,
            stdout=_decode(exc.stdout),
            stderr=_decode(exc.stderr),
            cwd=cwd_str,
            timed_out=True,
            timeout_seconds=timeout,
        )
