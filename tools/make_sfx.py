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

# bere pozione (quaff): suono udibile = asset reale registrato (CC0, Freesound) ->
# audio/sfx/evt__quaff.ogg, mappato in soundmap.json (vedi CREDITS.txt).
# Qui solo lo STUB SILENZIOSO evt__quaff.wav: la regola "sound += You drink:evt__quaff.wav"
# lo usa come trigger, il proxy lo intercetta e il Director riproduce l'OGG.
save("evt__quaff.wav", [0.0] * int(0.02 * FR))

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

# =========================================================================
#  Combattimento difensivo (quello che SUBISCI) + morte + momenti epici
# =========================================================================

# --- vieni colpito: tonfo sul corpo + schiaffo + breve grugnito (pitch variato) ---
def hurt(seed):
    random.seed(seed)
    thump = tone(75, 0.10, 0.03, vol=0.7)
    slap  = noise(0.07, 0.02, vol=0.4, lp=0.5)
    grunt = tone(150 + seed * 8, 0.16, 0.06, vol=0.35,
                 partials=(1, 0.6, 0.4, 0.2), vibrato=0.02)
    return mix([pad(thump, 0.24), pad(slap, 0.24),
                pad([0] * int(0.02 * FR) + grunt, 0.24)])

save("evt__hurt.wav",  hurt(11))
save("evt__hurt2.wav", hurt(12))
save("evt__hurt3.wav", hurt(13))

# --- morso: due crunch ravvicinati + snap ---
random.seed(70)
save("evt__hurt_bite.wav", mix([
    pad(noise(0.05, 0.012, vol=0.6, lp=0.7), 0.16),
    pad([0] * int(0.06 * FR) + noise(0.05, 0.012, vol=0.55, lp=0.7), 0.16),
    pad(tone(320, 0.04, 0.015, vol=0.3, partials=(1, 0.7, 0.5)), 0.16)]))

# --- artigliata: strappo brillante + whoosh discendente ---
random.seed(71)
save("evt__hurt_claw.wav", mix([
    pad(noise(0.18, 0.06, vol=0.45, lp=0.85), 0.2),
    pad(sweep(900, 250, 0.16, 0.07, vol=0.22), 0.2)]))

# --- parata con scudo: clangore metallico inarmonico + tick ---
def metal(f, vol, tau):
    return mix([tone(f, 0.4, tau, vol=vol),
                tone(f * 2.76, 0.4, tau * 0.8, vol=vol * 0.5),
                tone(f * 5.4, 0.35, tau * 0.6, vol=vol * 0.3)])

random.seed(72)
save("evt__block.wav", mix([pad(metal(520, 0.4, 0.18), 0.5),
                            pad(noise(0.03, 0.008, vol=0.3, lp=0.8), 0.5)]))

# --- il nemico ti manca: sibilo d'aria (whiff) ---
random.seed(73)
save("evt__miss_enemy.wav", mix([pad(noise(0.14, 0.05, vol=0.35, lp=0.2), 0.18),
                                 pad(sweep(1400, 500, 0.12, 0.05, vol=0.12), 0.18)]))

# --- morte: accordo minore basso + discesa cupa + boom sub (sting ~1.8s) ---
death = []
for f in (131, 156, 196):          # Do minore (C3 Eb3 G3)
    death.append(pad(tone(f, 1.6, 0.9, vol=0.28, partials=(1, 0.5, 0.3)), 1.8))
death.append(pad(sweep(300, 60, 1.4, 0.7, vol=0.25), 1.8))
death.append(pad(tone(55, 1.6, 1.0, vol=0.4), 1.8))
save("state__player_death.wav", mix(death))

# --- Orb of Zot: fanfara trionfale (arpeggio maggiore ottoni + accordo finale + sparkle) ---
BRASS = (1, 0.7, 0.5, 0.35, 0.2)
orb = []
for k, f in enumerate([392, 523, 659, 784]):   # G4 C5 E5 G5 ascendente
    orb.append(pad([0] * int(0.14 * k * FR) + tone(f, 0.6, 0.4, vol=0.34, partials=BRASS), 2.0))
for f in (523, 659, 784, 1046):                 # accordo maggiore ampio
    orb.append(pad([0] * int(0.56 * FR) + tone(f, 1.2, 0.7, vol=0.22, partials=BRASS), 2.0))
orb.append(pad([0] * int(0.6 * FR) + tone(2093, 0.5, 0.35, vol=0.16, partials=(1, 0.6)), 2.0))
save("evt__orb.wav", mix(orb))

# --- rune: chime trionfale corto (triade maggiore brillante + sparkle) ---
rune = []
for k, f in enumerate([659, 831, 988]):         # Mi maggiore (E5 G#5 B5)
    rune.append(pad([0] * int(0.07 * k * FR) + tone(f, 0.5, 0.32, vol=0.3, partials=(1, 0.5, 0.3)), 1.0))
rune.append(pad([0] * int(0.18 * FR) + tone(1318, 0.4, 0.3, vol=0.16, partials=(1, 0.6)), 1.0))
save("evt__rune.wav", mix(rune))

# --- passo di camminata: cortissimo, morbido, 2 varianti (piede dx/sx) ---
random.seed(80)
save("evt__step.wav",  pad(footstep(95, 0.30), 0.12))
random.seed(81)
save("evt__step2.wav", pad(footstep(88, 0.28), 0.12))

