import asyncio
import json
import os
import uuid
from collections.abc import Awaitable, Callable


DEFAULT_SOCKET_PATH = "/tmp/lailabot-approval.sock"
DEFAULT_TIMEOUT = 600  # 10 minutes


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
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        if os.path.exists(self.socket_path):
            os.unlink(self.socket_path)
        for future in self._pending.values():
            if not future.done():
                future.cancel()
        self._pending.clear()

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            line = await asyncio.wait_for(reader.readline(), timeout=10)
            if not line:
                return
            request = json.loads(line.decode())

            approval_id = str(uuid.uuid4())
            future = asyncio.get_event_loop().create_future()
            self._pending[approval_id] = future

            if self.on_request:
                await self.on_request(approval_id, request)

            try:
                decision = await asyncio.wait_for(future, timeout=self.timeout)
            except asyncio.TimeoutError:
                decision = {"behavior": "deny"}
            finally:
                self._pending.pop(approval_id, None)

            response = {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "decision": decision,
                }
            }
            writer.write(json.dumps(response).encode() + b"\n")
            await writer.drain()
        except Exception:
            pass
        finally:
            writer.close()
            await writer.wait_closed()

    def resolve(self, approval_id: str, allow: bool):
        future = self._pending.get(approval_id)
        if future and not future.done():
            decision = {"behavior": "allow"} if allow else {"behavior": "deny"}
            future.set_result(decision)
