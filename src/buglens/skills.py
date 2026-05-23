from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path

BUGLENS_SKILL_NAME = "buglens"


@dataclass(frozen=True)
class ExportResult:
    output_dir: Path
    exported_skill: str


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
