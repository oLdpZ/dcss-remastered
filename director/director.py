import json, os, sys, time
from router import path_to_token, Router
from audio_engine import AudioEngine
from pipe_server import PipeServer
from visual_router import VisualRouter
from gfx_state import GfxShmem

HERE = os.path.dirname(os.path.abspath(__file__))
AUDIO_ROOT = os.path.join(HERE, "..", "audio")

# Log su file: il Director gira con finestra nascosta, quindi lo stdout non si vede.
# Ogni evento ricevuto viene registrato qui per diagnostica.
_LOG = open(os.path.join(HERE, "director.log"), "a", encoding="utf-8", buffering=1)
def logln(msg):
    _LOG.write(time.strftime("%H:%M:%S ") + msg + "\n")

def main():
    soundmap = json.load(open(os.path.join(HERE, "soundmap.json"), encoding="utf-8"))
    router = Router(soundmap)
    engine = AudioEngine(os.path.abspath(AUDIO_ROOT))

    try:
        visualmap = json.load(open(os.path.join(HERE, "visualmap.json"), encoding="utf-8"))
        vrouter = VisualRouter(visualmap)
        shm = GfxShmem(); shm.open(); shm.write(vrouter.state)
        gfx_ok = True
    except Exception as e:
        print("[director] layer grafico disattivato (audio prosegue):", e)
        vrouter = None; shm = None; gfx_ok = False

    sfx_files = []
    for entry in soundmap.get("sfx", {}).values():
        sfx_files.extend(entry.get("files", []))
    engine.prewarm("sfx", sfx_files)

    # Musica del menu principale: parte all'avvio (il Director parte prima del gioco);
    # il primo cambio di branch in gioco fara' il crossfade al tema della zona.
    menu = soundmap.get("menu")
    if menu:
        engine.play_music(menu["file"], menu.get("volume", 0.5))
        print("[director] musica menu:", menu["file"])

    print("[director] pronto. In ascolto su \\\\.\\pipe\\dcss_audio")
    logln("=== director avviato, in ascolto ===")

    def handle(raw):
        token = path_to_token(raw)
        actions = router.route(token)
        ops = [a["op"] for a in actions] or "(nessuna azione)"
        print("[evt]", token, "->", ops)
        logln("[evt] " + token + " -> " + str(ops))
        for a in actions:
            op = a["op"]
            if op == "sfx":     engine.play_sfx(a["file"], a["volume"], a["group"], a.get("duck", False))
            elif op == "music": engine.play_music(a["file"], a["volume"])
            elif op == "duck":  engine.duck(a["volume"])
            elif op == "unduck":engine.unduck()
            elif op == "stop_music": engine.stop_music()
        if gfx_ok and vrouter.route(token):
            shm.write(vrouter.state)
        sys.stdout.flush()

    def on_disconnect():
        print("[director] gioco disconnesso: sfumo la musica")
        engine.stop_music()

    PipeServer(handle, on_disconnect=on_disconnect).serve_forever()

if __name__ == "__main__":
    main()
