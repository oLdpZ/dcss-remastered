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

class FakeClock:
    def __init__(self): self.t = 1000.0
    def __call__(self): return self.t

def _snapshot_hero(saves, ckpt, data=b"level1", keep=5):
    p = os.path.join(saves, "Hero.cs")
    _write(p, data)
    g = SaveGuard(saves, ckpt, {"keep": keep}, clock=FakeClock())
    g.poll_once(); g.poll_once()      # crea 0000
    return g, p

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

def test_rotation_keeps_last_n(tmp_path):
    saves, ckpt = _mk(tmp_path)
    p = os.path.join(saves, "Hero.cs")
    g = SaveGuard(saves, ckpt, {"keep": 3})
    for i in range(6):
        _write(p, b"content-%d" % i)   # contenuto sempre diverso
        g.poll_once(); g.poll_once()   # forza snapshot
    snaps = _snaps(ckpt, "Hero")
    assert len(snaps) == 3
    assert snaps == ["0003.cs", "0004.cs", "0005.cs"]

def test_rotation_orders_numerically_past_9999(tmp_path):
    # Regression: lexicographic sort would treat "10000.cs" as older than
    # "9999.cs" and delete the newest snapshot. _rotate must sort numerically.
    saves, ckpt = _mk(tmp_path)
    d = os.path.join(ckpt, "Hero"); os.makedirs(d)
    for name in ("9998.cs", "9999.cs", "10000.cs"):
        _write(os.path.join(d, name), b"x")
    g = SaveGuard(saves, ckpt, {"keep": 1})
    g._rotate(d)
    assert _snaps(ckpt, "Hero") == ["10000.cs"]   # newest survives

def test_restore_when_armed(tmp_path):
    saves, ckpt = _mk(tmp_path)
    g, p = _snapshot_hero(saves, ckpt)
    g.arm_restore()
    os.remove(p)                       # morte: DCSS cancella il .cs
    r = g.poll_once()
    assert r["restored"] == ["Hero"]
    assert os.path.exists(p)
    with open(p, "rb") as f:
        assert f.read() == b"level1"

def test_no_restore_when_not_armed(tmp_path):
    saves, ckpt = _mk(tmp_path)
    g, p = _snapshot_hero(saves, ckpt)   # require_death_token=True di default
    os.remove(p)
    r = g.poll_once()
    assert r["restored"] == []
    assert not os.path.exists(p)

def test_no_restore_after_window_expired(tmp_path):
    saves, ckpt = _mk(tmp_path)
    clock = FakeClock()
    p = os.path.join(saves, "Hero.cs"); _write(p, b"level1")
    g = SaveGuard(saves, ckpt, {"restore_window_seconds": 30}, clock=clock)
    g.poll_once(); g.poll_once()
    g.arm_restore()                       # armato a t=1000
    clock.t += 31                         # oltre la finestra
    os.remove(p)
    assert g.poll_once()["restored"] == []
    assert not os.path.exists(p)

def test_fallback_restore_without_token(tmp_path):
    saves, ckpt = _mk(tmp_path)
    p = os.path.join(saves, "Hero.cs"); _write(p, b"level1")
    g = SaveGuard(saves, ckpt, {"require_death_token": False}, clock=FakeClock())
    g.poll_once(); g.poll_once()
    os.remove(p)                          # nessun arm, ma fallback attivo
    assert g.poll_once()["restored"] == ["Hero"]
    assert os.path.exists(p)
