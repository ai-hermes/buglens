import json
import os
import subprocess
import sys


def test_cli_jsonrpc_lifecycle() -> None:
    env = dict(os.environ)
    env["BUGLENS_MOCK_RESPONSE"] = "hello-from-mock"

    proc = subprocess.Popen(
        [sys.executable, "-m", "buglens.cli"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )

    assert proc.stdin is not None
    assert proc.stdout is not None

    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "health", "params": {}},
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "invoke",
            "params": {"task": "ping", "context": {"source": "test"}},
        },
        {"jsonrpc": "2.0", "id": 4, "method": "shutdown", "params": {}},
    ]

    for message in messages:
        proc.stdin.write(json.dumps(message) + "\n")
        proc.stdin.flush()

    proc.stdin.close()
    stdout = proc.stdout.read().strip().splitlines()
    stderr = proc.stderr.read()
    return_code = proc.wait(timeout=10)

    assert return_code == 0, stderr
    assert len(stdout) == 4

    invoke_response = json.loads(stdout[2])
    assert invoke_response["result"]["output"] == "hello-from-mock"
