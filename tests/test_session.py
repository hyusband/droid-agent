import os
import time

from droid_agent import session as sess


def test_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("DROID_AGENT_HOME", str(tmp_path))
    s = sess.Session(device="emulator-5554", dumped_at=time.time(),
                     elements=[{"ref": 1, "center": [10, 20], "label": "OK"}])
    sess.save(s)
    loaded = sess.load()
    assert loaded is not None
    assert loaded.device == "emulator-5554"
    assert not loaded.is_stale
    el = sess.resolve_ref(loaded, 1)
    assert el["center"] == [10, 20]
    assert sess.resolve_ref(loaded, 99) is None


def test_stale(tmp_path, monkeypatch):
    monkeypatch.setenv("DROID_AGENT_HOME", str(tmp_path))
    s = sess.Session(device="x", dumped_at=time.time() - 9999, elements=[])
    sess.save(s)
    assert sess.load().is_stale


def test_missing_returns_none(tmp_path, monkeypatch):
    monkeypatch.setenv("DROID_AGENT_HOME", str(tmp_path))
    assert sess.load() is None


def test_corrupt_returns_none(tmp_path, monkeypatch):
    monkeypatch.setenv("DROID_AGENT_HOME", str(tmp_path))
    path = os.path.join(str(tmp_path), "session.json")
    with open(path, "w") as fh:
        fh.write("{not json")
    assert sess.load() is None
