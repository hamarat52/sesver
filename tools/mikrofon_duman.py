"""Mikrofon kaydı duman testi (CDP): açık bir SesVer sayfasında iki kaydediciyi gerçek tıklamayla dener
ve sonucu JSON olarak basar:

- yukle: Ses Oluştur → Dosya yükle → Kaydet → N sn → Durdur; kayıt dosya yolundaki hazırlıktan geçmeli
  (sayfada "… WAV …" hazırlık satırı).
- klon: Ses Klonlama → Referans ses → mikrofon simgesi → Kaydet → N sn → Durdur; kayıt yerel sunucuya
  yüklenmeli (referans alanında /gradio_api/file= bağlantısı) ve indirilen WAV, sunucunun klon
  denetimiyle (generate_audio: 1–30 sn) aynı aralıkta olmalı.

Gerçek mikrofon gerekmez: tarayıcı/WebView2 sahte cihazla başlatılır. Windows CI örneği (WebView2):

    set WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--remote-debugging-port=9222 --use-fake-device-for-media-stream --use-fake-ui-for-media-stream
    pythonw desktop.py            (SesVer penceresi açılır)
    python tools/mikrofon_duman.py --cdp http://127.0.0.1:9222

Chrome/Edge ile (tarayıcı yolu):

    chrome --headless=new --remote-debugging-port=9222 --use-fake-device-for-media-stream \
           --use-fake-ui-for-media-stream --user-data-dir=<boş klasör> http://127.0.0.1:7860/
    python tools/mikrofon_duman.py --cdp http://127.0.0.1:9222

Güvenlik: yalnız adresi http://127.0.0.1 ile başlayan SesVer sekmesine bağlanır; başka sekmeye
(kullanıcının açık tarayıcısı vb.) hiçbir komut göndermez; kayıt dosyası da yalnız 127.0.0.1'den
indirilir. Çıkış kodu: 0 seçilen alanların (--alan, varsayılan hepsi) hepsi geçti, 1 en az biri
geçmedi (iletiyle), 2 SesVer sekmesi bulunamadı, 3 (--paket-denetimi) gerekli paket eksik.

Yalnız standart kütüphane kullanır (en küçük WebSocket istemcisi aşağıda): SesVer'in kilitli paket
listesinde (kilit/) WebSocket kütüphanesi yok, CI ek paket kurmaz.
"""
import argparse
import base64
import io
import json
import os
import socket
import struct
import sys
import time
import urllib.parse
import urllib.request
import wave


