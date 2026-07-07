import time
import win32pipe, win32file, pywintypes

PIPE_NAME = r"\\.\pipe\dcss_audio"

ERROR_PIPE_CONNECTED = 535  # ConnectNamedPipe: client connected between create and connect calls

class PipeServer:
    def __init__(self, on_message, on_disconnect=None):
        self.on_message = on_message
        self.on_disconnect = on_disconnect

    def serve_forever(self):
        while True:
            try:
                h = win32pipe.CreateNamedPipe(
                    PIPE_NAME,
                    win32pipe.PIPE_ACCESS_INBOUND,
                    win32pipe.PIPE_TYPE_BYTE | win32pipe.PIPE_READMODE_BYTE | win32pipe.PIPE_WAIT,
                    1, 65536, 65536, 0, None)
            except pywintypes.error as e:
                # es. ERROR_PIPE_BUSY se un vecchio Director tiene ancora la pipe: riprova piu' tardi
                print("[director] CreateNamedPipe fallita, ritento:", e)
                time.sleep(0.5)
                continue

            connected = False
            try:
                try:
                    win32pipe.ConnectNamedPipe(h, None)
                    connected = True
                except pywintypes.error as e:
                    if getattr(e, "winerror", None) == ERROR_PIPE_CONNECTED:
                        # il client si e' gia' connesso tra CreateNamedPipe e ConnectNamedPipe: va bene
                        connected = True
                    else:
                        raise

                buf = b""
                while True:
                    hr, data = win32file.ReadFile(h, 4096)
                    if not data:
                        break
                    buf += data
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        tok = line.decode("utf-8", "replace").strip()
                        if tok:
                            try:
                                self.on_message(tok)
                            except Exception as e:
                                print(f"[director] errore su token '{tok}':", e)
            except pywintypes.error:
                pass  # client disconnected -> recreate pipe
            finally:
                win32file.CloseHandle(h)
                # il gioco si e' disconnesso (chiuso o riavviato): sfuma la musica
                # (solo se un client si era davvero connesso, non sul retry per CreateNamedPipe fallita)
                if connected and self.on_disconnect:
                    self.on_disconnect()
