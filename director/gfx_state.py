"""Lato Python del contratto IPC grafico: impacchetta lo stato visivo e lo
scrive nella memoria condivisa 'dcss_gfx_state' letta dal proxy opengl32."""
import mmap, struct

# Ordine campi (little-endian). DEVE combaciare con GfxState in shared_state.h.
#  version(I) master_enable(I) master_intensity(f)
#  tint_r/g/b(f) grade_strength(f) desaturate(f) vignette(f) bloom_base(f)
#  flash_seq(I) flash_r/g/b(f) flash_intensity(f)
#  shake_seq(I) shake_intensity(f)
#  bloom_seq(I) bloom_r/g/b(f) bloom_intensity(f)
PACK_FORMAT = "<IIf" "ffff" "fff" "I" "ffff" "If" "I" "ffff"
STRUCT_SIZE = struct.calcsize(PACK_FORMAT)   # == 88
SHMEM_NAME = "dcss_gfx_state"

class VisualState:
    def __init__(self):
        self.version = 1
        self.master_enable = 1
        self.master_intensity = 1.0
        self.tint = (0.0, 0.0, 0.0)
        self.grade_strength = 0.0
        self.desaturate = 0.0
        self.vignette = 0.0
        self.bloom_base = 0.0
        self.flash_seq = 0
        self.flash = (0.0, 0.0, 0.0)
        self.flash_intensity = 0.0
        self.shake_seq = 0
        self.shake_intensity = 0.0
        self.bloom_seq = 0
        self.bloom = (0.0, 0.0, 0.0)
        self.bloom_intensity = 0.0

def pack(vs):
    return struct.pack(
        PACK_FORMAT,
        vs.version, vs.master_enable, vs.master_intensity,
        vs.tint[0], vs.tint[1], vs.tint[2], vs.grade_strength,
        vs.desaturate, vs.vignette, vs.bloom_base,
        vs.flash_seq, vs.flash[0], vs.flash[1], vs.flash[2], vs.flash_intensity,
        vs.shake_seq, vs.shake_intensity,
        vs.bloom_seq, vs.bloom[0], vs.bloom[1], vs.bloom[2], vs.bloom_intensity,
    )

class GfxShmem:
    def __init__(self):
        self._mm = None
    def open(self):
        # -1 fd => mapping su pagefile, con nome: il proxy fa OpenFileMapping(SHMEM_NAME).
        self._mm = mmap.mmap(-1, STRUCT_SIZE, tagname=SHMEM_NAME)
    def write(self, vs):
        if self._mm is None:
            return
        self._mm.seek(0)
        self._mm.write(pack(vs))
    def close(self):
        if self._mm is not None:
            self._mm.close(); self._mm = None