class WebSocket:
    """RFC 6455 istemcisi; yalnız CDP için gereken kadarı (metin çerçeveleri, parçalı ileti, ping)."""

    def __init__(self, url, timeout=60):
        u = urllib.parse.urlsplit(url)
        if u.scheme != "ws" or u.hostname not in ("127.0.0.1", "localhost"):
            raise ValueError(f"yalnız yerel ws:// adresi: {url}")
        self.sock = socket.create_connection((u.hostname, u.port or 80), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        path = u.path + (f"?{u.query}" if u.query else "")
        self.sock.sendall((f"GET {path} HTTP/1.1\r\nHost: {u.hostname}:{u.port}\r\nUpgrade: websocket\r\n"
                           f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n")
                          .encode())
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = self.sock.recv(1)
            if not chunk:
                raise ConnectionError("WebSocket el sıkışması yarıda kaldı")
            head += chunk
        if b" 101 " not in head.split(b"\r\n", 1)[0]:
            raise ConnectionError(f"WebSocket el sıkışması reddedildi: {head[:80]!r}")

    def _exact(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("WebSocket bağlantısı kapandı")
            buf += chunk
        return buf

    def _frame(self, opcode, data):
        mask = os.urandom(4)
        n = len(data)
        head = bytes([0x80 | opcode])
        if n < 126:
            head += bytes([0x80 | n])
        elif n < 65536:
            head += bytes([0x80 | 126]) + struct.pack("!H", n)
        else:
            head += bytes([0x80 | 127]) + struct.pack("!Q", n)
        self.sock.sendall(head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def send(self, text):
        self._frame(0x1, text.encode("utf-8"))

    def recv(self):
        parts = []
        while True:
            b1, b2 = self._exact(2)
            opcode, n = b1 & 0x0F, b2 & 0x7F
            if n == 126:
                n = struct.unpack("!H", self._exact(2))[0]
            elif n == 127:
                n = struct.unpack("!Q", self._exact(8))[0]
            mask = self._exact(4) if b2 & 0x80 else None
            data = self._exact(n)
            if mask:
                data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
            if opcode == 0x9:  # ping → pong
                self._frame(0xA, data)
                continue
            if opcode == 0x8:
                raise ConnectionError("WebSocket kapatıldı")
            if opcode in (0x0, 0x1, 0x2):
                parts.append(data)
                if b1 & 0x80:
                    return b"".join(parts).decode("utf-8")

    def close(self):
        try:
            self._frame(0x8, b"")
        except OSError:
            pass
        self.sock.close()


class Sekme:
    def __init__(self, ws):
        self.ws = ws
        self.n = 0

    def cdp(self, method, **params):
        self.n += 1
        self.ws.send(json.dumps({"id": self.n, "method": method, "params": params}))
        while True:
            m = json.loads(self.ws.recv())
            if m.get("id") == self.n:
                if "error" in m:
                    raise RuntimeError(f"{method}: {m['error']}")
                return m.get("result", {})

    def js(self, expr):
        r = self.cdp("Runtime.evaluate", expression=expr, returnByValue=True, awaitPromise=True)
        return r.get("result", {}).get("value")

    def tikla(self, sel, idx=0):
        konum = self.js(f"""(() => {{ const e=[...document.querySelectorAll({json.dumps(sel)})]
            .filter(x => x.offsetParent)[{idx}]; if (!e) return null; e.scrollIntoView({{block: 'center'}});
            const r = e.getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; }})()""")
        if not konum:
            raise RuntimeError(f"bulunamadı: {sel}")
        time.sleep(0.4)
        for tur in ("mousePressed", "mouseReleased"):
            self.cdp("Input.dispatchMouseEvent", type=tur, x=konum[0], y=konum[1], button="left", clickCount=1)
        time.sleep(0.8)


DURUM_JS = """(() => {
  const s = document.querySelector('.sv-mic-status-yukle'); if (!s) return null;
  const m = s.querySelector('.sv-mic-meter'); const vis = (e) => e && e.offsetParent;
  return {sure: m.hidden ? null : s.querySelector('.sv-mic-time').textContent, durum: m.dataset.state || null,
          ileti: s.querySelector('.sv-mic-msg').textContent,
          hazirlik: ([...document.querySelectorAll('.sv-panel .sv-fine-md')].filter(vis)
                     .map((e) => e.innerText.trim()).find((t) => t.includes('WAV')) || '').split('\\n')[0]};
})()"""


# Ses Klonlama referansı: süre göstergesi + kayıt sunucuya yüklendiyse indirme bağlantısı.
KLON_JS = """(() => {
  const vis = (e) => e && e.offsetParent;
  const s = [...document.querySelectorAll('.sv-mic-status-klon')].find(vis); if (!s) return null;
  const r = [...document.querySelectorAll('.sv-mic-ref')].find(vis);
  const m = s.querySelector('.sv-mic-meter');
  const a = r && [...r.querySelectorAll('a[href]')].find((x) => x.getAttribute('href').includes('/gradio_api/file='));
  return {sure: m.hidden ? null : s.querySelector('.sv-mic-time').textContent, durum: m.dataset.state || null,
          ileti: s.querySelector('.sv-mic-msg').textContent, dosya: a ? a.href : null};
})()"""

KLON_MIN, KLON_MAX = 1.0, 30.0  # app.generate_audio / kuyruga_ekle_klon_ui ile aynı

# --paket-denetimi: duman testinin (desktop.py → app.py, pywebview + WebView2 köprüsü pythonnet,
# yazıya dökme, model paketleri) gerçekten ihtiyaç duyduğu üst düzey modüller. Yalnız
# importlib.util.find_spec: içe aktarılmaz, yan etki yok. pythonnet yalnız Windows kilidinde var.
GEREKLI_PAKETLER = ("gradio", "numpy", "soundfile", "scipy", "webview", "pythonnet", "faster_whisper",
                    "torch", "voxcpm")


def eksik_paketler(adlar=GEREKLI_PAKETLER):
    import importlib.util
    return [ad for ad in adlar if importlib.util.find_spec(ad) is None]


def wav_bilgisi(veri):
    """WAV baytlarından (saniye, kanal, örnek genişliği bayt). Bozuksa ValueError."""
    try:
        with wave.open(io.BytesIO(veri)) as w:
            return w.getnframes() / float(w.getframerate()), w.getnchannels(), w.getsampwidth()
    except (wave.Error, EOFError, ZeroDivisionError) as exc:
        raise ValueError(f"WAV okunamadı: {exc}") from exc


def _yerel_indir(url):
    u = urllib.parse.urlsplit(url)
    if u.scheme != "http" or u.hostname not in ("127.0.0.1", "localhost"):
        raise ValueError(f"yalnız yerel dosya indirilir: {url[:60]}")
    with urllib.request.urlopen(url, timeout=30) as r:
        return r.read()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cdp", default="http://127.0.0.1:9222")
    ap.add_argument("--saniye", type=float, default=9.5)
    ap.add_argument("--bekle", type=int, default=300, help="SesVer sekmesi için en fazla bekleme (sn)")
    ap.add_argument("--alan", choices=("hepsi", "yukle", "klon"), default="hepsi",
                    help="yukle: Ses Oluştur → Dosya yükle; klon: Ses Klonlama → Referans ses")
    ap.add_argument("--paket-denetimi", action="store_true",
                    help="yalnız bu Python'da gerekli paketler var mı bak (3 = eksik var); sekmeye bağlanmaz")
    a = ap.parse_args()
    if a.paket_denetimi:
        eksik = eksik_paketler()
        print(json.dumps({"python": sys.executable, "gerekli": list(GEREKLI_PAKETLER), "eksik": eksik},
                         ensure_ascii=False))
        return 3 if eksik else 0
    sekme = None
    for _ in range(a.bekle):  # SesVer açılana kadar (ilk açılış yavaş olabilir)
        try:
            with urllib.request.urlopen(a.cdp + "/json", timeout=5) as r:
                sekme = next((t for t in json.load(r) if t.get("type") == "page"
                              and t.get("url", "").startswith("http://127.0.0.1")), None)
        except OSError:
            pass
        if sekme:
            break
        time.sleep(1)
    if not sekme:
        print(json.dumps({"hata": "SesVer sekmesi (http://127.0.0.1...) bulunamadı"}, ensure_ascii=False))
        return 2
    ws = WebSocket(sekme["webSocketDebuggerUrl"])
    try:
        return _calistir(Sekme(ws), sekme["url"], a.saniye, a.alan)
    finally:
        ws.close()


def _calistir(s, url, saniye, alan="hepsi"):
    s.cdp("Runtime.enable")
    for _ in range(120):
        if s.js("[...document.querySelectorAll('#sv-tabs button[role=tab]')].filter(x => x.offsetParent).length"):
            break
        time.sleep(0.5)
    s.cdp("Input.dispatchKeyEvent", type="keyDown", key="Escape")  # açılış ekranını geç
    s.cdp("Input.dispatchKeyEvent", type="keyUp", key="Escape")
    time.sleep(1.5)
    rapor = {"sekme": url, "ua": s.js("navigator.userAgent")}
    gecti = True
    if alan in ("hepsi", "yukle"):
        rapor["yukle"] = _yukle(s, saniye)
        gecti &= rapor["yukle"]["gecti"]
    if alan in ("hepsi", "klon"):
        rapor["klon"] = _klon(s, saniye)
        gecti &= rapor["klon"]["gecti"]
    print(json.dumps(rapor, ensure_ascii=False, indent=1))
    return 0 if gecti else 1


def _durdur(s, kapsam):
    sel = f"{kapsam} .stop-button"
    if s.js(f"[...document.querySelectorAll({json.dumps(sel)})].some(x => x.offsetParent)"):
        s.tikla(sel)


def _yukle(s, saniye):
    s.tikla("#sv-tabs button[role=tab]", 1)       # Ses Oluştur
    s.tikla("#sv-subtabs button[role=tab]", 1)    # Dosya yükle
    s.tikla(".sv-mic:not(.sv-mic-ref) .record-button")
    time.sleep(saniye)
    sirasinda = s.js(DURUM_JS)
    _durdur(s, ".sv-mic:not(.sv-mic-ref)")
    sonuc = None
    for _ in range(30):
        time.sleep(1)
        sonuc = s.js(DURUM_JS)
        if sonuc and (sonuc["hazirlik"] or sonuc["ileti"]):
            break
    return {"kayit_sirasinda": sirasinda, "sonuc": sonuc,
            "gecti": bool(sonuc and sonuc["hazirlik"] and not sonuc["ileti"])}


def _klon(s, saniye):
    s.tikla("#sv-tabs button[role=tab]", 2)                 # Ses Klonlama
    s.tikla(".sv-mic-ref .source-selection button", 1)      # mikrofon kaynağı (dosya simgesinden sonra)
    s.tikla(".sv-mic-ref .record-button")
    time.sleep(saniye)
    sirasinda = s.js(KLON_JS)
    _durdur(s, ".sv-mic-ref")
    sonuc = None
    for _ in range(30):
        time.sleep(1)
        sonuc = s.js(KLON_JS)
        if sonuc and (sonuc["dosya"] or sonuc["ileti"]):
            break
    out = {"kayit_sirasinda": sirasinda, "sonuc": sonuc, "gecti": False}
    if not (sonuc and sonuc["dosya"]) or sonuc["ileti"]:
        return out
    try:
        sure, kanal, genislik = wav_bilgisi(_yerel_indir(sonuc["dosya"]))
    except (OSError, ValueError) as exc:
        out["wav_hata"] = str(exc)
        return out
    out["wav"] = {"saniye": round(sure, 2), "kanal": kanal, "bit": genislik * 8}
    out["gecti"] = KLON_MIN <= sure <= KLON_MAX
    return out


if __name__ == "__main__":
    sys.exit(main())
