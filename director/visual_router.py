"""Traduce i token di gioco (gli stessi che guidano l'audio) in un VisualState
target. Il branch imposta il grade di base; i modificatori (hp) vi si sommano;
gli eventi incrementano i seq dei pulse."""
from gfx_state import VisualState

_BRANCH_PREFIX = "state__branch_"

class VisualRouter:
    def __init__(self, visualmap):
        self.vmap = visualmap
        self.state = VisualState()
        m = visualmap.get("master", {})
        self.state.master_enable = int(m.get("enable", 1))
        self.state.master_intensity = float(m.get("intensity", 1.0))
        self._branch = None      # grade di base corrente (dict)
        self._hp_mod = None      # modificatore hp corrente (dict)
        self._apply()

    def branch(self, token):
        if not token.startswith(_BRANCH_PREFIX):
            return False
        key = token[len(_BRANCH_PREFIX):]
        g = self.vmap.get("grades", {}).get(key)
        if g is None:
            return False
        self._branch = g
        self._apply()
        return True

    def modifier(self, token):
        mods = self.vmap.get("modifiers", {})
        if token == "state__hp_low":
            self._hp_mod = mods.get("hp_low", {}); self._apply(); return True
        if token == "state__hp_ok":
            self._hp_mod = None; self._apply(); return True
        if token == "state__player_death":
            self._hp_mod = mods.get("player_death", {}); self._apply(); return True
        return False

    def event(self, token):
        e = self.vmap.get("events", {}).get(token)
        if e is None:
            return False
        if "flash" in e:
            self.state.flash_seq += 1
            self.state.flash = tuple(e["flash"])
            self.state.flash_intensity = float(e.get("flash_intensity", 0.0))
        if "shake" in e:
            self.state.shake_seq += 1
            self.state.shake_intensity = float(e["shake"])
        if "bloom" in e:
            self.state.bloom_seq += 1
            self.state.bloom = tuple(e["bloom"])
            self.state.bloom_intensity = float(e.get("bloom_intensity", 0.0))
        return True

    def route(self, token):
        return self.branch(token) or self.modifier(token) or self.event(token)

    def _apply(self):
        """Ricalcola i campi continui: grade di base + modificatore hp."""
        g = self._branch or {}
        self.state.tint = tuple(g.get("tint", (0.0, 0.0, 0.0)))
        self.state.grade_strength = float(g.get("strength", 0.0))
        self.state.vignette = float(g.get("vignette", 0.0))
        self.state.bloom_base = float(g.get("bloom_base", 0.0))
        self.state.desaturate = 0.0
        hp = self._hp_mod or {}
        if "desaturate" in hp:
            self.state.desaturate = float(hp["desaturate"])
        if "vignette_add" in hp:
            self.state.vignette = min(1.0, self.state.vignette + float(hp["vignette_add"]))
