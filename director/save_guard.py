import os, shutil, hashlib, json, time

DEFAULT_CONFIG = {
    "enabled": True,
    "keep": 5,
    "poll_seconds": 1.5,
    "require_death_token": True,
    "restore_window_seconds": 30,
}

class SaveGuard:
    def __init__(self, saves_dir, checkpoints_dir, config=None, clock=time.monotonic):
        self.saves_dir = saves_dir
        self.checkpoints_dir = checkpoints_dir
        self.cfg = dict(DEFAULT_CONFIG); self.cfg.update(config or {})
        self._clock = clock
        self._known = {}      # name -> (mtime, size) stato stabile gia' snapshottato
        self._pending = {}    # name -> (mtime, size) visto ma non ancora stabile
        self._last_hash = {}  # name -> hash dell'ultimo snapshot
        self._armed_at = None

    # --- API pubblica ---
    def arm_restore(self):
        self._armed_at = self._clock()

    def poll_once(self):
        report = {"snapshotted": [], "restored": []}
        current = self._scan()
        for name, meta in current.items():
            if self._known.get(name) == meta:
                continue
            if self._pending.get(name) == meta:      # stabile per un ciclo
                if self._snapshot(name):
                    report["snapshotted"].append(name)
                self._known[name] = meta
                self._pending.pop(name, None)
            else:
                self._pending[name] = meta           # attendi stabilita'
        return report

    # --- interni ---
    def _scan(self):
        out = {}
        try:
            names = os.listdir(self.saves_dir)
        except FileNotFoundError:
            return out
        for fn in names:
            if fn.endswith(".cs"):
                p = os.path.join(self.saves_dir, fn)
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                out[fn[:-3]] = (st.st_mtime, st.st_size)
        return out

    def _snapshot(self, name):
        src = os.path.join(self.saves_dir, name + ".cs")
        try:
            with open(src, "rb") as f:
                data = f.read()
        except OSError:
            return False
        h = hashlib.sha1(data).hexdigest()
        if self._last_hash.get(name) == h:
            return False
        d = os.path.join(self.checkpoints_dir, name)
        os.makedirs(d, exist_ok=True)
        idx = self._next_index(d)
        shutil.copy2(src, os.path.join(d, "%04d.cs" % idx))
        self._last_hash[name] = h
        return True

    def _next_index(self, d):
        mx = -1
        for fn in os.listdir(d):
            if fn.endswith(".cs") and fn[:-3].isdigit():
                mx = max(mx, int(fn[:-3]))
        return mx + 1
