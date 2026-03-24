import asyncio
import json
import logging
import os

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TimedOut, NetworkError

from lailabot.session_manager import SessionManager, discover_claude_sessions
from lailabot.claude_code_runner import ClaudeCodeRunner
from lailabot.message_formatter import split_message

logger = logging.getLogger(__name__)


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
        self._telegram_bot = None  # Set externally after Application is built
        self.approval_server = None  # Set externally
        self._discovered_sessions: list[dict] = []
        # Per Claude session ID -> set of allowed patterns (e.g. "Bash:git", "Edit")
        self._session_allowlist: dict[str, set[str]] = {}
        # Pending approval request data keyed by approval_id
        self._pending_requests: dict[str, dict] = {}

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
            attached = " [attached]" if s.get("attached") else ""
            lines.append(f"[{s['id']}] {s['work_dir']}{marker}{attached}")
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

    async def handle_discover(self, update, context):
        if not self._is_authorized(update.effective_user.id):
            return

        sessions = discover_claude_sessions()
        if not sessions:
            await update.message.reply_text("No running Claude Code sessions found.")
            return

        existing_claude_ids = {
            s["claude_session_id"]
            for s in self.session_manager.list_sessions()
            if s.get("claude_session_id")
        }
        sessions = [s for s in sessions if s["session_id"] not in existing_claude_ids]

        if not sessions:
            await update.message.reply_text("All discovered sessions are already attached.")
            return

        self._discovered_sessions = sessions

        lines = []
        buttons = []
        for i, s in enumerate(sessions):
            cwd_short = s["cwd"].replace(os.path.expanduser("~"), "~")
            lines.append(f"{i + 1}. PID {s['pid']} - {cwd_short}")
            buttons.append([
                InlineKeyboardButton(
                    f"Attach: PID {s['pid']} {cwd_short}",
                    callback_data=f"attach:{i}",
                )
            ])

        text = "Discovered Claude Code sessions:\n\n" + "\n".join(lines)
        keyboard = InlineKeyboardMarkup(buttons)
        await update.message.reply_text(text, reply_markup=keyboard)

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

    @staticmethod
    def _derive_pattern(tool_name: str, tool_input: dict) -> str:
        """Derive an allowlist pattern from a tool invocation.

        Returns patterns like "Bash:git", "Bash:npm", "Edit", "Read", etc.
        For Bash, uses the first word of the command as the prefix.
        """
        if tool_name == "Bash":
            cmd = tool_input.get("command", "")
            parts = cmd.split()
            if parts:
                return f"Bash:{parts[0]}"
        return tool_name

    @staticmethod
    def _pattern_display(pattern: str) -> str:
        """Human-readable display of an allowlist pattern."""
        if ":" in pattern:
            tool, prefix = pattern.split(":", 1)
            return f"{tool}({prefix}:*)"
        return pattern

    def _matches_allowlist(self, claude_session_id: str, tool_name: str, tool_input: dict) -> bool:
        patterns = self._session_allowlist.get(claude_session_id, set())
        if not patterns:
            return False
        if tool_name in patterns:
            return True
        if tool_name == "Bash":
            cmd = tool_input.get("command", "")
            parts = cmd.split()
            if parts and f"Bash:{parts[0]}" in patterns:
                return True
        return False

    async def handle_approval_request(self, approval_id: str, request_data: dict):
        tool_name = request_data.get("tool_name", "Unknown")
        tool_input = request_data.get("tool_input", {})
        claude_session_id = request_data.get("session_id", "")

        # Auto-approve if matches session allowlist
        if claude_session_id and self._matches_allowlist(claude_session_id, tool_name, tool_input):
            logger.info(f"[{approval_id}] Auto-approved by allowlist for session {claude_session_id}")
            if self.approval_server:
                self.approval_server.resolve(approval_id, allow=True)
            return

        # Store request data for "Always Allow" callback
        self._pending_requests[approval_id] = request_data

        input_summary = json.dumps(tool_input, indent=2, ensure_ascii=False)
        if len(input_summary) > 1000:
            input_summary = input_summary[:1000] + "\n..."

        pattern = self._derive_pattern(tool_name, tool_input)
        always_label = f"Always Allow {self._pattern_display(pattern)}"

        text = f"Permission Request\n\nTool: {tool_name}\nInput:\n{input_summary}"

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Approve", callback_data=f"approve:{approval_id}"),
                InlineKeyboardButton("Deny", callback_data=f"deny:{approval_id}"),
            ],
            [
                InlineKeyboardButton(always_label, callback_data=f"always:{approval_id}"),
            ],
        ])

        logger.info(f"[{approval_id}] Sending approval request to Telegram: {tool_name}")

        max_retries = 3
        for attempt in range(1, max_retries + 1):
            try:
                await self._telegram_bot.send_message(
                    chat_id=self.authorized_user_id,
                    text=text,
                    reply_markup=keyboard,
                )
                logger.info(f"[{approval_id}] Telegram message sent successfully")
                return
            except (TimedOut, NetworkError) as e:
                if attempt < max_retries:
                    delay = attempt * 2
                    logger.warning(
                        f"[{approval_id}] Telegram send attempt {attempt}/{max_retries} "
                        f"failed ({type(e).__name__}), retrying in {delay}s..."
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.exception(f"[{approval_id}] Failed to send Telegram message after {max_retries} attempts")
                    raise

    async def handle_callback(self, update, context):
        query = update.callback_query
        user_id = query.from_user.id

        if not self._is_authorized(user_id):
            logger.warning(f"Unauthorized callback from user={user_id}")
            return

        data = query.data or ""
        if data.startswith("approve:") or data.startswith("deny:"):
            await self._handle_approval_callback(query)
        elif data.startswith("always:"):
            await self._handle_always_allow_callback(query)
        elif data.startswith("attach:"):
            await self._handle_attach_callback(query)
        else:
            logger.warning(f"Unknown callback data: {data!r}")

    async def _handle_approval_callback(self, query):
        data = query.data

        if not data or ":" not in data:
            logger.warning(f"Invalid callback data: {data!r}")
            return

        action, approval_id = data.split(":", 1)
        allow = action == "approve"

        logger.info(f"[{approval_id}] User chose: {action}")

        self._pending_requests.pop(approval_id, None)

        resolved = False
        if self.approval_server:
            resolved = self.approval_server.resolve(approval_id, allow=allow)
            logger.info(f"[{approval_id}] resolve() returned {resolved}")
        else:
            logger.error(f"[{approval_id}] No approval_server attached!")

        if resolved:
            label = "Approved" if allow else "Denied"
            await query.answer(label)
        else:
            await query.answer("Expired (stale button)", show_alert=True)

        await query.edit_message_reply_markup(reply_markup=None)
        logger.info(f"[{approval_id}] Telegram UI updated")

    async def _handle_always_allow_callback(self, query):
        _, approval_id = query.data.split(":", 1)
        request_data = self._pending_requests.pop(approval_id, None)

        if not request_data:
            await query.answer("Expired (stale button)", show_alert=True)
            await query.edit_message_reply_markup(reply_markup=None)
            return

        tool_name = request_data.get("tool_name", "")
        tool_input = request_data.get("tool_input", {})
        claude_session_id = request_data.get("session_id", "")

        pattern = self._derive_pattern(tool_name, tool_input)

        if claude_session_id:
            if claude_session_id not in self._session_allowlist:
                self._session_allowlist[claude_session_id] = set()
            self._session_allowlist[claude_session_id].add(pattern)
            logger.info(f"[{approval_id}] Added '{pattern}' to allowlist for session {claude_session_id}")

        resolved = False
        if self.approval_server:
            resolved = self.approval_server.resolve(approval_id, allow=True)

        if resolved:
            display = self._pattern_display(pattern)
            await query.answer(f"Always allowed: {display}")
        else:
            await query.answer("Expired (stale button)", show_alert=True)

        await query.edit_message_reply_markup(reply_markup=None)

    async def _handle_attach_callback(self, query):
        data = query.data
        parts = data.split(":", 1)
        if len(parts) != 2:
            await query.answer("Invalid attach data")
            return

        try:
            idx = int(parts[1])
        except ValueError:
            await query.answer("Invalid index")
            return

        if idx < 0 or idx >= len(self._discovered_sessions):
            await query.answer("Session list expired. Run /discover again.", show_alert=True)
            return

        session = self._discovered_sessions[idx]
        claude_session_id = session["session_id"]
        cwd_short = session["cwd"].replace(os.path.expanduser("~"), "~")

        try:
            sid = self.session_manager.attach_session(claude_session_id)
            await query.answer(f"Attached as session {sid}")
            await query.edit_message_text(
                f"Attached to session in {cwd_short}\nLailaBot session ID: {sid}"
            )
        except ValueError as e:
            await query.answer(str(e), show_alert=True)
