import os
import tempfile

from lailabot.session_manager import SessionManager


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
