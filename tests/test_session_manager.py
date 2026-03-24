import json
import os
import tempfile
import unittest.mock as mock

from lailabot.session_manager import SessionManager, discover_claude_sessions


def make_manager(tmp_path):
    return SessionManager(persistence_path=os.path.join(tmp_path, "sessions.json"))


def test_create_session_returns_id_1_and_becomes_default():
    with tempfile.TemporaryDirectory() as tmp:
        mgr = make_manager(tmp)
        sid = mgr.create_session("/some/path")
        assert sid == 1
        default = mgr.get_default_session()
        assert default is not None
        assert default["id"] == 1
        assert default["work_dir"] == "/some/path"


def test_second_session_gets_id_2_first_remains_default():
    with tempfile.TemporaryDirectory() as tmp:
        mgr = make_manager(tmp)
        mgr.create_session("/path/a")
        sid2 = mgr.create_session("/path/b")
        assert sid2 == 2
        assert mgr.get_default_session()["id"] == 1


def test_list_sessions_returns_all():
    with tempfile.TemporaryDirectory() as tmp:
        mgr = make_manager(tmp)
        mgr.create_session("/path/a")
        mgr.create_session("/path/b")
        sessions = mgr.list_sessions()
        assert len(sessions) == 2
        assert sessions[0]["id"] == 1
        assert sessions[1]["id"] == 2
        assert sessions[0]["is_default"] is True
        assert sessions[1]["is_default"] is False


def test_set_default_switches_default():
    with tempfile.TemporaryDirectory() as tmp:
        mgr = make_manager(tmp)
        mgr.create_session("/path/a")
        mgr.create_session("/path/b")
        mgr.set_default(2)
        assert mgr.get_default_session()["id"] == 2


def test_kill_default_session_promotes_next():
    with tempfile.TemporaryDirectory() as tmp:
        mgr = make_manager(tmp)
        mgr.create_session("/path/a")
        mgr.create_session("/path/b")
        mgr.kill_session(1)
        assert len(mgr.list_sessions()) == 1
        assert mgr.get_default_session()["id"] == 2


def test_kill_last_session_leaves_no_default():
    with tempfile.TemporaryDirectory() as tmp:
        mgr = make_manager(tmp)
        mgr.create_session("/path/a")
        mgr.kill_session(1)
        assert len(mgr.list_sessions()) == 0
        assert mgr.get_default_session() is None


def test_max_10_sessions():
    with tempfile.TemporaryDirectory() as tmp:
        mgr = make_manager(tmp)
        for i in range(10):
            mgr.create_session(f"/path/{i}")
        try:
            mgr.create_session("/path/11")
            assert False, "Should have raised"
        except ValueError as e:
            assert "maximum" in str(e).lower()


def test_kill_nonexistent_session_raises():
    with tempfile.TemporaryDirectory() as tmp:
        mgr = make_manager(tmp)
        try:
            mgr.kill_session(999)
            assert False, "Should have raised"
        except ValueError:
            pass


def test_set_default_invalid_id_raises():
    with tempfile.TemporaryDirectory() as tmp:
        mgr = make_manager(tmp)
        mgr.create_session("/path/a")
        try:
            mgr.set_default(999)
            assert False, "Should have raised"
        except ValueError:
            pass


def test_persistence_restores_sessions():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "sessions.json")
        mgr1 = SessionManager(persistence_path=path)
        mgr1.create_session("/path/a")
        mgr1.create_session("/path/b")
        mgr1.set_default(2)

        # Create a new manager from the same file
        mgr2 = SessionManager(persistence_path=path)
        sessions = mgr2.list_sessions()
        assert len(sessions) == 2
        assert mgr2.get_default_session()["id"] == 2
        # Next ID should continue from where we left off
        sid3 = mgr2.create_session("/path/c")
        assert sid3 == 3


def test_get_session_and_update_claude_session_id():
    with tempfile.TemporaryDirectory() as tmp:
        mgr = make_manager(tmp)
        mgr.create_session("/path/a")
        session = mgr.get_session(1)
        assert session is not None
        assert session["claude_session_id"] is None

        mgr.update_claude_session_id(1, "abc-123")
        session = mgr.get_session(1)
        assert session["claude_session_id"] == "abc-123"

        assert mgr.get_session(999) is None


# --- discover_claude_sessions ---


def _write_session_file(sessions_dir, pid, session_id, cwd, started_at=1000):
    os.makedirs(sessions_dir, exist_ok=True)
    with open(os.path.join(sessions_dir, f"{pid}.json"), "w") as f:
        json.dump({"pid": pid, "sessionId": session_id, "cwd": cwd, "startedAt": started_at}, f)


def test_discover_returns_live_sessions():
    with tempfile.TemporaryDirectory() as tmp:
        sessions_dir = os.path.join(tmp, "sessions")
        my_pid = os.getpid()  # guaranteed alive
        _write_session_file(sessions_dir, my_pid, "sess-aaa", "/path/a", 2000)

        results = discover_claude_sessions(sessions_dir)
        assert len(results) == 1
        assert results[0]["pid"] == my_pid
        assert results[0]["session_id"] == "sess-aaa"
        assert results[0]["cwd"] == "/path/a"


