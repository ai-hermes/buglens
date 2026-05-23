from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path


@dataclass(frozen=True)
class ExportResult:
    output_dir: Path
    exported_skills: list[str]


def _template_root() -> resources.abc.Traversable:
    return resources.files("buglens").joinpath("skill_templates")


def list_template_skills() -> list[str]:
    root = _template_root()
    skills: list[str] = []
    for entry in root.iterdir():
        if not entry.is_dir():
            continue
        if entry.joinpath("SKILL.md").is_file():
            skills.append(entry.name)
    return sorted(skills)


def export_skills(
    output_dir: Path,
    selected_skills: list[str] | None = None,
    overwrite: bool = False,
) -> ExportResult:
    available = list_template_skills()
    if not available:
        raise RuntimeError("No packaged skill templates were found.")

    selected = sorted(set(selected_skills or available))
    unknown = sorted(set(selected) - set(available))
    if unknown:
        raise ValueError(f"Unknown skills: {', '.join(unknown)}")

    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    template_root = _template_root()
    for skill_name in selected:
        src = template_root.joinpath(skill_name)
        dst = output_dir / skill_name
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
        "name": "buglens-openclaw-skills",
        "version": "0.1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "skills": selected,
        "compatibility": {
            "codex": "SKILL.md + agents/openai.yaml",
            "openclaw": "SKILL.md frontmatter + local directory install",
        },
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    return ExportResult(output_dir=output_dir, exported_skills=selected)
