from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path
from typing import Callable

BUGLENS_SKILL_NAME = "buglens"


@dataclass(frozen=True)
class ExportResult:
    output_dir: Path
    exported_skill: str


@dataclass(frozen=True)
class ReleaseBundleResult:
    bundle_dir: Path
    skill_dir: Path
    wheel_path: Path
    install_doc: Path


def _template_root() -> resources.abc.Traversable:
    return resources.files("buglens").joinpath("skill_templates")


def export_skill(
    output_dir: Path,
    overwrite: bool = False,
) -> ExportResult:
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    template_root = _template_root()
    src = template_root.joinpath(BUGLENS_SKILL_NAME)
    if not src.joinpath("SKILL.md").is_file():
        raise RuntimeError("Packaged buglens skill template is missing.")

    dst = output_dir / BUGLENS_SKILL_NAME
    if dst.exists() and not overwrite:
        raise FileExistsError(
            f"Target already exists: {dst}. Re-run with --overwrite to replace it."
        )
    if dst.exists():
        shutil.rmtree(dst)
    # resources.as_file materializes package resources on disk when needed.
    with resources.as_file(src) as src_path:
        shutil.copytree(src_path, dst)

    manifest = {
        "name": "buglens-openclaw-skill",
        "version": "0.1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "skill": BUGLENS_SKILL_NAME,
        "compatibility": {
            "codex": "SKILL.md + agents/openai.yaml",
            "openclaw": "SKILL.md frontmatter + local directory install",
        },
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    return ExportResult(output_dir=output_dir, exported_skill=BUGLENS_SKILL_NAME)


def _latest_wheel_path(dist_dir: Path) -> Path:
    wheels = sorted(dist_dir.glob("buglens-*.whl"))
    if not wheels:
        raise FileNotFoundError(f"No buglens wheel found in {dist_dir}")
    return wheels[-1]


def _build_wheel(dist_dir: Path) -> Path:
    dist_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(dist_dir)],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return _latest_wheel_path(dist_dir)


def _write_bundle_install_md(bundle_dir: Path, wheel_name: str) -> Path:
    install_md = bundle_dir / "INSTALL.md"
    install_md.write_text(
        "\n".join(
            [
                "# buglens Bundle Install Guide",
                "",
                "This bundle ships one external skill (`buglens`) plus runtime wheel.",
                "",
                "## 1) Install runtime (no source code required)",
                "",
                "```bash",
                f"pipx install ./runtime/{wheel_name}",
                "```",
                "",
                "If you do not use `pipx`, use:",
                "",
                "```bash",
                f"python -m pip install ./runtime/{wheel_name}",
                "```",
                "",
                "## 2) Start MCP runtime",
                "",
                "```bash",
                "buglens-mcp",
                "```",
                "",
                "## 3) Install skill",
                "",
                "OpenClaw:",
                "",
                "```bash",
                "openclaw skills install ./skill/buglens",
                "```",
                "",
                "Codex (repo-local): copy or link `skill/buglens` into `.agents/skills/buglens`.",
                "",
                "## 4) Configure MCP",
                "",
                "Use `configs/openclaw-mcp.json` and `configs/codex-mcp.json` as templates.",
                "",
                "## 5) Required env vars",
                "",
                "- `GITLAB_URL`",
                "- `GITLAB_TOKEN`",
                "- `BUGLENS_ALIBABA_ACCESS_KEY_ID`",
                "- `BUGLENS_ALIBABA_ACCESS_KEY_SECRET`",
                "- `BUGLENS_ALIBABA_REGION_ID`",
                "",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return install_md


def _write_mcp_templates(bundle_dir: Path) -> None:
    configs_dir = bundle_dir / "configs"
    configs_dir.mkdir(parents=True, exist_ok=True)

    openclaw_mcp = {
        "mcpServers": {
            "buglens": {
                "command": "buglens-mcp",
                "env": {
                    "GITLAB_URL": "${GITLAB_URL}",
                    "GITLAB_TOKEN": "${GITLAB_TOKEN}",
                    "BUGLENS_ALIBABA_ACCESS_KEY_ID": "${BUGLENS_ALIBABA_ACCESS_KEY_ID}",
                    "BUGLENS_ALIBABA_ACCESS_KEY_SECRET": "${BUGLENS_ALIBABA_ACCESS_KEY_SECRET}",
                    "BUGLENS_ALIBABA_REGION_ID": "${BUGLENS_ALIBABA_REGION_ID}",
                },
            }
        }
    }
    codex_mcp = {
        "mcpServers": {
            "buglens": {
                "command": "buglens-mcp",
                "env": {
                    "GITLAB_URL": "${GITLAB_URL}",
                    "GITLAB_TOKEN": "${GITLAB_TOKEN}",
                },
            }
        }
    }
    (configs_dir / "openclaw-mcp.json").write_text(
        json.dumps(openclaw_mcp, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (configs_dir / "codex-mcp.json").write_text(
        json.dumps(codex_mcp, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def release_bundle(
    output_dir: Path,
    overwrite: bool = False,
    skip_build: bool = False,
    wheel_path: Path | None = None,
    build_runner: Callable[[Path], Path] = _build_wheel,
) -> ReleaseBundleResult:
    bundle_dir = output_dir.resolve()
    if bundle_dir.exists() and any(bundle_dir.iterdir()) and not overwrite:
        raise FileExistsError(
            f"Target already exists and is not empty: {bundle_dir}. "
            "Re-run with --overwrite to replace it."
        )
    if bundle_dir.exists() and overwrite:
        shutil.rmtree(bundle_dir)
    bundle_dir.mkdir(parents=True, exist_ok=True)

    skill_dir = bundle_dir / "skill"
    export_skill(output_dir=skill_dir, overwrite=overwrite)

    runtime_dir = bundle_dir / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)

    resolved_wheel: Path
    if wheel_path is not None:
        resolved_wheel = wheel_path.resolve()
        if not resolved_wheel.exists():
            raise FileNotFoundError(f"Wheel path not found: {resolved_wheel}")
    elif skip_build:
        resolved_wheel = _latest_wheel_path(Path.cwd() / "dist")
    else:
        resolved_wheel = build_runner(runtime_dir)

    target_wheel = runtime_dir / resolved_wheel.name
    if resolved_wheel != target_wheel:
        shutil.copy2(resolved_wheel, target_wheel)

    _write_mcp_templates(bundle_dir)
    install_doc = _write_bundle_install_md(bundle_dir, target_wheel.name)

    manifest = {
        "name": "buglens-release-bundle",
        "version": "0.1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "skill": BUGLENS_SKILL_NAME,
        "wheel": target_wheel.name,
    }
    (bundle_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    return ReleaseBundleResult(
        bundle_dir=bundle_dir,
        skill_dir=skill_dir / BUGLENS_SKILL_NAME,
        wheel_path=target_wheel,
        install_doc=install_doc,
    )
