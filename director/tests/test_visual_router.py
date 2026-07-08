import os, sys, json
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), ""))
from visual_router import VisualRouter

VMAP = {
  "master": {"enable": 1, "intensity": 1.0},
  "grades": {"Lair": {"tint": [0.15,0.45,0.18], "strength": 0.22, "vignette": 0.25, "bloom_base": 0.0}},
  "modifiers": {"hp_low": {"desaturate": 0.4, "vignette_add": 0.3, "vignette_tint": [0.6,0,0]},
                "hp_ok": {}, "player_death": {"desaturate": 1.0, "fade_black": 1.0}},
  "events": {"evt__level_up": {"flash": [1.0,0.9,0.4], "flash_intensity": 0.35,
                               "bloom": [1.0,0.85,0.3], "bloom_intensity": 0.7}},
}

def test_branch_sets_grade():
    r = VisualRouter(VMAP)
    assert r.route("state__branch_Lair") is True
    assert tuple(round(x,3) for x in r.state.tint) == (0.15,0.45,0.18)
    assert r.state.grade_strength == 0.22

def test_hp_low_adds_desaturate_over_current_branch():
    r = VisualRouter(VMAP)
    r.route("state__branch_Lair")
    r.route("state__hp_low")
    assert r.state.desaturate == 0.4
    assert tuple(round(x,3) for x in r.state.tint) == (0.15,0.45,0.18)  # branch mantenuto

def test_hp_ok_clears_desaturate():
    r = VisualRouter(VMAP)
    r.route("state__branch_Lair"); r.route("state__hp_low"); r.route("state__hp_ok")
    assert r.state.desaturate == 0.0

def test_event_bumps_pulse_seq_each_time():
    r = VisualRouter(VMAP)
    s0 = r.state.flash_seq
    r.route("evt__level_up")
    assert r.state.flash_seq == s0 + 1
    assert r.state.bloom_seq == 1
    r.route("evt__level_up")
    assert r.state.flash_seq == s0 + 2

def test_unknown_token_returns_false():
    assert VisualRouter(VMAP).route("evt__nope") is False
