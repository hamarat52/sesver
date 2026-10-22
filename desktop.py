"""SesVer masaüstü başlatıcısı: arayüzü tarayıcı sekmesi yerine gerçek bir pencerede açar.

Gradio sunucusu (app.py'deki build_app) arka plan thread'inde çalışır, pywebview
ana thread'de yerel bir pencere açar. Pencere kapatılınca süreç tamamen sonlanır.
pywebview kullanılamazsa (kurulu değil, Windows'ta WebView2 Runtime yok vb.)
eski davranışa dönülür: arayüz varsayılan tarayıcıda açılır.

Elle çalıştırmak için: python desktop.py   (python app.py de hâlâ çalışır.)

Tüm çıktı ayrıca sesver_log.txt dosyasına yazılır (her açılışta baştan). Windows
başlatıcısı uygulamayı konsolsuz pythonw.exe ile açtığında hata takibi buradan yapılır.
SESVER_DURUM_DOSYASI ortam değişkeni verilmişse (yalnız WINDOWS_BASLAT.bat verir)
açılış sonucu o dosyaya yazılır: acildi / hata / pencere_yok.
"""
import atexit
import datetime
import html
import os
import signal
import socket
import sys
import threading
import time
import urllib.error
import urllib.request

import hata_rehberi  # yalnız standart kütüphane: numpy/torch yüklenemese de çalışır
import i18n  # aynı şekilde yalnız standart kütüphane (yükleme/hata ekranı seçili dilde)
from i18n import t

LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sesver_log.txt")
# pythonw.exe altında konsol yoktur ve sys.stdout/sys.stderr None olur.
_NO_CONSOLE = sys.stdout is None or sys.stderr is None
_STATUS_FILE = os.environ.get("SESVER_DURUM_DOSYASI", "")


class _Tee:
    """Yazılanı hem asıl akışa (varsa) hem log dosyasına yazar."""

    def __init__(self, stream, log):
        self._stream = stream
        self._log = log

    def write(self, s):
        if self._stream is not None:
            try:
                self._stream.write(s)
            except Exception:  # noqa: BLE001 — konsol hatası log yazımını engellemesin
                pass
        try:
            self._log.write(s)
        except Exception:  # noqa: BLE001
            pass
        return len(s)

    def flush(self):
        for f in (self._stream, self._log):
            if f is not None:
                try:
                    f.flush()
                except Exception:  # noqa: BLE001
                    pass

    def isatty(self):
        return bool(self._stream is not None and self._stream.isatty())

    def fileno(self):
        return (self._stream if self._stream is not None else self._log).fileno()

    def __getattr__(self, name):  # encoding, errors vb.
        return getattr(self._stream if self._stream is not None else self._log, name)


def _report_status(state):
    """Başlatıcının beklediği durum dosyasını atomik olarak yazar."""
    global _STATUS_REPORTED
    if not _STATUS_FILE:
        return
    _STATUS_REPORTED = True
    tmp = _STATUS_FILE + ".yaz"
    try:
        with open(tmp, "w", encoding="ascii") as f:
            f.write(state)  # satır sonu yok: başlatıcı "set /p" ile okur
        os.replace(tmp, _STATUS_FILE)
    except OSError:
        pass


_STATUS_REPORTED = False


def _report_exit_without_status():
    """Süreç durum bildirmeden biterse (sys.exit vb.) başlatıcı 3 dk beklemesin."""
    if not _STATUS_REPORTED:
        _report_status("hata")


def _print_guide(error_text):
    """Hata bilinen bir Windows engeline (Akıllı Uygulama Denetimi) benziyorsa adım adım
    rehberi konsola/log'a yazar ve döndürür; değilse None. Log'un sonunda kalsın diye
    asıl hatadan SONRA çağrılır (başlatıcı sesver_log.txt'nin son satırlarını gösterir)."""
    guide = hata_rehberi.smart_app_control_rehberi(error_text)
    if guide:
        bar = "=" * 64
        print(f"\n{bar}\n{t('NE YAPMALIYIM?')}\n{bar}\n{guide}\n{bar}", file=sys.stderr, flush=True)
    return guide


def _setup_log_file():
    """stdout/stderr'i sesver_log.txt'ye de yönlendirir; yakalanmamış hatayı durum dosyasına bildirir."""
    try:
        log = open(LOG_PATH, "w", encoding="utf-8", errors="replace", buffering=1)
    except OSError:
        log = open(os.devnull, "w", encoding="utf-8")
    sys.stdout = _Tee(sys.stdout, log)
    sys.stderr = _Tee(sys.stderr, log)
    print(f"SesVer günlüğü {datetime.datetime.now():%Y-%m-%d %H:%M:%S} | "
          f"Python {sys.version.split()[0]} | {sys.executable}", flush=True)

    default_hook = sys.excepthook

    def hook(exc_type, exc, tb):
        default_hook(exc_type, exc, tb)
        sys.stderr.flush()
        # Ör. "import app" sırasında NumPy DLL'i engellenirse genel traceback yerine
        # eyleme geçirilebilir rehber de gösterilir.
        try:
            _print_guide(f"{exc_type.__name__}: {exc}")
        except Exception:  # noqa: BLE001 — rehber hatası durum bildirimini engellemesin
            pass
        _report_status("hata")

    sys.excepthook = hook
    atexit.register(_report_exit_without_status)


