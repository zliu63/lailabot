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
        events.append({
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": chunk}]},
            "session_id": session_id,
        })
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


# --- Approval flow ---


@pytest.mark.asyncio
async def test_approval_request_sends_telegram_message_with_keyboard():
    """When the approval server gets a request, bot sends a message with Approve/Deny buttons."""
    from telegram import InlineKeyboardMarkup

    with tempfile.TemporaryDirectory() as tmp:
        bot = make_bot(tmp)

        # Simulate the approval server calling on_request
        fake_bot_instance = mock.AsyncMock()
        bot._telegram_bot = fake_bot_instance

        request_data = {
            "tool_name": "Bash",
            "tool_input": {"command": "rm -rf /tmp/test"},
        }

        await bot.handle_approval_request("approval-123", request_data)

        fake_bot_instance.send_message.assert_called_once()
        call_kwargs = fake_bot_instance.send_message.call_args[1]
        assert "Bash" in call_kwargs["text"]
        assert "rm -rf /tmp/test" in call_kwargs["text"]
        assert isinstance(call_kwargs["reply_markup"], InlineKeyboardMarkup)


@pytest.mark.asyncio
async def test_approve_callback_resolves_approval():
    """Clicking Approve resolves the pending approval as allow."""
    from lailabot.approval_server import ApprovalServer

    with tempfile.TemporaryDirectory() as tmp:
        bot = make_bot(tmp)

        approval_server = mock.MagicMock(spec=ApprovalServer)
        bot.approval_server = approval_server

        # Simulate a callback query from the authorized user clicking "Approve"
        update = mock.AsyncMock()
        update.callback_query.from_user.id = 12345
        update.callback_query.data = "approve:approval-456"
        ctx = make_context()

        await bot.handle_callback(update, ctx)

        approval_server.resolve.assert_called_once_with("approval-456", allow=True)
        update.callback_query.answer.assert_called_once_with("Approved")


@pytest.mark.asyncio
async def test_deny_callback_resolves_approval():
    """Clicking Deny resolves the pending approval as deny."""
    from lailabot.approval_server import ApprovalServer

    with tempfile.TemporaryDirectory() as tmp:
        bot = make_bot(tmp)

        approval_server = mock.MagicMock(spec=ApprovalServer)
        bot.approval_server = approval_server

        update = mock.AsyncMock()
        update.callback_query.from_user.id = 12345
        update.callback_query.data = "deny:approval-789"
        ctx = make_context()

        await bot.handle_callback(update, ctx)

        approval_server.resolve.assert_called_once_with("approval-789", allow=False)
        update.callback_query.answer.assert_called_once_with("Denied")


# --- Discover + Attach ---


@pytest.mark.asyncio
async def test_discover_shows_sessions_with_pid():
    """Discover should display PID in button text for disambiguation."""
    with tempfile.TemporaryDirectory() as tmp:
        bot = make_bot(tmp)
        update = make_update("/discover")
        ctx = make_context()

        fake_sessions = [
            {"pid": 111, "session_id": "sess-a", "cwd": "/path/project", "started_at": 2000},
            {"pid": 222, "session_id": "sess-b", "cwd": "/path/project", "started_at": 1000},
        ]
        with mock.patch("lailabot.telegram_bot.discover_claude_sessions", return_value=fake_sessions):
            await bot.handle_discover(update, ctx)

        call_kwargs = update.message.reply_text.call_args[1] if update.message.reply_text.call_args[1] else {}
        call_args = update.message.reply_text.call_args[0]
        text = call_args[0]
        assert "PID 111" in text
        assert "PID 222" in text

        # Check buttons contain PID
        keyboard = call_kwargs.get("reply_markup") or update.message.reply_text.call_args[1]["reply_markup"]
        button_texts = [btn.text for row in keyboard.inline_keyboard for btn in row]
        assert any("PID 111" in t for t in button_texts)
        assert any("PID 222" in t for t in button_texts)


