import json
import os
import time


class SessionManager:
    def __init__(self, persistence_path: str = "~/.lailabot/sessions.json"):
        self._path = os.path.expanduser(persistence_path)
        self._sessions: dict[int, dict] = {}
        self._default_id: int | None = None
        self._next_id = 1
        self._load()

    MAX_SESSIONS = 10

    def create_session(self, work_dir: str) -> int:
        if len(self._sessions) >= self.MAX_SESSIONS:
            raise ValueError(f"Maximum of {self.MAX_SESSIONS} sessions reached")
        sid = self._next_id
        self._next_id += 1
        self._sessions[sid] = {
            "id": sid,
            "work_dir": work_dir,
            "claude_session_id": None,
            "created_at": time.time(),
        }
        if self._default_id is None:
            self._default_id = sid
        self._save()
        return sid

    def list_sessions(self) -> list[dict]:
        return [
            {**s, "is_default": s["id"] == self._default_id}
            for s in sorted(self._sessions.values(), key=lambda x: x["id"])
        ]

    def kill_session(self, session_id: int) -> None:
        if session_id not in self._sessions:
            raise ValueError(f"Session {session_id} not found")
        del self._sessions[session_id]
        if self._default_id == session_id:
            remaining = sorted(self._sessions.keys())
            self._default_id = remaining[0] if remaining else None
        self._save()

    def set_default(self, session_id: int) -> None:
        if session_id not in self._sessions:
            raise ValueError(f"Session {session_id} not found")
        self._default_id = session_id
        self._save()

    def get_session(self, session_id: int) -> dict | None:
        return self._sessions.get(session_id)

    def update_claude_session_id(self, session_id: int, claude_session_id: str) -> None:
        if session_id not in self._sessions:
            raise ValueError(f"Session {session_id} not found")
        self._sessions[session_id]["claude_session_id"] = claude_session_id
        self._save()

    def get_default_session(self) -> dict | None:
        if self._default_id is None:
            return None
        return self._sessions.get(self._default_id)

    def _save(self):
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        data = {
            "sessions": {str(k): v for k, v in self._sessions.items()},
            "default_id": self._default_id,
            "next_id": self._next_id,
        }
        with open(self._path, "w") as f:
            json.dump(data, f)

    def _load(self):
        if not os.path.exists(self._path):
            return
        with open(self._path) as f:
            data = json.load(f)
        self._sessions = {int(k): v for k, v in data["sessions"].items()}
        self._default_id = data["default_id"]
        self._next_id = data["next_id"]
