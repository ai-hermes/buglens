import os
import subprocess
import logging

from buglens.cli import _configure_logging


def test_cli_invoke_mode() -> None:
    env = dict(os.environ)
    env["BUGLENS_MOCK_RESPONSE"] = "mock-via-env"
    proc = subprocess.run(
        ["uv", "run", "buglens", "invoke", "--task", "ping"],
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "mock-via-env"


def test_cli_invoke_stream_and_logs() -> None:
    env = dict(os.environ)
    proc = subprocess.run(
        [
            "uv",
            "run",
            "buglens",
            "--log-level",
            "INFO",
            "invoke",
            "--task",
            "ping",
            "--mock-response",
            "stream-mock",
            "--stream",
        ],
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "stream-mock"
    assert "invoke started" in proc.stderr


def test_configure_logging_quiets_http_transport_logs() -> None:
    _configure_logging("INFO")
    assert logging.getLogger("httpx").level == logging.WARNING
    assert logging.getLogger("httpcore").level == logging.WARNING
