import asyncio
import json
import os
import tempfile
import unittest.mock as mock

import pytest

from lailabot.telegram_bot import LailaBot


def make_bot(tmp_dir, user_id=12345):
    return LailaBot(
        bot_token="fake-token",
        authorized_user_id=user_id,
        session_persistence_path=os.path.join(tmp_dir, "sessions.json"),
    )


def make_update(text, user_id=12345, chat_id=100):
    update = mock.AsyncMock()
    update.effective_user.id = user_id
    update.message.text = text
    update.message.chat_id = chat_id
    update.message.reply_text = mock.AsyncMock()
    return update


def make_context():
    ctx = mock.AsyncMock()
    ctx.args = []
    return ctx


@pytest.mark.asyncio
async def test_unauthorized_user_is_silently_ignored():
    with tempfile.TemporaryDirectory() as tmp:
        bot = make_bot(tmp, user_id=12345)
        update = make_update("hello", user_id=99999)
        ctx = make_context()

        await bot.handle_message(update, ctx)

        update.message.reply_text.assert_not_called()


@pytest.mark.asyncio
async def test_message_without_session_prompts_to_start():
    with tempfile.TemporaryDirectory() as tmp:
        bot = make_bot(tmp)
        update = make_update("hello")
        ctx = make_context()

        await bot.handle_message(update, ctx)

        reply = update.message.reply_text.call_args[0][0]
        assert "/new" in reply


@pytest.mark.asyncio
async def test_new_command_creates_session():
    with tempfile.TemporaryDirectory() as tmp:
        bot = make_bot(tmp)
        # Create a real directory to use as work_dir
        work_dir = os.path.join(tmp, "project")
        os.makedirs(work_dir)

        update = make_update(f"/new {work_dir}")
        ctx = make_context()
        ctx.args = [work_dir]

        await bot.handle_new(update, ctx)

        reply = update.message.reply_text.call_args[0][0]
        assert "1" in reply  # session ID
        assert len(bot.session_manager.list_sessions()) == 1


@pytest.mark.asyncio
async def test_new_command_rejects_nonexistent_path():
    with tempfile.TemporaryDirectory() as tmp:
        bot = make_bot(tmp)
        update = make_update("/new /nonexistent/path")
        ctx = make_context()
        ctx.args = ["/nonexistent/path"]

        await bot.handle_new(update, ctx)

        reply = update.message.reply_text.call_args[0][0]
        assert "not exist" in reply.lower() or "not found" in reply.lower()


@pytest.mark.asyncio
async def test_ls_default_lists_home():
    with tempfile.TemporaryDirectory() as tmp:
        bot = make_bot(tmp)
        update = make_update("/ls")
        ctx = make_context()
        ctx.args = []

        await bot.handle_ls(update, ctx)

        reply = update.message.reply_text.call_args[0][0]
        # Home directory should have some entries
        assert len(reply) > 0


@pytest.mark.asyncio
async def test_ls_with_path():
    with tempfile.TemporaryDirectory() as tmp:
        bot = make_bot(tmp)
        # Create test files
        open(os.path.join(tmp, "file1.txt"), "w").close()
        open(os.path.join(tmp, "file2.txt"), "w").close()

        update = make_update(f"/ls {tmp}")
        ctx = make_context()
        ctx.args = [tmp]

        await bot.handle_ls(update, ctx)

        reply = update.message.reply_text.call_args[0][0]
        assert "file1.txt" in reply
        assert "file2.txt" in reply


@pytest.mark.asyncio
async def test_list_sessions():
    with tempfile.TemporaryDirectory() as tmp:
        bot = make_bot(tmp)
        work_dir = os.path.join(tmp, "project")
        os.makedirs(work_dir)
        bot.session_manager.create_session(work_dir)

        update = make_update("/list")
        ctx = make_context()

        await bot.handle_list(update, ctx)

        reply = update.message.reply_text.call_args[0][0]
        assert "1" in reply
        assert work_dir in reply


@pytest.mark.asyncio
async def test_kill_session():
    with tempfile.TemporaryDirectory() as tmp:
        bot = make_bot(tmp)
        bot.session_manager.create_session("/some/path")

        update = make_update("/kill 1")
        ctx = make_context()
        ctx.args = ["1"]

        await bot.handle_kill(update, ctx)

        assert len(bot.session_manager.list_sessions()) == 0
        reply = update.message.reply_text.call_args[0][0]
        assert "killed" in reply.lower() or "1" in reply


@pytest.mark.asyncio
async def test_set_default():
    with tempfile.TemporaryDirectory() as tmp:
        bot = make_bot(tmp)
        bot.session_manager.create_session("/path/a")
        bot.session_manager.create_session("/path/b")

        update = make_update("/set_default 2")
        ctx = make_context()
        ctx.args = ["2"]

        await bot.handle_set_default(update, ctx)

        assert bot.session_manager.get_default_session()["id"] == 2


@pytest.mark.asyncio
async def test_start_command_shows_welcome():
    with tempfile.TemporaryDirectory() as tmp:
        bot = make_bot(tmp)
        update = make_update("/start")
        ctx = make_context()

        await bot.handle_start(update, ctx)

        reply = update.message.reply_text.call_args[0][0]
        assert "LailaBot" in reply or "lailabot" in reply.lower()


# --- Integration: message routing to Claude Code ---

def make_stream_lines(session_id, text_chunks):
    events = [
        {"type": "system", "subtype": "init", "session_id": session_id},
    ]
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
async def test_message_routes_to_default_session():
    with tempfile.TemporaryDirectory() as tmp:
        bot = make_bot(tmp)
        work_dir = os.path.join(tmp, "project")
        os.makedirs(work_dir)
        bot.session_manager.create_session(work_dir)

        update = make_update("help me fix a bug")
        ctx = make_context()

        lines = make_stream_lines("claude-sess-1", ["Sure, ", "I can help!"])

        with mock.patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_exec.return_value = make_mock_proc(lines)
            await bot.handle_message(update, ctx)

        # Should have replied with Claude's response
        replies = [call[0][0] for call in update.message.reply_text.call_args_list]
        full_reply = " ".join(replies)
        assert "Sure" in full_reply or "help" in full_reply

        # Session should now have claude_session_id stored
        session = bot.session_manager.get_session(1)
        assert session["claude_session_id"] == "claude-sess-1"


@pytest.mark.asyncio
async def test_send_command_routes_to_specific_session():
    with tempfile.TemporaryDirectory() as tmp:
        bot = make_bot(tmp)
        dir_a = os.path.join(tmp, "a")
        dir_b = os.path.join(tmp, "b")
        os.makedirs(dir_a)
        os.makedirs(dir_b)
        bot.session_manager.create_session(dir_a)
        bot.session_manager.create_session(dir_b)

        update = make_update("/send 2 check tests")
        ctx = make_context()
        ctx.args = ["2", "check", "tests"]

        lines = make_stream_lines("claude-sess-2", ["Tests pass!"])

        with mock.patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_exec.return_value = make_mock_proc(lines)
            await bot.handle_send(update, ctx)

        replies = [call[0][0] for call in update.message.reply_text.call_args_list]
        assert any("Tests pass" in r for r in replies)

        # Verify it ran in dir_b's working directory
        call_kwargs = mock_exec.call_args[1]
        assert call_kwargs["cwd"] == dir_b
