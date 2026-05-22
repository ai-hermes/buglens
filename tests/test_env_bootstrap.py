from __future__ import annotations

import os

from buglens.config import bootstrap_process_env_from_dotenv


def test_bootstrap_process_env_from_dotenv_loads_missing_keys(tmp_path, monkeypatch) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "\n".join(
            [
                "GITLAB_URL=http://gitlab.local",
                "GITLAB_TOKEN=token-123",
                "BUGLENS_MODEL=from-dotenv",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GITLAB_URL", raising=False)
    monkeypatch.delenv("GITLAB_TOKEN", raising=False)
    monkeypatch.delenv("BUGLENS_MODEL", raising=False)

    bootstrap_process_env_from_dotenv()

    assert os.environ.get("GITLAB_URL") == "http://gitlab.local"
    assert os.environ.get("GITLAB_TOKEN") == "token-123"
    assert os.environ.get("BUGLENS_MODEL") == "from-dotenv"


def test_bootstrap_process_env_from_dotenv_keeps_existing_env(tmp_path, monkeypatch) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text("GITLAB_URL=http://gitlab.local\n", encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GITLAB_URL", "http://already-set.local")

    bootstrap_process_env_from_dotenv()

    assert os.environ.get("GITLAB_URL") == "http://already-set.local"
