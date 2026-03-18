import asyncio
import json
import os
import subprocess
import sys

import pytest
import pytest_asyncio

from lailabot.approval_server import ApprovalServer


@pytest_asyncio.fixture
async def server():
    socket_path = f"/tmp/lailabot-hook-test-{os.getpid()}.sock"
    srv = ApprovalServer(socket_path=socket_path)
    await srv.start()
    yield srv
    await srv.stop()


@pytest.mark.asyncio
async def test_hook_script_sends_request_and_receives_decision(server):
    """The hook script reads stdin, connects to the socket, and outputs the decision JSON."""

    async def on_request(approval_id, request_data):
        assert request_data["tool_name"] == "Bash"
        server.resolve(approval_id, allow=True)

    server.on_request = on_request

    hook_input = json.dumps({
        "tool_name": "Bash",
        "tool_input": {"command": "echo hello"},
        "session_id": "sess-1",
    })

    # Run the hook script as a subprocess (like Claude Code would)
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "lailabot.approval_hook",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={**os.environ, "LAILABOT_SOCKET": server.socket_path},
    )
    stdout, stderr = await asyncio.wait_for(
        proc.communicate(hook_input.encode()), timeout=5
    )

    assert proc.returncode == 0, f"Hook failed: {stderr.decode()}"

    output = json.loads(stdout.decode())
    decision = output["hookSpecificOutput"]["decision"]
    assert decision["behavior"] == "allow"
