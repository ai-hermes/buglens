import os
import subprocess


def test_cli_repl_plain_text_invokes() -> None:
    env = dict(os.environ)
    env["BUGLENS_MOCK_RESPONSE"] = "mock-repl"

    proc = subprocess.run(
        ["uv", "run", "buglens", "repl"],
        input="hi\nshutdown\n",
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.count("invoking...") == 1
    assert "mock-repl" in proc.stdout
    assert '"stopped": true' in proc.stdout


def test_cli_repl_stream_mode() -> None:
    env = dict(os.environ)
    proc = subprocess.run(
        ["uv", "run", "buglens", "repl", "--mock-response", "stream-repl", "--stream"],
        input="hi\nshutdown\n",
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.count("invoking...") == 1
    assert "stream-repl" in proc.stdout
    assert '"stopped": true' in proc.stdout
