"""Sintetizza effetti sonori 'veri' per gli eventi di gioco (CC0, auto-prodotti).
Sostituisce i beep segnaposto in remaster/audio/sfx/. Mono 44100 16-bit WAV."""
import wave, struct, math, random, os

FR = 44100
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.abspath(os.path.join(HERE, "..", "audio", "sfx"))
os.makedirs(OUT, exist_ok=True)
random.seed(1234)  # deterministico

def env_exp(n, tau, attack=0.003):
    a = max(1, int(attack * FR))
    out = []
    for i in range(n):
        e = math.exp(-i / (tau * FR))
        if i < a:
            e *= i / a
        out.append(e)
    return out

def mix(buffers):
    n = max(len(b) for b in buffers)
    out = [0.0] * n
    for b in buffers:
        for i, v in enumerate(b):
            out[i] += v
    return out

def tone(freq, dur, tau, vol=0.5, partials=(1.0,), vibrato=0.0):
    n = int(dur * FR); e = env_exp(n, tau)
    out = []
    for i in range(n):
        t = i / FR
        f = freq * (1 + vibrato * math.sin(2 * math.pi * 5 * t))
        s = sum(amp * math.sin(2 * math.pi * f * k * t) for k, amp in enumerate(partials, 1))
        out.append(vol * e[i] * s / sum(partials))
    return out

def sweep(f0, f1, dur, tau, vol=0.5):
    n = int(dur * FR); e = env_exp(n, tau); out = []; ph = 0.0
    for i in range(n):
        t = i / FR
        f = f0 + (f1 - f0) * (i / n)
        ph += 2 * math.pi * f / FR
        out.append(vol * e[i] * math.sin(ph))
    return out

def noise(dur, tau, vol=0.5, lp=0.5):
    n = int(dur * FR); e = env_exp(n, tau); out = []; y = 0.0
    for i in range(n):
        x = random.uniform(-1, 1)
        y = y + lp * (x - y)  # one-pole lowpass
        out.append(vol * e[i] * y)
    return out

def pad(buf, dur):
    n = int(dur * FR)
    return buf + [0.0] * max(0, n - len(buf))

def save(name, buf):
    w = wave.open(os.path.join(OUT, name), "w")
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(FR)
    for v in buf:
        v = max(-1.0, min(1.0, v))
        w.writeframes(struct.pack("<h", int(v * 32000)))
    w.close()

# --- eventi ---
def melee(seed):
    random.seed(seed)
    thump = tone(90, 0.12, 0.035, vol=0.8)
    crack = noise(0.09, 0.025, vol=0.6, lp=0.6)
    return mix([pad(thump, 0.14), pad(crack, 0.14)])

save("evt__melee_hit.wav",  melee(1))
save("evt__melee_hit2.wav", melee(2))
save("evt__melee_hit3.wav", melee(3))

save("evt__ranged.wav", mix([pad(noise(0.22, 0.09, vol=0.5, lp=0.25), 0.24),
                             pad(sweep(1200, 300, 0.22, 0.08, vol=0.25), 0.24)]))

save("evt__cast_spell.wav", mix([pad(sweep(320, 900, 0.42, 0.28, vol=0.35), 0.5),
                                 pad(tone(660, 0.5, 0.3, vol=0.2, partials=(1,0.5,0.3), vibrato=0.01), 0.5),
                                 pad(sweep(325, 910, 0.42, 0.28, vol=0.2), 0.5)]))  # detune shimmer

save("evt__quaff.wav", mix([pad(sweep(700, 300, 0.10, 0.05, vol=0.4), 0.34),
                            pad([0]*int(0.12*FR) + sweep(600, 260, 0.10, 0.05, vol=0.35), 0.34),
                            pad(noise(0.30, 0.12, vol=0.12, lp=0.3), 0.34)]))

save("evt__read.wav", mix([pad(noise(0.06, 0.02, vol=0.4, lp=0.4), 0.28),
                           pad([0]*int(0.10*FR) + noise(0.06, 0.02, vol=0.35, lp=0.4), 0.28),
                           pad([0]*int(0.19*FR) + noise(0.05, 0.02, vol=0.3, lp=0.4), 0.28)]))

