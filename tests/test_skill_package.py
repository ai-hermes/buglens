from pathlib import Path

from buglens.skills import export_skills


def _frontmatter(path: Path) -> str:
    content = path.read_text(encoding="utf-8")
    parts = content.split("---\n")
    if len(parts) < 3:
        raise AssertionError("SKILL.md frontmatter is missing")
    return parts[1]


def test_buglens_skill_frontmatter_is_openclaw_compatible() -> None:
    skill_path = Path("skills/buglens/SKILL.md")
    assert skill_path.exists()

    header = _frontmatter(skill_path)
    assert "name: buglens" in header
    assert "description:" in header
    assert "user-invocable: true" in header
    assert "openclaw:" in header
    assert "env:" in header
    assert "- GITLAB_URL" in header
    assert "- GITLAB_TOKEN" in header


def test_buglens_skill_has_codex_ui_metadata() -> None:
    ui_metadata = Path("skills/buglens/agents/openai.yaml")
    assert ui_metadata.exists()
    content = ui_metadata.read_text(encoding="utf-8")
    assert "display_name: buglens" in content
    assert "short_description:" in content
    assert "default_prompt:" in content


def test_export_skills_writes_expected_layout(tmp_path: Path) -> None:
    output = tmp_path / "openclaw-skills"
    result = export_skills(output_dir=output)

    assert result.exported_skills == ["buglens"]
    assert (output / "manifest.json").exists()
    assert (output / "buglens" / "SKILL.md").exists()
    assert (output / "buglens" / "agents" / "openai.yaml").exists()