# Log, app (torch, gradio...) içe aktarılmadan önce kurulur: içe aktarma hataları da
# konsolsuz modda sesver_log.txt'ye düşsün.
if __name__ == "__main__":
    _setup_log_file()

import app  # noqa: E402
import voice_library as vlib  # noqa: E402

HOST = "127.0.0.1"
SERVER_TIMEOUT_S = 30  # launch() döndükten sonra HTTP 200 için en fazla bekleme
BUILD_TIMEOUT_S = 300  # build_app() + launch() için üst sınır (ilk açılış yavaş olabilir)

_LOADING_HTML = """<!doctype html><html><head><meta charset="utf-8"><style>
html,body{height:100%;margin:0;background:#0f1115;color:#e6e6e6;
font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
body{display:flex;align-items:center;justify-content:center;flex-direction:column;gap:14px}
.s{width:34px;height:34px;border:3px solid #333;border-top-color:#e6e6e6;border-radius:50%;
animation:r 1s linear infinite}@keyframes r{to{transform:rotate(360deg)}}
</style></head><body><div class="s"></div><div>{opening}</div></body></html>"""

_ERROR_HTML = """<!doctype html><html><head><meta charset="utf-8"><style>
body{margin:0;padding:40px;background:#0f1115;color:#e6e6e6;
font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
pre{white-space:pre-wrap;color:#ff8a8a}</style></head><body>
<h2>{title}</h2>
<p>{see_log}</p>
<pre style="color:#e6e6e6">{log}</pre>
<pre>{msg}</pre>{guide}</body></html>"""

_GUIDE_HTML = """<h3>{what}</h3><pre style="color:#e6e6e6">{guide}</pre>"""


def _ui_url(base):
    """Kayıtlı arayüz dilinin sayfası (Türkçe kökte; diğerleri /en, /es …)."""
    path = i18n.page_path(i18n.saved_language())
    return f"{base}/{path}" if path else base


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
    # Pencere ekranda (yükleniyor görünümü): başlatıcı konsolu artık kapanabilir.
    _report_status("acildi")
    if server.wait_ready():
        window.load_url(_ui_url(server.url))
    else:
        print(f"[HATA] {server.error}", flush=True)
        print(f"Ayrıntı için: {LOG_PATH}", flush=True)
        guide = _print_guide(server.error)
        window.load_html(
            _ERROR_HTML.replace("{title}", html.escape(t("SesVer başlatılamadı")))
            .replace("{see_log}", html.escape(t("Ayrıntı için SesVer klasöründeki sesver_log.txt dosyasına bakın:")))
            .replace("{log}", html.escape(LOG_PATH))
            .replace("{msg}", html.escape(server.error or t("bilinmeyen hata")))
            .replace("{guide}", _GUIDE_HTML.replace("{what}", html.escape(t("Ne yapmalıyım?")))
                     .replace("{guide}", html.escape(guide)) if guide else "")
        )


def _run_window(server):
    """Pencereyi açar; pencere kapanınca döner. pywebview kullanılamazsa istisna fırlatır."""
    import webview

    _check_webview_backend(webview)
    webview.settings["ALLOW_DOWNLOADS"] = True  # "WAV indir" düğmeleri için
    window = webview.create_window(
        "SesVer", html=_LOADING_HTML.replace("{opening}", html.escape(t("SesVer açılıyor…"))),
        width=1280, height=860, min_size=(900, 600),
        background_color="#0f1115",
    )
    webview.start(_load_ui, (window, server))


def _run_browser(server):
    """Eski davranış: arayüzü varsayılan tarayıcıda açar, Ctrl+C'ye kadar çalışır."""
    import webbrowser

    signal.signal(signal.SIGINT, signal.default_int_handler)  # block_thread Ctrl+C'yi düzgün kapatır
    if not server.wait_ready():
        print(f"[HATA] {server.error}", flush=True)
        _print_guide(server.error)
        sys.exit(1)
    print(f"Pencere açılamadı, tarayıcıda açılıyor: {server.url}", flush=True)
    webbrowser.open(_ui_url(server.url))
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
        if _NO_CONSOLE:
            # Konsolsuz (pythonw) çalışıyoruz: tarayıcı modu Ctrl+C için konsol ister.
            # Başlatıcıya bildirip çık; o, uygulamayı konsollu python.exe ile yeniden açar.
            sys.stdout.flush()
            _report_status("pencere_yok")
            os._exit(3)
        _run_browser(server)
        return
    # Pencere kapatıldı: arka plandaki Gradio sunucusu ve tüm thread'lerle birlikte çık.
    print("Pencere kapatıldı, SesVer kapanıyor.", flush=True)
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