save("evt__pickup.wav", mix([pad(tone(1046, 0.12, 0.09, vol=0.4, partials=(1,0.4)), 0.30),
                             pad([0]*int(0.09*FR) + tone(1568, 0.16, 0.11, vol=0.4, partials=(1,0.4)), 0.30)]))

save("evt__spot.wav", mix([pad(tone(494, 0.10, 0.06, vol=0.4), 0.26),
                           pad([0]*int(0.08*FR) + tone(466, 0.14, 0.08, vol=0.45), 0.26)]))  # dissonante

save("evt__kill.wav", mix([pad(sweep(240, 60, 0.28, 0.14, vol=0.6), 0.34),
                           pad(noise(0.14, 0.05, vol=0.4, lp=0.5), 0.34)]))

# level up: arpeggio maggiore ascendente + sparkle
lu = []
for k, f in enumerate([523, 659, 784, 1046]):
    lu.append(pad([0]*int(0.12*k*FR) + tone(f, 0.5, 0.28, vol=0.4, partials=(1,0.5,0.25)), 1.0))
lu.append(pad([0]*int(0.55*FR) + tone(2093, 0.4, 0.3, vol=0.25, partials=(1,0.6)), 1.0))
save("evt__level_up.wav", mix(lu))

# hp basso: lub-dub
save("evt__hp_low.wav", mix([pad(tone(70, 0.14, 0.05, vol=0.7), 0.5),
                             pad([0]*int(0.18*FR) + tone(64, 0.16, 0.06, vol=0.55), 0.5)]))

def door_creak(dur, tremolo_hz, vol):
    n = int(dur * FR); out = []; y = 0.0
    for i in range(n):
        t = i / FR
        x = random.uniform(-1, 1)
        y = y + 0.05 * (x - y)              # lowpass pesante -> rumore basso (legno)
        trem = 0.55 + 0.45 * math.sin(2 * math.pi * tremolo_hz * t)  # stutter del cigolio
        env = math.sin(math.pi * i / n)     # dentro/fuori morbido
        out.append(vol * env * trem * y * 5.0)
    return out

def wood_knock(freq, vol):
    return tone(freq, 0.10, 0.03, vol=vol, partials=(1, 0.5, 0.25))

# porta che si apre: cigolio + leggero tonfo del chiavistello
random.seed(50)
save("evt__door.wav", mix([pad(door_creak(0.38, 17, vol=0.5), 0.52),
                           pad([0]*int(0.40*FR) + wood_knock(120, 0.35), 0.52)]))
# porta che si chiude: cigolio piu' corto + tonfo piu' deciso
random.seed(51)
save("evt__door_close.wav", mix([pad(door_creak(0.28, 20, vol=0.45), 0.5),
                                 pad([0]*int(0.30*FR) + wood_knock(95, 0.6), 0.5),
                                 pad([0]*int(0.30*FR) + noise(0.06, 0.02, vol=0.25, lp=0.5), 0.5)]))

def footstep(freq, vol):
    return mix([tone(freq, 0.09, 0.03, vol=vol * 0.5, partials=(1, 0.4)),
                noise(0.06, 0.02, vol=vol * 0.45, lp=0.45)])

def stairs(direction):  # +1 = su (pitch crescente), -1 = giu' (pitch calante)
    parts = []
    base = 120
    for k in range(3):
        f = base + direction * k * 22
        parts.append(pad([0] * int(0.11 * k * FR) + footstep(f, 0.6), 0.6))
    w0, w1 = (300, 520) if direction > 0 else (520, 260)
    parts.append(pad(sweep(w0, w1, 0.35, 0.18, vol=0.22), 0.6))  # whoosh direzionale
    return mix(parts)

random.seed(60)
save("evt__stairs_down.wav", stairs(-1))
random.seed(61)
save("evt__stairs_up.wav", stairs(1))

print("SFX sintetizzati in", OUT)
