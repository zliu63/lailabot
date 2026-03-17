import os

from lailabot.session_manager import SessionManager
from lailabot.claude_code_runner import ClaudeCodeRunner
from lailabot.message_formatter import split_message


class LailaBot:
    def __init__(
        self,
        bot_token: str,
        authorized_user_id: int,
        session_persistence_path: str = "~/.lailabot/sessions.json",
    ):
        self.bot_token = bot_token
        self.authorized_user_id = authorized_user_id
        self.session_manager = SessionManager(persistence_path=session_persistence_path)
        self.runner = ClaudeCodeRunner()

    def _is_authorized(self, user_id: int) -> bool:
        return user_id == self.authorized_user_id

    async def handle_message(self, update, context):
        if not self._is_authorized(update.effective_user.id):
            return

        default = self.session_manager.get_default_session()
        if default is None:
            await update.message.reply_text(
                "No active session. Use /new {path} to start one."
            )
            return

        await self._send_to_session(default, update.message.text, update)

    async def handle_new(self, update, context):
        if not self._is_authorized(update.effective_user.id):
            return

        if not context.args:
            await update.message.reply_text("Usage: /new {path}")
            return

        path = os.path.expanduser(context.args[0])
        if not os.path.isdir(path):
            await update.message.reply_text(f"Directory does not exist: {path}")
            return

        try:
            sid = self.session_manager.create_session(path)
            await update.message.reply_text(f"Session {sid} created in {path}")
        except ValueError as e:
            await update.message.reply_text(str(e))

    async def handle_start(self, update, context):
        if not self._is_authorized(update.effective_user.id):
            return
        await update.message.reply_text(
            "Welcome to LailaBot! Use /new {path} to start a Claude Code session."
        )

    async def handle_ls(self, update, context):
        if not self._is_authorized(update.effective_user.id):
            return

        path = os.path.expanduser(context.args[0] if context.args else "~")
        if not os.path.isdir(path):
            await update.message.reply_text(f"Directory does not exist: {path}")
            return

        entries = sorted(os.listdir(path))
        text = "\n".join(entries) if entries else "(empty directory)"
        await update.message.reply_text(text)

    async def handle_list(self, update, context):
        if not self._is_authorized(update.effective_user.id):
            return

        sessions = self.session_manager.list_sessions()
        if not sessions:
            await update.message.reply_text("No active sessions.")
            return

        lines = []
        for s in sessions:
            marker = " (default)" if s["is_default"] else ""
            lines.append(f"[{s['id']}] {s['work_dir']}{marker}")
        await update.message.reply_text("\n".join(lines))

    async def handle_kill(self, update, context):
        if not self._is_authorized(update.effective_user.id):
            return

        if not context.args:
            await update.message.reply_text("Usage: /kill {session_id}")
            return

        try:
            sid = int(context.args[0])
            self.session_manager.kill_session(sid)
            await update.message.reply_text(f"Session {sid} killed.")
        except (ValueError, KeyError) as e:
            await update.message.reply_text(str(e))

    async def handle_set_default(self, update, context):
        if not self._is_authorized(update.effective_user.id):
            return

        if not context.args:
            await update.message.reply_text("Usage: /set_default {session_id}")
            return

        try:
            sid = int(context.args[0])
            self.session_manager.set_default(sid)
            await update.message.reply_text(f"Default session set to {sid}.")
        except ValueError as e:
            await update.message.reply_text(str(e))

    async def handle_send(self, update, context):
        if not self._is_authorized(update.effective_user.id):
            return

        if not context.args or len(context.args) < 2:
            await update.message.reply_text("Usage: /send {session_id} {message}")
            return

        try:
            sid = int(context.args[0])
        except ValueError:
            await update.message.reply_text("Invalid session ID.")
            return

        session = self.session_manager.get_session(sid)
        if session is None:
            await update.message.reply_text(f"Session {sid} not found.")
            return

        message = " ".join(context.args[1:])
        await self._send_to_session(session, message, update)

    async def _send_to_session(self, session, message, update):
        accumulated = []

        async def on_chunk(text):
            accumulated.append(text)

        try:
            claude_session_id = await self.runner.send_message(
                message=message,
                work_dir=session["work_dir"],
                claude_session_id=session["claude_session_id"],
                on_chunk=on_chunk,
            )
            self.session_manager.update_claude_session_id(
                session["id"], claude_session_id
            )
        except Exception as e:
            await update.message.reply_text(f"Error: {e}")
            return

        full_response = "".join(accumulated)
        if not full_response:
            await update.message.reply_text("(no response)")
            return

        for chunk in split_message(full_response):
            await update.message.reply_text(chunk)
