import asyncio
import json
import os

import pytest
import pytest_asyncio

from lailabot.approval_server import ApprovalServer


@pytest_asyncio.fixture
async def server():
    socket_path = f"/tmp/lailabot-test-{os.getpid()}.sock"
    srv = ApprovalServer(socket_path=socket_path)
    await srv.start()
    yield srv
    await srv.stop()


@pytest.mark.asyncio
async def test_happy_path_approve(server):
    """Hook connects, sends request, server calls on_request, resolve allows, hook gets allow response."""
    received = []

    async def on_request(approval_id, request_data):
        received.append((approval_id, request_data))
        # Simulate user approving after a short delay
        await asyncio.sleep(0.01)
        server.resolve(approval_id, allow=True)

    server.on_request = on_request

    # Simulate what the hook script does: connect, send JSON, read response
    reader, writer = await asyncio.open_unix_connection(server.socket_path)

    request = {"tool_name": "Bash", "tool_input": {"command": "ls"}}
    writer.write(json.dumps(request).encode() + b"\n")
    await writer.drain()

    response_line = await asyncio.wait_for(reader.readline(), timeout=5)
    writer.close()
    await writer.wait_closed()

    response = json.loads(response_line)

    # on_request was called with the right data
    assert len(received) == 1
    assert received[0][1] == request

    # Response has correct PreToolUse format
    assert response["hookSpecificOutput"]["permissionDecision"] == "allow"


@pytest.mark.asyncio
async def test_timeout_returns_deny(server):
    """If nobody calls resolve(), the hook gets a deny after timeout."""
    server.timeout = 0.1  # Override to 100ms for fast test
    server.on_request = lambda aid, req: asyncio.sleep(0)  # No-op, never resolves

    reader, writer = await asyncio.open_unix_connection(server.socket_path)

    request = {"tool_name": "Bash", "tool_input": {"command": "rm -rf /"}}
    writer.write(json.dumps(request).encode() + b"\n")
    await writer.drain()

    response_line = await asyncio.wait_for(reader.readline(), timeout=5)
    writer.close()
    await writer.wait_closed()

    response = json.loads(response_line)
    assert response["hookSpecificOutput"]["permissionDecision"] == "deny"
