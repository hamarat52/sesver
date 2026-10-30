"""SesVer masaüstü başlatıcısı: arayüzü tarayıcı sekmesi yerine gerçek bir pencerede açar.

Gradio sunucusu (app.py'deki build_app) arka plan thread'inde çalışır, pywebview
ana thread'de yerel bir pencere açar. Pencere kapatılınca süreç tamamen sonlanır.
pywebview kullanılamazsa (kurulu değil, Windows'ta WebView2 Runtime yok vb.)
eski davranışa dönülür: arayüz varsayılan tarayıcıda açılır.

Elle çalıştırmak için: python desktop.py   (python app.py de hâlâ çalışır.)

Tüm çıktı ayrıca sesver_log.txt dosyasına yazılır (her açılışta baştan; bir önceki
açılışın günlüğü sesver_log_onceki.txt olarak saklanır). Windows
başlatıcısı uygulamayı konsolsuz pythonw.exe ile açtığında hata takibi buradan yapılır.
SESVER_DURUM_DOSYASI ortam değişkeni verilmişse (yalnız WINDOWS_BASLAT.bat verir)
açılış sonucu o dosyaya yazılır: acildi / hata / pencere_yok.
"""
import atexit
import datetime
import html
import json
import os
import signal
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request

import hata_raporu  # aynı şekilde yalnız standart kütüphane (başlatma hatasında rapor)
import hata_rehberi  # yalnız standart kütüphane: numpy/torch yüklenemese de çalışır
import i18n  # aynı şekilde yalnız standart kütüphane (yükleme/hata ekranı seçili dilde)
from i18n import t

LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sesver_log.txt")
PREV_LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sesver_log_onceki.txt")
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
    """stdout/stderr'i sesver_log.txt'ye de yönlendirir; yakalanmamış hatayı durum dosyasına bildirir.

    Önceki açılışın günlüğü (hata kanıtı) silinmesin diye önce sesver_log_onceki.txt'ye taşınır."""
    hata_raporu.rotate_log(LOG_PATH, PREV_LOG_PATH)
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
<pre>{msg}</pre>{guide}{report}</body></html>"""

_GUIDE_HTML = """<h3>{what}</h3><pre style="color:#e6e6e6">{guide}</pre>"""

# Başlatma hatasında "Hata raporu gönder": rapor önce gösterilir, e-posta taslağı ancak
# kullanıcı "E-posta uygulamasında aç"a basınca açılır (pywebview js_api → ReportApi).
_REPORT_HTML = """<style>
.rp button{font:inherit;padding:8px 14px;margin:4px 6px 4px 0;border-radius:10px;border:1px solid #555;
background:#1d2129;color:#e6e6e6;cursor:pointer}.rp button.p{background:#e6e6e6;color:#0f1115}
.rp textarea{width:100%;box-sizing:border-box;height:260px;background:#171a21;color:#e6e6e6;border:1px solid #333;
border-radius:10px;padding:10px;font:12px ui-monospace,Menlo,Consolas,monospace}.rp .f{color:#9aa0aa;font-size:13px}
</style><div class="rp"><h3>{title}</h3>
<button id="rp-open" class="p">{send}</button>
<div id="rp-box" hidden><p><b>{consent}</b> {details}</p>
<label id="rp-prev-row" hidden><input type="checkbox" id="rp-prev"> {prev}</label>
<textarea id="rp-text" readonly></textarea>
<div><button id="rp-mail" class="p">{mail}</button><button id="rp-copy">{copy}</button></div>
<p class="f">{to}</p></div><p id="rp-msg"></p></div>
<script>
(function () {
  const $ = (id) => document.getElementById(id);
  const api = () => window.pywebview && window.pywebview.api;
  const say = (s) => { $('rp-msg').textContent = s || ''; };
  async function prepare(prev) {
    if (!api()) { say({noapi}); return; }
    say({wait});
    const r = await api().hazirla(prev);
    $('rp-text').value = r.text; $('rp-prev').checked = !!r.prev_checked;
    $('rp-prev-row').hidden = !r.prev_exists; $('rp-box').hidden = false; say('');
  }
  $('rp-open').onclick = () => prepare(null);
  $('rp-prev').onchange = (e) => prepare(e.target.checked);
  $('rp-mail').onclick = async () => { if (api()) say(await api().eposta()); };
  $('rp-copy').onclick = async () => { if (api()) say(await api().kopyala()); };
})();
</script>"""


class ReportApi:
    """pywebview js_api: başlatma hatası ekranındaki rapor düğmeleri (yalnız kullanıcı tıklayınca)."""

    def __init__(self):
        self._report = None

    def hazirla(self, prev=None):
        """Raporu kurar ve önizleme için döndürür; hiçbir şey açılmaz/gönderilmez."""
        prev_exists = os.path.isfile(PREV_LOG_PATH)
        if prev is None:
            prev = prev_exists and hata_raporu.log_has_error(PREV_LOG_PATH)
        prev = bool(prev) and prev_exists
        self._report = hata_raporu.build_report(include_previous=prev, log_path=LOG_PATH, prev_path=PREV_LOG_PATH)
        return {"text": self._report["text"], "prev_exists": prev_exists, "prev_checked": prev}

    def eposta(self):
        if not self._report:
            return t("Önce “Hata raporu gönder” ile raporu hazırlayın.")
        try:
            path, opened = hata_raporu.send(self._report)
        except OSError as exc:
            return t("Rapor dosyası yazılamadı: {hata}", hata=f"{type(exc).__name__}: {exc}")
        return hata_raporu.send_message(path, opened)

    def kopyala(self):
        if not self._report:
            return t("Önce “Hata raporu gönder” ile raporu hazırlayın.")
        return hata_raporu.copy_message(hata_raporu.copy_to_clipboard(hata_raporu.clipboard_text(self._report)))


def _report_html():
    consent, details = hata_raporu.consent_text()
    esc = html.escape
    return (_REPORT_HTML.replace("{title}", esc(t("Sorun bildir / Hata raporu gönder")))
            .replace("{send}", esc(t("Hata raporu gönder")))
            .replace("{consent}", esc(consent)).replace("{details}", esc(details))
            .replace("{prev}", esc(t("Önceki oturumun günlüğünü de ekle")))
            .replace("{mail}", esc(t("E-posta uygulamasında aç"))).replace("{copy}", esc(t("Panoya kopyala")))
            .replace("{to}", esc(hata_raporu.recipient_text()))
            .replace("{wait}", json.dumps(t("Rapor hazırlanıyor…"), ensure_ascii=False))
            .replace("{noapi}", json.dumps(t("Rapor düğmesi bu pencerede çalışmıyor. Lütfen {log} dosyasını "
                                             "{adres} adresine e-postayla gönderin.",
                                             log=LOG_PATH, adres=hata_raporu.DESTEK_EPOSTA), ensure_ascii=False)))


def _ui_url(base):
    """Açılış dilinin sayfası (Türkçe kökte; diğerleri /en, /es …).

    Dil: ayarlar.json'daki tercih; yoksa (ilk açılış) işletim sisteminin dili,
    o da desteklenmiyorsa İngilizce (bkz. i18n.saved_language)."""
    path = i18n.page_path(i18n.saved_language())
    return f"{base}/{path}" if path else base


def _language_note(base):
    """Günlük satırı: hangi dille ve neden (kayıtlı tercih / sistem dili) açılıyor."""
    source = "ayarlar.json" if i18n.stored_language() else "sistem dili"
    return f"Arayüz dili: {i18n.saved_language()} ({source}) -> {_ui_url(base)}"


def _pick_port():
    """İlk denenecek port: GRADIO_SERVER_PORT (yoksa 7860). Burada soketle yoklanmaz —
    yokla-sonra-kullan yarışı doğurur; port doluysa Server._run sonraki portları dener."""
    return int(os.environ.get("GRADIO_SERVER_PORT", "7860"))


class Server:
    """Gradio sunucusunu arka plan thread'inde başlatır ve hazır olmasını bekler."""

    def __init__(self, port):
        self.port = port
        self.url = f"http://{HOST}:{port}"
        self.demo = None
        self.error = None
        self.traceback = ""
        self._launched = threading.Event()
        self._thread = threading.Thread(target=self._run, name="sesver-gradio", daemon=True)

    def start(self):
        self._thread.start()

    def _run(self):
        try:
            demo = app.build_app()
            # app.py'deki launch parametrelerinin aynısı + prevent_thread_lock.
            # Port doluysa (OSError) sonraki portlar denenir; açılan port URL'ye yansır.
            port = app.launch_with_port_retry(
                demo, self.port,
                server_name=HOST,
                share=False, inbrowser=False,
                css=app._CSS, theme=app._THEME, js=app._JS, footer_links=[],
                allowed_paths=[str(vlib.VOICES_DIR / "hazir"), str(vlib.VOICES_DIR / "seslerim")],
                prevent_thread_lock=True,
            )
            self.port, self.url = port, f"http://{HOST}:{port}"
            self.demo = demo
        except BaseException as exc:  # noqa: BLE001 — hata ana thread'e taşınır
            self.error = hata_raporu.exc_line(exc)  # "MemoryError: MemoryError: …" olmasın
            self.traceback = traceback.format_exc()  # hata raporu için (log'a ana thread yazar)
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
        if server.traceback:
            print(server.traceback, end="", file=sys.stderr, flush=True)
        print(f"Ayrıntı için: {LOG_PATH}", flush=True)
        hata_raporu.record_text_error(server.error or "", server.traceback, where="startup")
        guide = _print_guide(server.error)
        window.load_html(
            _ERROR_HTML.replace("{title}", html.escape(t("SesVer başlatılamadı")))
            .replace("{see_log}", html.escape(t("Ayrıntı için SesVer klasöründeki sesver_log.txt dosyasına bakın:")))
            .replace("{log}", html.escape(LOG_PATH))
            .replace("{msg}", html.escape(server.error or t("bilinmeyen hata")))
            .replace("{guide}", _GUIDE_HTML.replace("{what}", html.escape(t("Ne yapmalıyım?")))
                     .replace("{guide}", html.escape(guide)) if guide else "")
            .replace("{report}", _report_html())
        )


def _run_window(server):
    """Pencereyi açar; pencere kapanınca döner. pywebview kullanılamazsa istisna fırlatır."""
    import webview

    _check_webview_backend(webview)
    webview.settings["ALLOW_DOWNLOADS"] = True  # "WAV indir" düğmeleri için
    window = webview.create_window(
        "SesVer", html=_LOADING_HTML.replace("{opening}", html.escape(t("SesVer açılıyor…"))),
        width=1280, height=860, min_size=(900, 600),
        background_color="#0f1115", js_api=ReportApi(),
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
    # "Yeni sürüm var" kontrolü arka plan thread'inde; açılışı bekletmez (bkz. guncelleme.py).
    app.guncelleme.baslat()
    server = Server(_pick_port())
    server.start()
    print(f"SesVer başlatılıyor ({server.url})...", flush=True)
    print(_language_note(server.url), flush=True)

    # GUI döngüsü (özellikle macOS Cocoa) Python'un SIGINT işleyicisini çalıştıramaz;
    # varsayılan davranışla terminaldeki Ctrl+C süreci doğrudan sonlandırır.
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    try:
        _run_window(server)
    except Exception as exc:  # noqa: BLE001 — her türlü pencere hatasında tarayıcıya dön
        print(f"[BILGI] Masaüstü penceresi kullanılamıyor: {hata_raporu.exc_line(exc)}", flush=True)
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