@pytest.mark.asyncio
async def test_discover_filters_already_attached():
    with tempfile.TemporaryDirectory() as tmp:
        bot = make_bot(tmp)
        # Pre-create a session with claude_session_id "sess-a"
        bot.session_manager.create_session("/path/a")
        bot.session_manager.update_claude_session_id(1, "sess-a")

        update = make_update("/discover")
        ctx = make_context()

        fake_sessions = [
            {"pid": 111, "session_id": "sess-a", "cwd": "/path/a", "started_at": 2000},
            {"pid": 222, "session_id": "sess-b", "cwd": "/path/b", "started_at": 1000},
        ]
        with mock.patch("lailabot.telegram_bot.discover_claude_sessions", return_value=fake_sessions):
            await bot.handle_discover(update, ctx)

        text = update.message.reply_text.call_args[0][0]
        # sess-a should be filtered out, only sess-b shown
        assert "PID 222" in text
        assert "PID 111" not in text


@pytest.mark.asyncio
async def test_discover_no_sessions_found():
    with tempfile.TemporaryDirectory() as tmp:
        bot = make_bot(tmp)
        update = make_update("/discover")
        ctx = make_context()

        with mock.patch("lailabot.telegram_bot.discover_claude_sessions", return_value=[]):
            await bot.handle_discover(update, ctx)

        reply = update.message.reply_text.call_args[0][0]
        assert "no running" in reply.lower() or "No running" in reply


@pytest.mark.asyncio
async def test_attach_callback_creates_session_and_sets_default():
    with tempfile.TemporaryDirectory() as tmp:
        bot = make_bot(tmp)
        bot.session_manager.create_session("/existing")  # session 1, default

        bot._discovered_sessions = [
            {"pid": 111, "session_id": "sess-new", "cwd": "/new/project", "started_at": 2000},
        ]

        update = mock.AsyncMock()
        update.callback_query.from_user.id = 12345
        update.callback_query.data = "attach:0"
        ctx = make_context()

        with mock.patch("lailabot.session_manager._find_cwd_for_session", return_value="/new/project"):
            await bot.handle_callback(update, ctx)

        # Should have created session 2 and set it as default
        assert bot.session_manager.get_default_session()["id"] == 2
        session = bot.session_manager.get_session(2)
        assert session["claude_session_id"] == "sess-new"
        assert session["attached"] is True
        update.callback_query.answer.assert_called_once()


@pytest.mark.asyncio
async def test_attach_callback_expired_index():
    with tempfile.TemporaryDirectory() as tmp:
        bot = make_bot(tmp)
        bot._discovered_sessions = []  # empty / expired

        update = mock.AsyncMock()
        update.callback_query.from_user.id = 12345
        update.callback_query.data = "attach:5"
        ctx = make_context()

        await bot.handle_callback(update, ctx)

        update.callback_query.answer.assert_called_once()
        answer_args = update.callback_query.answer.call_args
        assert "expired" in answer_args[0][0].lower() or "Expired" in answer_args[0][0]


@pytest.mark.asyncio
async def test_list_shows_attached_marker():
    with tempfile.TemporaryDirectory() as tmp:
        bot = make_bot(tmp)
        bot.session_manager.create_session("/normal")

        # Manually add an attached session
        bot.session_manager._sessions[2] = {
            "id": 2, "work_dir": "/attached", "claude_session_id": "sess-x",
            "created_at": 0, "attached": True,
        }
        bot.session_manager._next_id = 3
        bot.session_manager._save()

        update = make_update("/list")
        ctx = make_context()
        await bot.handle_list(update, ctx)

        reply = update.message.reply_text.call_args[0][0]
        assert "[attached]" in reply
        # The non-attached session should NOT have the marker
        lines = reply.strip().split("\n")
        normal_line = [l for l in lines if "/normal" in l][0]
        assert "[attached]" not in normal_line


# --- Always Allow ---


def test_derive_pattern_bash():
    pattern = LailaBot._derive_pattern("Bash", {"command": "git status"})
    assert pattern == "Bash:git"


def test_derive_pattern_bash_complex_command():
    pattern = LailaBot._derive_pattern("Bash", {"command": "npm run test --watch"})
    assert pattern == "Bash:npm"


def test_derive_pattern_bash_empty_command():
    pattern = LailaBot._derive_pattern("Bash", {"command": ""})
    assert pattern == "Bash"


def test_derive_pattern_non_bash():
    pattern = LailaBot._derive_pattern("Edit", {"file_path": "/foo.py"})
    assert pattern == "Edit"


def test_pattern_display():
    assert LailaBot._pattern_display("Bash:git") == "Bash(git:*)"
    assert LailaBot._pattern_display("Edit") == "Edit"


