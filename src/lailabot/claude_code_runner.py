import asyncio
import json
import signal
from collections.abc import Awaitable, Callable


class ClaudeCodeRunner:
    def __init__(self):
        self._queues: dict[int, asyncio.Queue] = {}
        self._workers: dict[int, asyncio.Task] = {}

    async def send_message(
        self,
        message: str,
        work_dir: str,
        claude_session_id: str | None,
        on_chunk: Callable[[str], Awaitable[None]],
    ) -> str:
        cmd = [
            "claude", "-p", message,
            "--output-format", "stream-json",
            "--verbose",
        ]
        if claude_session_id:
            cmd.extend(["--resume", claude_session_id])

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=work_dir,
        )

        session_id = claude_session_id

        async for line in proc.stdout:
            line = line.decode().strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            event_type = event.get("type")

            if event_type == "system" and event.get("subtype") == "init":
                session_id = event.get("session_id", session_id)
            elif event_type == "assistant":
                msg = event.get("message", {})
                for block in msg.get("content", []):
                    if block.get("type") == "text":
                        await on_chunk(block["text"])
            elif event_type == "result":
                session_id = event.get("session_id", session_id)

        await proc.wait()
        return session_id

    def enqueue(
        self,
        session_key: int,
        message: str,
        work_dir: str,
        claude_session_id: str | None,
        on_chunk: Callable[[str], Awaitable[None]],
    ) -> asyncio.Future:
        loop = asyncio.get_event_loop()
        future = loop.create_future()

        if session_key not in self._queues:
            self._queues[session_key] = asyncio.Queue()
            self._workers[session_key] = asyncio.create_task(
                self._worker(session_key)
            )

        self._queues[session_key].put_nowait(
            (message, work_dir, claude_session_id, on_chunk, future)
        )
        return future

    async def _worker(self, session_key: int):
        queue = self._queues[session_key]
        while True:
            message, work_dir, claude_session_id, on_chunk, future = await queue.get()
            try:
                result = await self.send_message(
                    message=message,
                    work_dir=work_dir,
                    claude_session_id=claude_session_id,
                    on_chunk=on_chunk,
                )
                future.set_result(result)
            except Exception as e:
                future.set_exception(e)
            finally:
                queue.task_done()

    def kill(self, pid: int) -> None:
        import os
        os.kill(pid, signal.SIGKILL)
