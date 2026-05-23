from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from buglens.skills import release_bundle


def test_release_bundle_with_explicit_wheel_path(tmp_path: Path) -> None:
    wheel_file = tmp_path / "buglens-0.1.0-py3-none-any.whl"
    wheel_file.write_bytes(b"fake-wheel")

    result = release_bundle(
        output_dir=tmp_path / "bundle",
        wheel_path=wheel_file,
        skip_build=True,
    )

    assert result.bundle_dir.exists()
    assert result.skill_dir.exists()
    assert result.wheel_path.exists()
    assert result.wheel_path.name == wheel_file.name
    assert (result.bundle_dir / "configs" / "openclaw-mcp.json").exists()
    assert (result.bundle_dir / "configs" / "codex-mcp.json").exists()
    assert result.install_doc.exists()


def test_skills_release_cli_with_skip_build(tmp_path: Path) -> None:
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir(parents=True)
    wheel_file = dist_dir / "buglens-0.1.0-py3-none-any.whl"
    wheel_file.write_bytes(b"fake-wheel")

    bundle_dir = tmp_path / "bundle"
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "buglens.cli",
            "skills",
            "release",
            "--output",
            str(bundle_dir),
            "--skip-build",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 0, proc.stderr
    assert "release bundle:" in proc.stdout
    assert (bundle_dir / "runtime" / wheel_file.name).exists()
    assert (bundle_dir / "skill" / "buglens" / "SKILL.md").exists()
    assert (bundle_dir / "INSTALL.md").exists()
