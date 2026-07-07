import win32pipe, win32file, pywintypes

PIPE_NAME = r"\\.\pipe\dcss_audio"

class PipeServer:
    def __init__(self, on_message, on_disconnect=None):
        self.on_message = on_message
        self.on_disconnect = on_disconnect

    def serve_forever(self):
        while True:
            h = win32pipe.CreateNamedPipe(
                PIPE_NAME,
                win32pipe.PIPE_ACCESS_INBOUND,
                win32pipe.PIPE_TYPE_BYTE | win32pipe.PIPE_READMODE_BYTE | win32pipe.PIPE_WAIT,
                1, 65536, 65536, 0, None)
            try:
                win32pipe.ConnectNamedPipe(h, None)
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
                            self.on_message(tok)
            except pywintypes.error:
                pass  # client disconnected -> recreate pipe
            finally:
                win32file.CloseHandle(h)
                # il gioco si e' disconnesso (chiuso o riavviato): sfuma la musica
                if self.on_disconnect:
                    self.on_disconnect()