# =========================================================================
#  Suoni di pickup per classe oggetto (CC0)
# =========================================================================

# pergamena: fruscio cartaceo breve + micro-tick
random.seed(90)
save("evt__pickup_scroll.wav", mix([
    pad(noise(0.10, 0.04, vol=0.32, lp=0.35), 0.16),
    pad([0]*int(0.05*FR) + noise(0.05, 0.02, vol=0.22, lp=0.4), 0.16)]))

# pozione: il suono udibile e' un asset reale registrato (CC0, Freesound) ->
# audio/sfx/evt__pickup_potion.ogg, mappato in soundmap.json (vedi CREDITS.txt).
# Qui generiamo solo uno STUB SILENZIOSO evt__pickup_potion.wav: il .rc chiama
# crawl.playsound(".../evt__pickup_potion.wav") come TRIGGER dell'evento; il proxy
# lo intercetta e il Director riproduce l'OGG. Lo stub silenzioso garantisce che il
# file-trigger esista (come per ogni altro token) senza aggiungere audio.
save("evt__pickup_potion.wav", [0.0] * int(0.02 * FR))

# anello: ting metallico piccolo e brillante
random.seed(92)
save("evt__pickup_ring.wav", pad(metal(1320, 0.30, 0.12), 0.34))

# amuleto: chime caldo (piu' grave, code lunghe)
random.seed(93)
save("evt__pickup_amulet.wav", mix([
    pad(tone(880, 0.5, 0.35, vol=0.3, partials=(1, 0.5, 0.25)), 0.5),
    pad([0]*int(0.06*FR) + tone(1174, 0.45, 0.3, vol=0.2, partials=(1, 0.5)), 0.5)]))

# arma: "shing" di lama -> zing ascendente + ring metallico GRAVE e sostenuto.
# Deliberatamente piu' basso e con coda lunga per non confondersi col jingle acuto dell'oro.
random.seed(94)
save("evt__pickup_weapon.wav", mix([
    pad(sweep(400, 1700, 0.12, 0.05, vol=0.28), 0.44),          # zing della lama (tetto piu' basso)
    pad([0]*int(0.05*FR) + metal(440, 0.34, 0.24), 0.44),       # ring grave con coda lunga
    pad(noise(0.04, 0.012, vol=0.16, lp=0.7), 0.44)]))          # attrito iniziale

# armatura: clangore pesante + componente cuoio + tonfo
random.seed(95)
save("evt__pickup_armour.wav", mix([
    pad(metal(300, 0.4, 0.18), 0.34),
    pad(noise(0.12, 0.05, vol=0.28, lp=0.3), 0.34),
    pad([0]*int(0.02*FR) + tone(140, 0.10, 0.04, vol=0.3), 0.34)]))

# dardi/proiettili: rattle di faretra (noise ritmico)
random.seed(96)
quiver = []
for k in range(3):
    quiver.append(pad([0]*int(0.05*k*FR) + noise(0.05, 0.02, vol=0.3, lp=0.6), 0.22))
save("evt__pickup_missile.wav", mix(quiver))

# bacchetta: blip shimmer magico (sweep ascendente + detune)
random.seed(97)
save("evt__pickup_wand.wav", mix([
    pad(sweep(500, 1500, 0.16, 0.09, vol=0.28), 0.24),
    pad(sweep(505, 1520, 0.16, 0.09, vol=0.18), 0.24)]))

# libro: tonfo sordo di copertina + sfoglio di pagine
random.seed(98)
save("evt__pickup_book.wav", mix([
    pad(tone(120, 0.12, 0.05, vol=0.4), 0.28),
    pad([0]*int(0.10*FR) + noise(0.12, 0.05, vol=0.22, lp=0.3), 0.28)]))

# bastone magico: knock legnoso + hum grave
random.seed(99)
save("evt__pickup_staff.wav", mix([
    pad(wood_knock(150, 0.4), 0.30),
    pad([0]*int(0.04*FR) + tone(90, 0.22, 0.12, vol=0.22, partials=(1, 0.5)), 0.30)]))

# misc/evocable: pickup neutro brillante (due note)
random.seed(100)
save("evt__pickup_misc.wav", mix([
    pad(tone(784, 0.12, 0.08, vol=0.35, partials=(1, 0.4)), 0.26),
    pad([0]*int(0.09*FR) + tone(1175, 0.14, 0.09, vol=0.3, partials=(1, 0.4)), 0.26)]))

# talismano: shimmer esoterico (accordo sospeso + vibrato)
random.seed(101)
save("evt__pickup_talisman.wav", mix([
    pad(tone(659, 0.4, 0.28, vol=0.26, partials=(1, 0.5, 0.3), vibrato=0.015), 0.42),
    pad(tone(988, 0.38, 0.26, vol=0.2, partials=(1, 0.5), vibrato=0.02), 0.42)]))

# oro: jingle di monete (tintinnii metallici multipli)
random.seed(102)
coins = []
for k, f in enumerate([2100, 2640, 1900, 2400, 2200]):
    coins.append(pad([0]*int(0.03*k*FR) + tone(f, 0.10, 0.05, vol=0.22, partials=(1, 0.7, 0.4)), 0.34))
save("evt__pickup_gold.wav", mix(coins))

print("SFX sintetizzati in", OUT)
