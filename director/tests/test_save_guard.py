import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from save_guard import SaveGuard, DEFAULT_CONFIG

def _write(path, data: bytes):
    with open(path, "wb") as f:
        f.write(data)

def _mk(tmp_path):
    saves = tmp_path / "saves"; saves.mkdir()
    ckpt = tmp_path / "remaster_checkpoints"
    return str(saves), str(ckpt)

def _snaps(ckpt, name):
    d = os.path.join(ckpt, name)
    return sorted(f for f in os.listdir(d)) if os.path.isdir(d) else []

def test_snapshot_created_after_debounce(tmp_path):
    saves, ckpt = _mk(tmp_path)
    _write(os.path.join(saves, "Hero.cs"), b"level1")
    g = SaveGuard(saves, ckpt)
    r1 = g.poll_once()          # 1a scansione: file nuovo -> in attesa (debounce)
    assert r1["snapshotted"] == []
    r2 = g.poll_once()          # 2a scansione: size stabile -> snapshot
    assert r2["snapshotted"] == ["Hero"]
    assert _snaps(ckpt, "Hero") == ["0000.cs"]
    with open(os.path.join(ckpt, "Hero", "0000.cs"), "rb") as f:
        assert f.read() == b"level1"

def test_dedup_same_content(tmp_path):
    saves, ckpt = _mk(tmp_path)
    p = os.path.join(saves, "Hero.cs")
    _write(p, b"level1")
    g = SaveGuard(saves, ckpt)
    g.poll_once(); g.poll_once()               # snapshot 0000
    os.utime(p, None)                            # tocca mtime, stesso contenuto
    g.poll_once()                                # rileva cambio -> attesa
    r = g.poll_once()                            # stabile -> ma hash uguale -> dedup
    assert r["snapshotted"] == []
    assert _snaps(ckpt, "Hero") == ["0000.cs"]

def test_new_content_makes_new_snapshot(tmp_path):
    saves, ckpt = _mk(tmp_path)
    p = os.path.join(saves, "Hero.cs")
    _write(p, b"level1")
    g = SaveGuard(saves, ckpt)
    g.poll_once(); g.poll_once()               # 0000
    _write(p, b"level2xx")                       # contenuto diverso (size diversa)
    g.poll_once(); g.poll_once()               # 0001
    assert _snaps(ckpt, "Hero") == ["0000.cs", "0001.cs"]
