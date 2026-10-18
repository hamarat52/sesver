"""SesVer masaüstü başlatıcısı: arayüzü tarayıcı sekmesi yerine gerçek bir pencerede açar.

Gradio sunucusu (app.py'deki build_app) arka plan thread'inde çalışır, pywebview
ana thread'de yerel bir pencere açar. Pencere kapatılınca süreç tamamen sonlanır.
pywebview kullanılamazsa (kurulu değil, Windows'ta WebView2 Runtime yok vb.)
eski davranışa dönülür: arayüz varsayılan tarayıcıda açılır.

Elle çalıştırmak için: python desktop.py   (python app.py de hâlâ çalışır.)
"""
import os
import signal
import socket
import sys
import threading
import time
import urllib.error
import urllib.request

import app
import voice_library as vlib

HOST = "127.0.0.1"
SERVER_TIMEOUT_S = 30  # launch() döndükten sonra HTTP 200 için en fazla bekleme
BUILD_TIMEOUT_S = 300  # build_app() + launch() için üst sınır (ilk açılış yavaş olabilir)

_LOADING_HTML = """<!doctype html><html><head><meta charset="utf-8"><style>
html,body{height:100%;margin:0;background:#0f1115;color:#e6e6e6;
font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
body{display:flex;align-items:center;justify-content:center;flex-direction:column;gap:14px}
.s{width:34px;height:34px;border:3px solid #333;border-top-color:#e6e6e6;border-radius:50%;
animation:r 1s linear infinite}@keyframes r{to{transform:rotate(360deg)}}
</style></head><body><div class="s"></div><div>SesVer açılıyor…</div></body></html>"""

_ERROR_HTML = """<!doctype html><html><head><meta charset="utf-8"><style>
body{margin:0;padding:40px;background:#0f1115;color:#e6e6e6;
font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
pre{white-space:pre-wrap;color:#ff8a8a}</style></head><body>
<h2>SesVer başlatılamadı</h2><p>Ayrıntı için başlatıcı (terminal) penceresindeki mesajları okuyun.</p>
<pre>{msg}</pre></body></html>"""


def _pick_port():
    """GRADIO_SERVER_PORT (yoksa 7860); doluysa boş bir port seçer."""
    wanted = int(os.environ.get("GRADIO_SERVER_PORT", "7860"))
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((HOST, wanted))
            return wanted
        except OSError:
            pass
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((HOST, 0))
        free = s.getsockname()[1]
    print(f"Port {wanted} kullanımda, {free} portu kullanılacak.", flush=True)
    return free


class Server:
    """Gradio sunucusunu arka plan thread'inde başlatır ve hazır olmasını bekler."""

    def __init__(self, port):
        self.port = port
        self.url = f"http://{HOST}:{port}"
        self.demo = None
        self.error = None
        self._launched = threading.Event()
        self._thread = threading.Thread(target=self._run, name="sesver-gradio", daemon=True)

    def start(self):
        self._thread.start()

    def _run(self):
        try:
            demo = app.build_app()
            # app.py'deki launch parametrelerinin aynısı + prevent_thread_lock.
            demo.launch(
                server_name=HOST, server_port=self.port,
                share=False, inbrowser=False,
                css=app._CSS, theme=app._THEME, js=app._JS, footer_links=[],
                allowed_paths=[str(vlib.VOICES_DIR / "hazir"), str(vlib.VOICES_DIR / "seslerim")],
                prevent_thread_lock=True,
            )
            self.demo = demo
        except BaseException as exc:  # noqa: BLE001 — hata ana thread'e taşınır
            self.error = f"{type(exc).__name__}: {exc}"
        finally:
            self._launched.set()

    def wait_ready(self):
        """Sunucu HTTP 200 dönene kadar bekler. Başarıda True, aksi hâlde False (self.error dolu)."""
        if not self._launched.wait(BUILD_TIMEOUT_S):
            self.error = f"Sunucu {BUILD_TIMEOUT_S} sn içinde başlatılamadı."
            return False
        if self.error:
            return False
        deadline = time.monotonic() + SERVER_TIMEOUT_S
        last = ""
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(self.url, timeout=2) as resp:
                    if resp.status == 200:
                        return True
                    last = f"HTTP {resp.status}"
            except (urllib.error.URLError, OSError) as exc:
                last = str(exc)
            time.sleep(0.5)
        self.error = f"Sunucu {SERVER_TIMEOUT_S} sn içinde yanıt vermedi ({last})."
        return False


def _check_webview_backend(webview):
    """Windows'ta WebView2 yoksa pywebview sessizce eski MSHTML (IE) motoruna düşer;
    Gradio arayüzü orada çalışmaz. Bu durumda pencere yerine tarayıcıya dönülür."""
    if sys.platform == "win32":
        from webview.platforms import winforms
        if getattr(winforms, "renderer", "") != "edgechromium":
            raise RuntimeError(
                "Microsoft Edge WebView2 Runtime bulunamadı "
                "(https://developer.microsoft.com/microsoft-edge/webview2/ adresinden kurulabilir)"
            )


def _load_ui(window, server):
    """pywebview GUI döngüsü başladıktan sonra ayrı thread'de çalışır."""
    if server.wait_ready():
        window.load_url(server.url)
    else:
        print(f"[HATA] {server.error}", flush=True)
        window.load_html(_ERROR_HTML.replace("{msg}", server.error or "bilinmeyen hata"))


def _run_window(server):
    """Pencereyi açar; pencere kapanınca döner. pywebview kullanılamazsa istisna fırlatır."""
    import webview

    _check_webview_backend(webview)
    webview.settings["ALLOW_DOWNLOADS"] = True  # "WAV indir" düğmeleri için
    window = webview.create_window(
        "SesVer", html=_LOADING_HTML, width=1280, height=860, min_size=(900, 600),
        background_color="#0f1115",
    )
    webview.start(_load_ui, (window, server))


def _run_browser(server):
    """Eski davranış: arayüzü varsayılan tarayıcıda açar, Ctrl+C'ye kadar çalışır."""
    import webbrowser

    signal.signal(signal.SIGINT, signal.default_int_handler)  # block_thread Ctrl+C'yi düzgün kapatır
    if not server.wait_ready():
        print(f"[HATA] {server.error}", flush=True)
        sys.exit(1)
    print(f"Pencere açılamadı, tarayıcıda açılıyor: {server.url}", flush=True)
    webbrowser.open(server.url)
    print("Durdurmak için bu pencerede Ctrl+C kullanın.", flush=True)
    server.demo.block_thread()


def main():
    app._setup_logging()
    server = Server(_pick_port())
    server.start()
    print(f"SesVer başlatılıyor ({server.url})...", flush=True)

    # GUI döngüsü (özellikle macOS Cocoa) Python'un SIGINT işleyicisini çalıştıramaz;
    # varsayılan davranışla terminaldeki Ctrl+C süreci doğrudan sonlandırır.
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    try:
        _run_window(server)
    except Exception as exc:  # noqa: BLE001 — her türlü pencere hatasında tarayıcıya dön
        print(f"[BILGI] Masaüstü penceresi kullanılamıyor: {type(exc).__name__}: {exc}", flush=True)
        _run_browser(server)
        return
    # Pencere kapatıldı: arka plandaki Gradio sunucusu ve tüm thread'lerle birlikte çık.
    print("Pencere kapatıldı, SesVer kapanıyor.", flush=True)
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
