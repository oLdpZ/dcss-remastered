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
    g = SaveGuard(saves, ckpt, {"min_snapshot_interval_seconds": 0})
    g.poll_once(); g.poll_once()               # 0000
    _write(p, b"level2xx")                       # contenuto diverso (size diversa)
    g.poll_once(); g.poll_once()               # 0001
    assert _snaps(ckpt, "Hero") == ["0000.cs", "0001.cs"]

def test_rotation_keeps_last_n(tmp_path):
    saves, ckpt = _mk(tmp_path)
    p = os.path.join(saves, "Hero.cs")
    g = SaveGuard(saves, ckpt, {"keep": 3, "min_snapshot_interval_seconds": 0})
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

def test_restore_picks_numerically_latest_past_9999(tmp_path):
    # Regression: lexicographic sort would pick "9999.cs" over the newer
    # "10000.cs". _maybe_restore must select the numerically-highest snapshot.
    saves, ckpt = _mk(tmp_path)
    d = os.path.join(ckpt, "Hero"); os.makedirs(d)
    _write(os.path.join(d, "9999.cs"), b"old")
    _write(os.path.join(d, "10000.cs"), b"newest")
    g = SaveGuard(saves, ckpt, {"require_death_token": False})
    assert g._maybe_restore("Hero") is True
    with open(os.path.join(saves, "Hero.cs"), "rb") as f:
        assert f.read() == b"newest"

def test_resolve_saves_dir_env(monkeypatch, tmp_path):
    from save_guard import resolve_saves_dir
    monkeypatch.setenv("DCSS_SAVES_DIR", str(tmp_path / "s"))
    assert resolve_saves_dir("/whatever/here") == str(tmp_path / "s")

def test_resolve_saves_dir_dev_fallback(monkeypatch):
    from save_guard import resolve_saves_dir
    monkeypatch.delenv("DCSS_SAVES_DIR", raising=False)
    here = os.path.abspath(os.path.join("game", "stone_soup-tiles-0.34", "remaster", "director"))
    got = resolve_saves_dir(here)
    expected = os.path.abspath(os.path.join("game", "stone_soup-tiles-0.34", "saves"))
    assert got == expected

def test_run_forever_returns_immediately_when_disabled(tmp_path):
    saves, ckpt = _mk(tmp_path)
    g = SaveGuard(saves, ckpt, {"enabled": False})
    g.run_forever()   # must return at once; if it looped, the test would hang

def test_load_config_defaults_when_missing(tmp_path):
    from save_guard import load_saveguard_config, DEFAULT_CONFIG
    cfg = load_saveguard_config(str(tmp_path))     # nessun saveguard.json
    assert cfg == DEFAULT_CONFIG

def test_load_config_merges_file(tmp_path):
    from save_guard import load_saveguard_config
    (tmp_path / "saveguard.json").write_text('{"keep": 3, "enabled": false}')
    cfg = load_saveguard_config(str(tmp_path))
    assert cfg["keep"] == 3 and cfg["enabled"] is False
    assert cfg["poll_seconds"] == 1.5             # default preservato

def test_late_arm_still_restores_within_window(tmp_path):
    # Race: the game deletes the .cs BEFORE the death token arms restore.
    # The guard must keep tracking the vanished character and restore on a
    # later poll once armed (not drop it on the first missing observation).
    saves, ckpt = _mk(tmp_path)
    p = os.path.join(saves, "Hero.cs"); _write(p, b"level1")
    g = SaveGuard(saves, ckpt, clock=FakeClock())
    g.poll_once(); g.poll_once()          # snapshot 0000, Hero in _known
    os.remove(p)                           # game deletes save before token
    assert g.poll_once()["restored"] == []  # not armed yet -> no restore
    assert not os.path.exists(p)
    g.arm_restore()                        # death token arrives late
    assert g.poll_once()["restored"] == ["Hero"]  # retried within window
    assert os.path.exists(p)
    with open(p, "rb") as f:
        assert f.read() == b"level1"

def test_redeletion_after_restore_is_restored_again(tmp_path):
    # Race: the game re-deletes the .cs right after our restore while still
    # finalizing death. The guard must restore again (not disarm prematurely).
    saves, ckpt = _mk(tmp_path)
    p = os.path.join(saves, "Hero.cs"); _write(p, b"level1")
    g = SaveGuard(saves, ckpt, clock=FakeClock())
    g.poll_once(); g.poll_once()          # snapshot
    g.arm_restore()
    os.remove(p)
    assert g.poll_once()["restored"] == ["Hero"]   # first restore
    assert os.path.exists(p)
    os.remove(p)                           # game re-deletes before it stabilizes
    assert g.poll_once()["restored"] == ["Hero"]   # restored again
    assert os.path.exists(p)

def test_throttle_limits_snapshot_rate(tmp_path):
    # DCSS riscrive il save spesso: con throttle facciamo al massimo uno snapshot
    # ogni `min_snapshot_interval_seconds` per personaggio.
    saves, ckpt = _mk(tmp_path)
    p = os.path.join(saves, "Hero.cs")
    clock = FakeClock()
    g = SaveGuard(saves, ckpt, {"min_snapshot_interval_seconds": 20}, clock=clock)
    _write(p, b"a"); g.poll_once(); g.poll_once()          # 0000 (primo: consentito)
    assert _snaps(ckpt, "Hero") == ["0000.cs"]
    _write(p, b"bb"); g.poll_once(); g.poll_once()         # entro 20s -> throttled
    assert _snaps(ckpt, "Hero") == ["0000.cs"]
    clock.t += 25                                           # oltre l'intervallo
    _write(p, b"ccc"); g.poll_once(); g.poll_once()        # ora consentito -> 0001
    assert _snaps(ckpt, "Hero") == ["0000.cs", "0001.cs"]

def test_read_failure_does_not_consume_change(tmp_path, monkeypatch):
    # Se la lettura fallisce (es. gioco senza l'hook), il cambiamento NON va perso:
    # _known non avanza e si riprova al poll successivo (quando la lettura riesce).
    import save_guard
    saves, ckpt = _mk(tmp_path)
    p = os.path.join(saves, "Hero.cs"); _write(p, b"data")
    g = SaveGuard(saves, ckpt, {"min_snapshot_interval_seconds": 0})
    calls = {"n": 0}
    real = save_guard.read_file_shared
    def flaky(path):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("locked")
        return real(path)
    monkeypatch.setattr(save_guard, "read_file_shared", flaky)
    g.poll_once(); r = g.poll_once()       # stabile -> _snapshot legge -> 1a volta FAIL
    assert r["snapshotted"] == []
    assert _snaps(ckpt, "Hero") == []      # nessuno snapshot
    r2 = g.poll_once()                      # riprova (known non avanzato) -> 2a volta OK
    assert r2["snapshotted"] == ["Hero"]
    assert _snaps(ckpt, "Hero") == ["0000.cs"]
