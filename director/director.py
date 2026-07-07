import json, os, sys
from router import path_to_token, Router
from audio_engine import AudioEngine
from pipe_server import PipeServer

HERE = os.path.dirname(os.path.abspath(__file__))
AUDIO_ROOT = os.path.join(HERE, "..", "audio")

def main():
    soundmap = json.load(open(os.path.join(HERE, "soundmap.json"), encoding="utf-8"))
    router = Router(soundmap)
    engine = AudioEngine(os.path.abspath(AUDIO_ROOT))

    sfx_files = []
    for entry in soundmap.get("sfx", {}).values():
        sfx_files.extend(entry.get("files", []))
    engine.prewarm("sfx", sfx_files)

    print("[director] pronto. In ascolto su \\\\.\\pipe\\dcss_audio")

    def handle(raw):
        token = path_to_token(raw)
        actions = router.route(token)
        print("[evt]", token, "->", [a["op"] for a in actions] or "(nessuna azione)")
        for a in actions:
            op = a["op"]
            if op == "sfx":     engine.play_sfx(a["file"], a["volume"], a["group"])
            elif op == "music": engine.play_music(a["file"], a["volume"])
            elif op == "duck":  engine.duck(a["volume"])
            elif op == "unduck":engine.unduck()
            elif op == "stop_music": engine.stop_music()
        sys.stdout.flush()

    def on_disconnect():
        print("[director] gioco disconnesso: sfumo la musica")
        engine.stop_music()

    PipeServer(handle, on_disconnect=on_disconnect).serve_forever()

if __name__ == "__main__":
    main()