def test_discover_filters_dead_pids():
    with tempfile.TemporaryDirectory() as tmp:
        sessions_dir = os.path.join(tmp, "sessions")
        dead_pid = 99999999  # almost certainly not alive
        _write_session_file(sessions_dir, dead_pid, "sess-dead", "/path/dead")

        results = discover_claude_sessions(sessions_dir)
        assert len(results) == 0


def test_discover_skips_malformed_json():
    with tempfile.TemporaryDirectory() as tmp:
        sessions_dir = os.path.join(tmp, "sessions")
        os.makedirs(sessions_dir)
        with open(os.path.join(sessions_dir, "bad.json"), "w") as f:
            f.write("not json{{{")

        results = discover_claude_sessions(sessions_dir)
        assert len(results) == 0


def test_discover_skips_missing_fields():
    with tempfile.TemporaryDirectory() as tmp:
        sessions_dir = os.path.join(tmp, "sessions")
        os.makedirs(sessions_dir)
        with open(os.path.join(sessions_dir, "123.json"), "w") as f:
            json.dump({"pid": 123}, f)  # missing sessionId and cwd

        results = discover_claude_sessions(sessions_dir)
        assert len(results) == 0


def test_discover_returns_empty_for_nonexistent_dir():
    results = discover_claude_sessions("/nonexistent/path/sessions")
    assert results == []


def test_discover_sorts_by_started_at_descending():
    with tempfile.TemporaryDirectory() as tmp:
        sessions_dir = os.path.join(tmp, "sessions")
        my_pid = os.getpid()
        _write_session_file(sessions_dir, my_pid, "sess-old", "/old", 1000)
        # Use same pid file trick: write a second file with different name
        with open(os.path.join(sessions_dir, f"{my_pid}_2.json"), "w") as f:
            json.dump({"pid": my_pid, "sessionId": "sess-new", "cwd": "/new", "startedAt": 3000}, f)

        results = discover_claude_sessions(sessions_dir)
        assert len(results) == 2
        assert results[0]["session_id"] == "sess-new"
        assert results[1]["session_id"] == "sess-old"


# --- attach_session ---


def test_attach_session_sets_default_and_populates_fields():
    with tempfile.TemporaryDirectory() as tmp:
        sessions_dir = os.path.join(tmp, "claude_sessions")
        my_pid = os.getpid()
        _write_session_file(sessions_dir, my_pid, "sess-xyz", "/work/dir")

        mgr = make_manager(tmp)
        mgr.create_session("/other/path")  # session 1, currently default

        with mock.patch("lailabot.session_manager.CLAUDE_SESSIONS_DIR", sessions_dir):
            sid = mgr.attach_session("sess-xyz")

        assert sid == 2
        session = mgr.get_session(2)
        assert session["claude_session_id"] == "sess-xyz"
        assert session["work_dir"] == "/work/dir"
        assert session["attached"] is True
        # Should be the new default
        assert mgr.get_default_session()["id"] == 2


def test_attach_session_always_becomes_default():
    """attach_session should unconditionally set the attached session as default."""
    with tempfile.TemporaryDirectory() as tmp:
        sessions_dir = os.path.join(tmp, "claude_sessions")
        my_pid = os.getpid()
        # Use different filenames to avoid overwriting
        os.makedirs(sessions_dir, exist_ok=True)
        with open(os.path.join(sessions_dir, "100.json"), "w") as f:
            json.dump({"pid": my_pid, "sessionId": "sess-1", "cwd": "/dir1", "startedAt": 1000}, f)
        with open(os.path.join(sessions_dir, "200.json"), "w") as f:
            json.dump({"pid": my_pid, "sessionId": "sess-2", "cwd": "/dir2", "startedAt": 2000}, f)

        mgr = make_manager(tmp)
        mgr.create_session("/existing")  # session 1, default

        with mock.patch("lailabot.session_manager.CLAUDE_SESSIONS_DIR", sessions_dir):
            mgr.attach_session("sess-1")  # becomes default
            mgr.attach_session("sess-2")  # should override default

        assert mgr.get_default_session()["id"] == 3  # sess-2


def test_attach_session_not_found_raises():
    with tempfile.TemporaryDirectory() as tmp:
        sessions_dir = os.path.join(tmp, "claude_sessions")
        os.makedirs(sessions_dir)

        mgr = make_manager(tmp)
        with mock.patch("lailabot.session_manager.CLAUDE_SESSIONS_DIR", sessions_dir):
            try:
                mgr.attach_session("nonexistent-session")
                assert False, "Should have raised"
            except ValueError as e:
                assert "nonexistent-session" in str(e)


def test_attach_session_respects_max_sessions():
    with tempfile.TemporaryDirectory() as tmp:
        sessions_dir = os.path.join(tmp, "claude_sessions")
        my_pid = os.getpid()
        _write_session_file(sessions_dir, my_pid, "sess-extra", "/extra")

        mgr = make_manager(tmp)
        for i in range(10):
            mgr.create_session(f"/path/{i}")

        with mock.patch("lailabot.session_manager.CLAUDE_SESSIONS_DIR", sessions_dir):
            try:
                mgr.attach_session("sess-extra")
                assert False, "Should have raised"
            except ValueError as e:
                assert "maximum" in str(e).lower()
