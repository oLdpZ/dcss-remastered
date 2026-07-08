import os, sys, struct
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), ""))
from gfx_state import VisualState, pack, STRUCT_SIZE, PACK_FORMAT

def test_struct_is_88_bytes():
    assert STRUCT_SIZE == 88
    assert struct.calcsize(PACK_FORMAT) == 88

def test_pack_roundtrip_fields_in_order():
    vs = VisualState()
    vs.tint = (0.1, 0.2, 0.3); vs.grade_strength = 0.5
    vs.desaturate = 0.4; vs.vignette = 0.6; vs.bloom_base = 0.05
    vs.flash_seq = 7; vs.flash = (1.0, 0.9, 0.0); vs.flash_intensity = 0.8
    vs.shake_seq = 3; vs.shake_intensity = 0.25
    vs.bloom_seq = 2; vs.bloom = (0.2, 0.6, 1.0); vs.bloom_intensity = 0.7
    raw = pack(vs)
    vals = struct.unpack(PACK_FORMAT, raw)
    assert vals[0] == 1                 # version
    assert vals[1] == 1                 # master_enable
    assert abs(vals[2] - 1.0) < 1e-6    # master_intensity
    assert tuple(round(v, 3) for v in vals[3:6]) == (0.1, 0.2, 0.3)   # tint
    assert vals[10] == 7                # flash_seq
    assert vals[15] == 3                # shake_seq
    assert vals[17] == 2                # bloom_seq

def test_defaults_are_neutral():
    v = struct.unpack(PACK_FORMAT, pack(VisualState()))
    assert v[3:6] == (0.0, 0.0, 0.0)    # no tint
    assert v[6] == 0.0                  # grade_strength
    assert v[7] == 0.0                  # desaturate
