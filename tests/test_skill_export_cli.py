from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _run_export(output: Path, overwrite: bool = False) -> subprocess.CompletedProcess[str]:
    cmd = [
        sys.executable,
        "-m",
        "buglens.cli",
        "skills",
        "export",
        "--output",
        str(output),
    ]
    if overwrite:
        cmd.append("--overwrite")
    return subprocess.run(cmd, capture_output=True, text=True)


def test_skill_export_cli_success(tmp_path: Path) -> None:
    output = tmp_path / "dist"
    proc = _run_export(output)

    assert proc.returncode == 0, proc.stderr
    assert "exported skill: buglens" in proc.stdout
    assert "openclaw skills install" in proc.stdout
    assert (output / "manifest.json").exists()


def test_skill_export_cli_overwrite_guard(tmp_path: Path) -> None:
    output = tmp_path / "dist"
    first = _run_export(output)
    assert first.returncode == 0, first.stderr

    second = _run_export(output)
    assert second.returncode != 0
    assert "skills export failed" in second.stderr

    third = _run_export(output, overwrite=True)
    assert third.returncode == 0, third.stderr