def test_matches_allowlist_exact_tool():
    with tempfile.TemporaryDirectory() as tmp:
        bot = make_bot(tmp)
        bot._session_allowlist["sess-1"] = {"Edit"}

        assert bot._matches_allowlist("sess-1", "Edit", {}) is True
        assert bot._matches_allowlist("sess-1", "Read", {}) is False
        assert bot._matches_allowlist("sess-2", "Edit", {}) is False


def test_matches_allowlist_bash_pattern():
    with tempfile.TemporaryDirectory() as tmp:
        bot = make_bot(tmp)
        bot._session_allowlist["sess-1"] = {"Bash:git"}

        assert bot._matches_allowlist("sess-1", "Bash", {"command": "git status"}) is True
        assert bot._matches_allowlist("sess-1", "Bash", {"command": "git push"}) is True
        assert bot._matches_allowlist("sess-1", "Bash", {"command": "rm -rf /"}) is False
        assert bot._matches_allowlist("sess-1", "Bash", {"command": ""}) is False


@pytest.mark.asyncio
async def test_approval_request_auto_approves_when_allowlisted():
    from lailabot.approval_server import ApprovalServer

    with tempfile.TemporaryDirectory() as tmp:
        bot = make_bot(tmp)
        approval_server = mock.MagicMock(spec=ApprovalServer)
        bot.approval_server = approval_server
        bot._telegram_bot = mock.AsyncMock()

        # Add git to allowlist for this session
        bot._session_allowlist["claude-sess-1"] = {"Bash:git"}

        request_data = {
            "session_id": "claude-sess-1",
            "tool_name": "Bash",
            "tool_input": {"command": "git diff"},
        }

        await bot.handle_approval_request("approval-auto", request_data)

        # Should auto-approve without sending Telegram message
        approval_server.resolve.assert_called_once_with("approval-auto", allow=True)
        bot._telegram_bot.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_approval_request_sends_always_allow_button():
    from telegram import InlineKeyboardMarkup

    with tempfile.TemporaryDirectory() as tmp:
        bot = make_bot(tmp)
        bot._telegram_bot = mock.AsyncMock()

        request_data = {
            "session_id": "claude-sess-1",
            "tool_name": "Bash",
            "tool_input": {"command": "git push origin main"},
        }

        await bot.handle_approval_request("approval-btn", request_data)

        call_kwargs = bot._telegram_bot.send_message.call_args[1]
        keyboard = call_kwargs["reply_markup"]
        assert isinstance(keyboard, InlineKeyboardMarkup)

        # Should have 2 rows: [Approve, Deny] and [Always Allow ...]
        assert len(keyboard.inline_keyboard) == 2
        always_btn = keyboard.inline_keyboard[1][0]
        assert "Always Allow" in always_btn.text
        assert "Bash(git:*)" in always_btn.text
        assert always_btn.callback_data == "always:approval-btn"


@pytest.mark.asyncio
async def test_always_allow_callback_adds_to_allowlist_and_resolves():
    from lailabot.approval_server import ApprovalServer

    with tempfile.TemporaryDirectory() as tmp:
        bot = make_bot(tmp)
        approval_server = mock.MagicMock(spec=ApprovalServer)
        bot.approval_server = approval_server

        # Simulate a pending request
        bot._pending_requests["approval-aa"] = {
            "session_id": "claude-sess-1",
            "tool_name": "Bash",
            "tool_input": {"command": "npm test"},
        }

        update = mock.AsyncMock()
        update.callback_query.from_user.id = 12345
        update.callback_query.data = "always:approval-aa"
        ctx = make_context()

        await bot.handle_callback(update, ctx)

        # Should resolve the approval
        approval_server.resolve.assert_called_once_with("approval-aa", allow=True)

        # Should add pattern to session allowlist
        assert "Bash:npm" in bot._session_allowlist["claude-sess-1"]

        # Should clean up pending request
        assert "approval-aa" not in bot._pending_requests


@pytest.mark.asyncio
async def test_always_allow_callback_expired():
    with tempfile.TemporaryDirectory() as tmp:
        bot = make_bot(tmp)
        # No pending request for this ID

        update = mock.AsyncMock()
        update.callback_query.from_user.id = 12345
        update.callback_query.data = "always:expired-id"
        ctx = make_context()

        await bot.handle_callback(update, ctx)

        update.callback_query.answer.assert_called_once()
        answer_args = update.callback_query.answer.call_args
        assert "expired" in answer_args[0][0].lower() or "Expired" in answer_args[0][0]
