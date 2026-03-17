import asyncio
import json
import unittest.mock as mock

import pytest

from lailabot.claude_code_runner import ClaudeCodeRunner


def make_stream_lines(session_id, text_chunks):
    """Build fake stream-json output as list of encoded lines."""
    events = []
    events.append({"type": "system", "subtype": "init", "session_id": session_id})
    for chunk in text_chunks:
        events.append({"type": "assistant", "subtype": "text", "content": chunk})
    events.append({"type": "result", "session_id": session_id, "result": "".join(text_chunks)})
    return [json.dumps(e).encode() + b"\n" for e in events]


async def async_line_iter(lines):
    for line in lines:
        yield line


def make_mock_proc(lines, return_code=0):
    proc = mock.AsyncMock()
    proc.stdout = async_line_iter(lines)
    proc.wait = mock.AsyncMock(return_value=return_code)
    proc.pid = 12345
    return proc


@pytest.mark.asyncio
async def test_first_message_captures_session_id_and_returns_text():
    runner = ClaudeCodeRunner()
    chunks_received = []

    async def on_chunk(text):
        chunks_received.append(text)

    lines = make_stream_lines("sess-abc-123", ["Hello ", "world!"])

    with mock.patch("asyncio.create_subprocess_exec") as mock_exec:
        mock_exec.return_value = make_mock_proc(lines)

        session_id = await runner.send_message(
            message="hello",
            work_dir="/tmp/test",
            claude_session_id=None,
            on_chunk=on_chunk,
        )

    assert session_id == "sess-abc-123"
    assert "Hello " in chunks_received
    assert "world!" in chunks_received

    # Verify claude was called without --resume for first message
    call_args = mock_exec.call_args
    args = call_args[0]
    assert "--resume" not in args


@pytest.mark.asyncio
async def test_resume_uses_session_id():
    runner = ClaudeCodeRunner()
    lines = make_stream_lines("sess-abc-123", ["OK"])

    with mock.patch("asyncio.create_subprocess_exec") as mock_exec:
        mock_exec.return_value = make_mock_proc(lines)

        await runner.send_message(
            message="follow up",
            work_dir="/tmp/test",
            claude_session_id="sess-abc-123",
            on_chunk=mock.AsyncMock(),
        )

    args = mock_exec.call_args[0]
    assert "--resume" in args
    resume_idx = args.index("--resume")
    assert args[resume_idx + 1] == "sess-abc-123"


@pytest.mark.asyncio
async def test_ignores_non_text_events():
    runner = ClaudeCodeRunner()
    chunks_received = []

    events = [
        {"type": "system", "subtype": "init", "session_id": "s1"},
        {"type": "assistant", "subtype": "tool_use", "content": "reading file"},
        {"type": "assistant", "subtype": "text", "content": "actual text"},
        {"type": "tool_result", "content": "file contents"},
        {"type": "result", "session_id": "s1", "result": "actual text"},
    ]
    lines = [json.dumps(e).encode() + b"\n" for e in events]

    with mock.patch("asyncio.create_subprocess_exec") as mock_exec:
        mock_exec.return_value = make_mock_proc(lines)

        await runner.send_message(
            message="test",
            work_dir="/tmp",
            claude_session_id=None,
            on_chunk=lambda t: chunks_received.append(t) or asyncio.sleep(0),
        )

    assert chunks_received == ["actual text"]


@pytest.mark.asyncio
async def test_fifo_queue_processes_sequentially():
    runner = ClaudeCodeRunner()
    order = []

    async def on_chunk_factory(label):
        async def on_chunk(text):
            order.append(f"{label}:{text}")
        return on_chunk

    call_count = 0

    async def fake_exec(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        n = call_count
        lines = make_stream_lines(f"s{n}", [f"reply{n}"])
        return make_mock_proc(lines)

    with mock.patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
        # Queue 3 messages for the same session key
        chunk_cb1 = await on_chunk_factory("m1")
        chunk_cb2 = await on_chunk_factory("m2")
        chunk_cb3 = await on_chunk_factory("m3")

        t1 = runner.enqueue(session_key=1, message="msg1", work_dir="/tmp",
                            claude_session_id=None, on_chunk=chunk_cb1)
        t2 = runner.enqueue(session_key=1, message="msg2", work_dir="/tmp",
                            claude_session_id=None, on_chunk=chunk_cb2)
        t3 = runner.enqueue(session_key=1, message="msg3", work_dir="/tmp",
                            claude_session_id=None, on_chunk=chunk_cb3)

        results = await asyncio.gather(t1, t2, t3)

    assert order == ["m1:reply1", "m2:reply2", "m3:reply3"]
