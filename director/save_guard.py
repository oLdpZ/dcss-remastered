import os, sys, shutil, hashlib, json, time


def read_file_shared(path):
    """Legge un file aprendolo con condivisione piena (READ|WRITE|DELETE), cosi' si
    puo' leggere un save che DCSS tiene aperto con un handle di scrittura. La open()
    normale di Python non condivide la scrittura -> fallirebbe con 'Permission denied'.
    Su piattaforme non-Windows (o test) ripiega su open()."""
    if sys.platform != "win32":
        with open(path, "rb") as f:
            return f.read()
    import ctypes
    from ctypes import wintypes
    k = ctypes.windll.kernel32
    k.CreateFileW.restype = wintypes.HANDLE
    k.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                              ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                              wintypes.HANDLE]
    k.ReadFile.restype = wintypes.BOOL
    k.ReadFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                           ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    GENERIC_READ = 0x80000000
    SHARE = 0x1 | 0x2 | 0x4          # FILE_SHARE_READ | WRITE | DELETE
    OPEN_EXISTING = 3
    INVALID = ctypes.c_void_p(-1).value
    h = k.CreateFileW(path, GENERIC_READ, SHARE, None, OPEN_EXISTING, 0x80, None)
    if not h or h == INVALID:
        raise OSError("CreateFileW failed (err %d): %s" % (ctypes.GetLastError(), path))
    try:
        out = []
        buf = ctypes.create_string_buffer(1 << 16)
        rd = wintypes.DWORD(0)
        while True:
            if not k.ReadFile(h, buf, 1 << 16, ctypes.byref(rd), None):
                raise OSError("ReadFile failed (err %d): %s" % (ctypes.GetLastError(), path))
            if rd.value == 0:
                break
            out.append(buf.raw[:rd.value])
        return b"".join(out)
    finally:
        k.CloseHandle(h)


DEFAULT_CONFIG = {
    "enabled": True,
    "keep": 10,
    "poll_seconds": 1.5,
    "min_snapshot_interval_seconds": 20,
    "require_death_token": True,
    "restore_window_seconds": 30,
    "debug": False,
}

