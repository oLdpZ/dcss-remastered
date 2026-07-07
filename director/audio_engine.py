import os, pygame

class AudioEngine:
    def __init__(self, audio_root: str, sfx_channels: int = 12):
        self.root = audio_root
        pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
        pygame.mixer.set_num_channels(sfx_channels + 2)
        pygame.mixer.set_reserved(2)  # canali 0,1 riservati alla musica: Sound.play() non li usa
        self._music_ch = pygame.mixer.Channel(0)       # canale musica A
        self._music_next = pygame.mixer.Channel(1)     # canale musica B (crossfade)
        self._cache = {}
        self._music_vol = 0.5
        self._ducked = False

    def _load(self, subdir, file):
        key = (subdir, file)
        if key not in self._cache:
            self._cache[key] = pygame.mixer.Sound(os.path.join(self.root, subdir, file))
        return self._cache[key]

    def play_sfx(self, file, volume=1.0, group=None):
        try:
            s = self._load("sfx", file); s.set_volume(volume); s.play()
        except Exception as e:
            print("[sfx err]", file, e)

    def play_music(self, file, volume=0.5):
        try:
            s = self._load("music", file)
            self._music_vol = volume
            cur = self._music_ch
            cur.fadeout(600)
            s.set_volume(0.0 if self._ducked else volume)
            self._music_next.play(s, loops=-1, fade_ms=600)
            self._music_ch, self._music_next = self._music_next, self._music_ch
        except Exception as e:
            print("[music err]", file, e)

    def duck(self, volume=0.3):
        self._ducked = True
        self._music_ch.set_volume(volume)
        self._music_next.set_volume(volume)

    def unduck(self):
        self._ducked = False
        self._music_ch.set_volume(self._music_vol)
        self._music_next.set_volume(self._music_vol)

    def stop_music(self):
        self._music_ch.fadeout(800); self._music_next.fadeout(800)

    def prewarm(self, subdir, files):
        for f in files:
            try:
                self._load(subdir, f)
            except Exception as e:
                print("[prewarm err]", f, e)
