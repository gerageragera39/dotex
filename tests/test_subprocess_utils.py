from __future__ import annotations

import subprocess
from pathlib import Path

from docx2xelatex.subprocess_utils import run_command


def test_run_command_decodes_invalid_utf8_without_unicode_error(monkeypatch):
    class Proc:
        returncode = 0
        stdout = b"ok\x81done"
        stderr = b"err\x81"

    def fake_run(*args, **kwargs):
        assert kwargs["text"] is False
        assert kwargs["stdin"] is subprocess.DEVNULL
        return Proc()

    monkeypatch.setattr("docx2xelatex.subprocess_utils.subprocess.run", fake_run)
    result = run_command(["dummy"])
    assert result.returncode == 0
    assert "ok" in result.stdout
    assert "�" in result.stdout
    assert "�" in result.stderr


def test_production_subprocess_pipe_calls_do_not_use_text_true():
    root = Path("src/docx2xelatex")
    offenders = []
    for path in root.rglob("*.py"):
        if path.name == "subprocess_utils.py":
            continue
        text = path.read_text(encoding="utf-8")
        if "subprocess.run" in text and "text=True" in text and "PIPE" in text:
            offenders.append(str(path))
    assert offenders == []
