"""Scrive uno stato grafico statico nella shared memory e lo tiene vivo,
per testare il proxy senza il Director completo. Ctrl-C per uscire."""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from gfx_state import VisualState, GfxShmem

vs = VisualState()
vs.tint = (0.15, 0.6, 0.2); vs.grade_strength = 0.35; vs.vignette = 0.3  # verde Lair
shm = GfxShmem(); shm.open(); shm.write(vs)
print("shared memory scritta (verde). Ctrl-C per uscire.")
try:
    while True: time.sleep(1); shm.write(vs)
except KeyboardInterrupt:
    shm.close()
