import asyncio
import json
import logging
import os
import uuid
from collections.abc import Awaitable, Callable


DEFAULT_SOCKET_PATH = "/tmp/lailabot-approval.sock"
DEFAULT_TIMEOUT = 600  # 10 minutes

logger = logging.getLogger(__name__)


class ApprovalServer:
    def __init__(self, socket_path: str = DEFAULT_SOCKET_PATH):
        self.socket_path = socket_path
        self.timeout = DEFAULT_TIMEOUT
        self._server: asyncio.AbstractServer | None = None
        self._pending: dict[str, asyncio.Future] = {}
        self.on_request: Callable[[str, dict], Awaitable[None]] | None = None

    async def start(self):
        if os.path.exists(self.socket_path):
            os.unlink(self.socket_path)
        self._server = await asyncio.start_unix_server(
            self._handle_client, self.socket_path
        )

    async def stop(self):
        for future in self._pending.values():
            if not future.done():
                future.cancel()
        self._pending.clear()
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        if os.path.exists(self.socket_path):
            os.unlink(self.socket_path)

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        approval_id = None
        try:
            line = await asyncio.wait_for(reader.readline(), timeout=10)
            if not line:
                logger.warning("Empty connection from hook script")
                return
            request = json.loads(line.decode())
            tool_name = request.get("tool_name", "?")

            approval_id = str(uuid.uuid4())
            logger.info(f"[{approval_id}] Received approval request for {tool_name}")

            future = asyncio.get_running_loop().create_future()
            self._pending[approval_id] = future

            logger.info(f"[{approval_id}] Future created, pending_ids={list(self._pending.keys())}")

            if self.on_request:
                await self.on_request(approval_id, request)

            logger.info(f"[{approval_id}] Awaiting user decision...")
            try:
                decision = await asyncio.wait_for(future, timeout=self.timeout)
            except asyncio.TimeoutError:
                logger.warning(f"[{approval_id}] Timed out, denying")
                decision = "deny"
            except asyncio.CancelledError:
                logger.warning(f"[{approval_id}] Future cancelled while awaiting")
                decision = "deny"
            finally:
                self._pending.pop(approval_id, None)

            logger.info(f"[{approval_id}] Decision: {decision}, writing response to hook")

            response = {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": decision,
                }
            }
            writer.write(json.dumps(response).encode() + b"\n")
            await writer.drain()
        except asyncio.CancelledError:
            logger.info(f"[{approval_id}] Cancelled (server stopping)")
        except Exception:
            logger.exception(f"[{approval_id}] Error handling approval request")
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except (Exception, asyncio.CancelledError):
                pass

    def resolve(self, approval_id: str, allow: bool) -> bool:
        future = self._pending.get(approval_id)
        if future and not future.done():
            decision = "allow" if allow else "deny"
            logger.info(f"[{approval_id}] Resolved: {decision}")
            future.set_result(decision)
            return True
        else:
            logger.warning(
                f"[{approval_id}] resolve() called but no pending future found. "
                f"pending_ids={list(self._pending.keys())}"
            )
            return False