class SaveGuard:
    def __init__(self, saves_dir, checkpoints_dir, config=None, clock=time.monotonic, log=None):
        self.saves_dir = saves_dir
        self.checkpoints_dir = checkpoints_dir
        self.cfg = dict(DEFAULT_CONFIG); self.cfg.update(config or {})
        self._clock = clock
        self._log = log or (lambda msg: None)
        self._known = {}      # name -> (mtime, size) stato stabile gia' snapshottato
        self._pending = {}    # name -> (mtime, size) visto ma non ancora stabile
        self._last_hash = {}  # name -> hash dell'ultimo snapshot
        self._last_snap_at = {}  # name -> clock time dell'ultimo snapshot (throttle)
        self._vanished = {}   # name -> clock time in cui il .cs e' sparito (morte)
        self._armed_at = None
        self._debug = bool(self.cfg.get("debug", False))

    def _dbg(self, msg):
        if self._debug:
            self._log(msg)

    # --- API pubblica ---
    def arm_restore(self):
        self._armed_at = self._clock()

    def poll_once(self):
        report = {"snapshotted": [], "restored": []}
        current = self._scan()

        # 1. Sparizioni: un file noto non c'e' piu' -> candidato al ripristino (morte).
        for name in list(self._known):
            if name not in current:
                self._vanished[name] = self._clock()
                del self._known[name]
                self._pending.pop(name, None)

        # 2. Serve i personaggi spariti: riprova il ripristino a ogni poll finche' il
        #    flag e' valido, e tiene d'occhio una eventuale ri-cancellazione dal gioco.
        window = float(self.cfg.get("restore_window_seconds", 30))
        for name in list(self._vanished):
            if name in current:
                # Il file e' tornato (il nostro restore ha tenuto, o e' una nuova
                # partita con lo stesso nome): stabile -> smetti di seguirlo e disarma.
                del self._vanished[name]
                self._armed_at = None
                continue
            if self._maybe_restore(name):
                report["restored"].append(name)
                self._log("[saveguard] ripristinato checkpoint per " + name)
                # resta in _vanished: al prossimo poll confermiamo che non sia
                # stato ri-cancellato dal gioco mentre finalizzava la morte.
            elif (self._clock() - self._vanished[name]) > window:
                # Finestra scaduta senza ripristino riuscito -> smetti di seguirlo.
                del self._vanished[name]

        # 3. Snapshot dei file nuovi/cambiati (debounce + dedup + throttle).
        interval = float(self.cfg.get("min_snapshot_interval_seconds", 20))
        for name, meta in current.items():
            if self._known.get(name) == meta:
                continue
            self._dbg("[saveguard][diag] cambio visto %s known=%r pending=%r new=%r"
                      % (name, self._known.get(name), self._pending.get(name), meta))
            if self._pending.get(name) != meta:      # non ancora stabile: attendi
                self._pending[name] = meta
                continue
            # Stabile per un ciclo. Throttle: al massimo uno snapshot ogni `interval`s
            # per personaggio (DCSS riscrive il save spesso; teniamo storia diradata).
            last = self._last_snap_at.get(name)
            if last is not None and (self._clock() - last) < interval:
                self._known[name] = meta          # consuma il cambiamento senza snapshot
                self._pending.pop(name, None)
                continue
            try:
                snapped = self._snapshot(name)
            except OSError as e:
                # Lettura fallita (es. gioco avviato senza l'hook che sblocca il lock):
                # NON avanzare _known -> riprova al prossimo poll.
                self._dbg("[saveguard][diag] read FAIL %s: %r" % (name, e))
                continue
            if snapped:
                self._last_snap_at[name] = self._clock()
                report["snapshotted"].append(name)
                self._log("[saveguard] checkpoint " + name)
            self._known[name] = meta
            self._pending.pop(name, None)
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
        data = read_file_shared(src)   # rilancia OSError: gestito dal chiamante
        h = hashlib.sha1(data).hexdigest()
        if self._last_hash.get(name) == h:
            return False
        d = os.path.join(self.checkpoints_dir, name)
        os.makedirs(d, exist_ok=True)
        idx = self._next_index(d)
        with open(os.path.join(d, "%04d.cs" % idx), "wb") as f:
            f.write(data)
        self._last_hash[name] = h
        self._rotate(d)
        return True

    def _next_index(self, d):
        mx = -1
        for fn in os.listdir(d):
            if fn.endswith(".cs") and fn[:-3].isdigit():
                mx = max(mx, int(fn[:-3]))
        return mx + 1

    def _rotate(self, d):
        snaps = sorted((fn for fn in os.listdir(d)
                        if fn.endswith(".cs") and fn[:-3].isdigit()),
                       key=lambda fn: int(fn[:-3]))
        # keep <= 0 disabilita la rotazione (ritenzione illimitata).
        keep = int(self.cfg.get("keep", 5))
        for fn in snaps[:-keep] if keep > 0 else []:
            try:
                os.remove(os.path.join(d, fn))
            except OSError:
                pass

    def _restore_allowed(self):
        if not self.cfg.get("require_death_token", True):
            return True
        if self._armed_at is None:
            return False
        return (self._clock() - self._armed_at) <= float(
            self.cfg.get("restore_window_seconds", 30))

    def _maybe_restore(self, name):
        if not self._restore_allowed():
            return False
        d = os.path.join(self.checkpoints_dir, name)
        if not os.path.isdir(d):
            return False
        snaps = sorted((fn for fn in os.listdir(d)
                        if fn.endswith(".cs") and fn[:-3].isdigit()),
                       key=lambda fn: int(fn[:-3]))
        if not snaps:
            return False
        latest = os.path.join(d, snaps[-1])
        dst = os.path.join(self.saves_dir, name + ".cs")
        try:
            shutil.copy2(latest, dst)
        except OSError:
            return False
        return True

    def run_forever(self):
        if not self.cfg.get("enabled", True):
            return
        while True:
            try:
                self.poll_once()
            except Exception as e:
                self._log("[saveguard] errore poll: " + repr(e))
            time.sleep(float(self.cfg.get("poll_seconds", 1.5)))


def resolve_saves_dir(here):
    env = os.environ.get("DCSS_SAVES_DIR")
    if env:
        return os.path.abspath(env)
    return os.path.abspath(os.path.join(here, "..", "..", "saves"))


def load_saveguard_config(here):
    cfg = dict(DEFAULT_CONFIG)
    try:
        with open(os.path.join(here, "saveguard.json"), encoding="utf-8") as f:
            cfg.update(json.load(f))
    except FileNotFoundError:
        pass
    return cfg
