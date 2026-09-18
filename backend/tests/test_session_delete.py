import threading

from app.persistence.sessions import SessionArchive
from app.api import routes_engine


def test_deleted_session_stays_hidden_after_snapshot_and_restart(tmp_path):
    archive = SessionArchive(tmp_path)
    archive.save('ex_first', {'exploration_id': 'ex_first', 'started_at': 1})
    archive.save('ex_second', {'exploration_id': 'ex_second', 'started_at': 2})
    assert archive.delete('ex_first')
    archive.save('ex_first', {'exploration_id': 'ex_first', 'status': 'COMPLETE'})
    restarted = SessionArchive(tmp_path)
    assert restarted.get('ex_first') is None
    assert (tmp_path / 'ex_first.json').exists()
    assert [(row['exploration_id'], row['session_no']) for row in restarted.list()] == [('ex_second', 2)]
    assert not restarted.delete('ex_missing')


def test_delete_route_requests_cancellation(tmp_path, monkeypatch):
    archive = SessionArchive(tmp_path)
    archive.save('ex_live', {'exploration_id': 'ex_live'})
    cancel = threading.Event()
    monkeypatch.setattr(routes_engine, '_sessions', archive)
    monkeypatch.setattr(routes_engine, '_active', {'ex_live': cancel})
    assert routes_engine.delete_session('ex_live')['deleted']
    assert cancel.is_set()
    assert not archive.list()
