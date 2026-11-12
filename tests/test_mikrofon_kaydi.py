"""1.4.2: mikrofonla kayıt (Ses Oluştur → Dosya yükle ve Ses Klonlama → Referans ses).

Kayıt dosya yolundaki işlemlerin aynısından geçer (Ses Oluştur: dönüştürme, kırpma, 8–20 sn kuralı,
izin kutucuğu; Ses Klonlama: 1–30 sn denetimi, otomatik yazıya dökme); izin reddi / cihaz yok
iletileri sayfanın dilinde; Mac paketi mikrofon iznini isteyebilir (Info.plist + entitlement).
Model yüklenmez; ağ çağrılmaz.
"""
import json
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import soundfile as sf

import app
import audio_prep
import i18n
import voice_library as vl

ROOT = Path(__file__).resolve().parent.parent
SR = 44100
MIC_KEYS = [
    "ya da", "Mikrofonla kaydedin", "Mikrofon kaydı",
    "Kaydet'e basın, 8–20 saniye konuşun ve Durdur'a basın. Dinleyin; beğenmezseniz silip yeniden kaydedin. "
    "Kayıt yalnız bu bilgisayarda kalır.",
    "Mikrofon izni bekleniyor. Açılan pencerede izin verin.",
    "Mikrofon izni verilmedi. Sistem Ayarları > Gizlilik ve Güvenlik > Mikrofon'da SesVer'i açın, SesVer'i "
    "yeniden başlatıp tekrar deneyin ya da dosya yükleyin.",
    "Mikrofon izni verilmedi. Ayarlar > Gizlilik ve güvenlik > Mikrofon'da masaüstü uygulamalarına izin verin, "
    "SesVer'i yeniden açıp tekrar deneyin ya da dosya yükleyin.",
    "Mikrofon izni verilmedi. Adres çubuğundaki simgeden ve sistem ayarlarından tarayıcınıza izin verip tekrar "
    "deneyin ya da dosya yükleyin.",
    "Mikrofon bulunamadı. Bir mikrofon bağlayıp tekrar deneyin ya da dosya yükleyin.",
    "Mikrofon açılamadı; başka bir uygulama kullanıyor olabilir. Onu kapatıp tekrar deneyin ya da dosya yükleyin.",
    "Bu pencerede mikrofon kaydı kullanılamıyor. Dosya yükleyerek devam edin.",
    "Mikrofon açılamadı. Tekrar deneyin ya da dosya yükleyin.",
    "{sn} sn · en az 8 sn konuşun", "{sn} sn · süre uygun",
    "{sn} sn · 20 sn'yi geçti, kullanılacak aralığı sonra seçersiniz",
]
# Ses Klonlama → Referans ses (mikrofon, 1–30 sn; 3–15 önerilir).
CLONE_KEYS = [
    "Örnek sesi yükleyin ya da kaydedin",
    "Mikrofonla kaydetmek için kutunun altındaki mikrofon simgesine, sonra Kaydet'e basın. 3–15 saniye konuşup "
    "Durdur'a basın; dinleyin, beğenmezseniz silip yeniden kaydedin. Kayıt yalnız bu bilgisayarda kalır.",
    "{sn} sn · en az 1 sn gerekir", "{sn} sn · kabul edilir; 3–15 sn önerilir",
    "{sn} sn · kabul edilir; 3–15 sn daha iyi sonuç verir", "{sn} sn · 30 sn'yi geçti; silip daha kısa kaydedin",
]


def recorder_wav(path, speech_s, lead_s=0.6, tail_s=0.8):
    """Gradio kaydedicisinin yüklediği biçim: audio.wav, 44.1 kHz, stereo, 16-bit PCM; başta/sonda sessizlik."""
    t = np.arange(int(speech_s * SR)) / SR
    speech = (0.3 * np.sin(2 * np.pi * 180 * t) * (0.6 + 0.4 * np.sin(2 * np.pi * 3 * t))).astype(np.float32)
    mono = np.concatenate([np.zeros(int(lead_s * SR), np.float32), speech, np.zeros(int(tail_s * SR), np.float32)])
    sf.write(str(path), np.stack([mono, mono], axis=1), SR, subtype="PCM_16")
    return str(path)


def _demo():
    with patch.object(app.guncelleme.urllib.request, "urlopen", side_effect=AssertionError("ağ çağrıldı")):
        return app.build_app()


class MicPipelineTests(unittest.TestCase):
    """Mikrofon kaydı = dosya yükleme: aynı işlev, aynı çıktı, aynı kurallar."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.patches = [patch.object(app, "OUTPUT_DIR", self.tmp / "out"),
                        patch.object(vl, "VOICES_DIR", self.tmp / "voices")]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_mic_goes_through_the_same_preparation_as_a_file(self):
        mic = recorder_wav(self.tmp / "audio.wav", 12)
        dosya = self.tmp / "yuklenen.wav"
        shutil.copy(mic, dosya)
        with patch.object(app, "upload_analyze_ui", wraps=app.upload_analyze_ui) as ortak:
            m = app.mic_analyze_ui(mic)
            f = app.file_analyze_ui(str(dosya))
        self.assertEqual([c.args[0] for c in ortak.call_args_list], [mic, str(dosya)])  # tek ortak işlev
        self.assertEqual(len(m), 9)
        self.assertIsNone(m[-1])  # kayıt bitti → dosya kutusu boşalır
        self.assertIsNone(f[-1])  # dosya yüklendi → mikrofon kutusu boşalır
        self.assertEqual(m[3], f[3])  # aynı bilgi metni (süre, uyarılar, temizlik notu)
        a, sr_a = sf.read(m[1])
        b, sr_b = sf.read(f[1])
        self.assertEqual(sr_a, sr_b)
        np.testing.assert_array_equal(a, b)
        info = sf.info(m[1])
        self.assertEqual((info.channels, info.subtype), (1, "PCM_16"))  # mono 16-bit
        self.assertLess(info.duration, 12.6)  # baştaki/sondaki sessizlik kırpıldı (12 sn konuşma + 1,4 sn sessizlik)
        self.assertGreater(info.duration, 11.9)
        self.assertIn("mono, 16-bit", m[3])

    def test_duration_rule_short_and_long(self):
        kisa = app.mic_analyze_ui(recorder_wav(self.tmp / "audio.wav", 5))
        self.assertIn("en az 8 sn", kisa[3])
        self.assertFalse(kisa[4]["visible"])
        with self.assertRaisesRegex(app.gr.Error, "8–20 sn"):
            app.save_uploaded_ui(kisa[1], "Metin.", "Kısa", "", "", True)
        uzun = app.mic_analyze_ui(recorder_wav(self.tmp / "audio2.wav", 26))
        self.assertIn("en fazla 20 sn", uzun[3])
        self.assertTrue(uzun[4]["visible"])  # aralık kaydırıcıları açılır
        self.assertAlmostEqual(sf.info(uzun[1]).duration, audio_prep.MAX_SECONDS, places=2)
        kesit, _onizleme, _md = app.upload_cut_ui(uzun[0], 3, 15)
        self.assertAlmostEqual(sf.info(kesit).duration, 12, places=2)

    def test_empty_or_too_short_recording(self):
        bos = app.mic_analyze_ui(None)  # kayıt boş durdu / kutu temizlendi
        self.assertEqual(bos[:3], (None, None, None))
        # Yarım saniyelik ses + sessizlik: kırpılınca 1 sn'nin altında kalır (dosyadaki kuralın aynısı).
        kisa = recorder_wav(self.tmp / "audio.wav", 0.5, lead_s=1.5, tail_s=1.5)
        with self.assertRaisesRegex(app.gr.Error, "konuşma bulunamadı"):
            app.mic_analyze_ui(kisa)

    def test_consent_checkbox_is_still_required(self):
        m = app.mic_analyze_ui(recorder_wav(self.tmp / "audio.wav", 10))
        with self.assertRaisesRegex(app.gr.Error, "izin"):
            app.save_uploaded_ui(m[1], "Merhaba bu benim sesim.", "Mikrofon Sesim", "", "", False)
        _v, vid, _t, _msg = app.save_uploaded_ui(m[1], "Merhaba bu benim sesim.", "Mikrofon Sesim", "", "", True)
        ses = vl.get_voice(vid)
        self.assertEqual(ses["kaynak"], "yüklendi")  # gerçek kişi sesi: hazir/ altına yazılamaz
        self.assertFalse(ses["hazir"])


class MicUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.demo = _demo()
        cls.comps = cls.demo.config["components"]
        cls.by_id = {c["id"]: c for c in cls.comps}

    def _mics(self):
        return [c for c in self.comps if c["type"] == "audio" and "sv-mic" in (c["props"].get("elem_classes") or [])
                and "sv-mic-ref" not in c["props"]["elem_classes"]]

    def _refs(self):
        return [c for c in self.comps if c["type"] == "audio" and "sv-mic-ref" in (c["props"].get("elem_classes") or [])]

    def test_recorder_on_every_language_page(self):
        mics = self._mics()
        self.assertEqual(len(mics), len(i18n.LANGUAGES))
        for c in mics:
            p = c["props"]
            self.assertEqual(p["sources"], ["microphone"])
            self.assertFalse(p["editable"])
            self.assertNotIn("share", p.get("buttons") or [])  # kayıt hiçbir yere yüklenmez
            self.assertIsNone(p.get("format"))  # sunucuda ikinci dönüştürme (ffmpeg) yok
        self.assertIn("Mikrofon kaydı", {c["props"]["label"] for c in mics})
        self.assertIn("Microphone recording", {c["props"]["label"] for c in mics})

    def test_events_share_the_file_pipeline(self):
        mic_ids = {c["id"] for c in self._mics()}
        files = {c["id"] for c in self.comps if c["type"] == "file" and "sv-file" in (c["props"].get("elem_classes") or [])
                 and c["props"].get("file_types") == [".wav", ".mp3", ".m4a"]}
        stop = [f for f in self.demo.fns.values() if any(t[0] in mic_ids and t[1] == "stop_recording" for t in f.targets)]
        self.assertEqual(len(stop), len(i18n.LANGUAGES))
        for f in stop:
            self.assertIs(f.fn, app.mic_analyze_ui)
            self.assertTrue({o._id for o in f.outputs} & files)  # kayıt bitince dosya kutusu boşalır
        clear = [f for f in self.demo.fns.values() if any(t[0] in mic_ids and t[1] == "clear" for t in f.targets)]
        self.assertEqual(len(clear), len(i18n.LANGUAGES))
        up = [f for f in self.demo.fns.values() if any(t[0] in files and t[1] == "upload" for t in f.targets)]
        self.assertEqual(len(up), len(i18n.LANGUAGES))
        for f in up:
            self.assertIs(f.fn, app.file_analyze_ui)
            self.assertTrue({o._id for o in f.outputs} & mic_ids)

    def test_status_messages_are_in_the_page_language(self):
        htmls = [str(c["props"].get("value")) for c in self.comps if c["type"] == "html"]
        durum = [h for h in htmls if "sv-mic-status-yukle" in h]
        self.assertEqual(len(durum), len(i18n.LANGUAGES))
        tr = next(h for h in durum if "Mikrofon izni verilmedi" in h)
        en = next(h for h in durum if "Microphone permission was not given" in h)
        for h in (tr, en):
            for anahtar in ("wait", "denied-mac", "denied-win", "denied-browser", "nodevice", "busy", "unsupported",
                            "error", "short", "ok", "long", "steps", "scale"):
                self.assertRegex(h, rf'data-{anahtar}="[^"]+"')
            self.assertIn("{sn}", h)
        self.assertIn("Sistem Ayarları &gt; Gizlilik ve Güvenlik &gt; Mikrofon", tr)
        self.assertIn("System Settings &gt; Privacy &amp; Security &gt; Microphone", en)

    def test_js_maps_errors_to_messages(self):
        js = app._JS
        self.assertIn(app._MIC_JS.strip()[:60], js)
        for ad, anahtar in (("NotAllowedError", "deniedKey()"), ("NotFoundError", "'nodevice'"),
                            ("NotReadableError", "'busy'")):
            satir = next(s for s in app._MIC_JS.splitlines() if ad in s)
            self.assertIn(anahtar, satir)
        self.assertIn("window.pywebview", app._MIC_JS)  # pencere / tarayıcı ayrımı

    def test_new_texts_translated_without_em_dash(self):
        kaynak = json.loads((ROOT / "locales" / "_kaynak.json").read_text(encoding="utf-8"))
        for k in MIC_KEYS:
            self.assertIn(k, kaynak)
            self.assertNotIn("\u2014", k)
        for lang in i18n.LANGUAGES:
            if lang == i18n.DEFAULT:
                continue
            d = json.loads((ROOT / "locales" / f"{lang}.json").read_text(encoding="utf-8"))
            for k in MIC_KEYS:
                with self.subTest(dil=lang, anahtar=k[:30]):
                    self.assertTrue(d.get(k, "").strip())
                    self.assertNotIn("\u2014", d[k])
                    self.assertEqual(re.findall(r"\{[^{}]*\}", k), re.findall(r"\{[^{}]*\}", d[k]))
        for h in (app._mic_intro_html(), app._mic_status_html()):
            self.assertNotIn("\u2014", h)


@unittest.skipUnless(shutil.which("node"), "node yok")
class MicJsBehaviourTests(unittest.TestCase):
    """_MIC_JS gerçek JavaScript olarak çalışır (node, en küçük DOM taklidi): izin reddi iletisi,
    cihaz yok, bekleme ipucu ve süre göstergesi."""

    HARNESS = r"""
const MIC_JS = %s;
const scenario = %s;
const listeners = {};
const msg = {textContent: ''};
const bar = {style: {}};
const time = {textContent: ''};
const meter = {hidden: true, dataset: {}, classList: {toggle() {}},
               querySelector: (s) => (s === '.sv-mic-bar i' ? bar : time)};
const box = {dataset: Object.assign({wait: 'WAIT', deniedMac: 'MAC', deniedWin: 'WIN', deniedBrowser: 'BROWSER',
                       nodevice: 'NODEV', busy: 'BUSY', unsupported: 'UNSUP', error: 'ERR',
                       short: '{sn} kisa', ok: '{sn} uygun', long: '{sn} uzun'}, scenario.data || {}),
             classList: {toggle() {}}, querySelector: (s) => (s === '.sv-mic-msg' ? msg : meter)};
// Sayfada önce başka bir alanın kutusu var (belge sırasında kaydediciden önce): ona yazılmamalı.
const other = {dataset: {}, classList: {toggle() { throw new Error('yanlış kutu'); }},
               querySelector() { throw new Error('yanlış kutu'); }};
const mic = {querySelector: () => null, compareDocumentPosition: (n) => (n === box ? 4 : 2)};
let clock = 0;
globalThis.performance = {now: () => clock};
globalThis.window = scenario.pywebview ? {pywebview: {}} : {};
const track = {stop() {}};
let resolveGum;
const md = scenario.noMedia ? undefined : {getUserMedia: () => new Promise((res, rej) => {
  if (scenario.error) rej(Object.assign(new Error('x'), {name: scenario.error}));
  else resolveGum = () => res({getTracks: () => [track]});
})};
Object.defineProperty(globalThis, 'navigator', {value: {mediaDevices: md, platform: scenario.platform,
  userAgent: scenario.platform}, configurable: true});
globalThis.document = {querySelectorAll: (s) => (s === '.sv-mic-status' ? [other, box] : []),
  addEventListener: (t, f) => { listeners[t] = f; }, documentElement: {lang: 'tr'}};
const inMic = (sel) => ({closest: (q) => (q === '.sv-mic' ? mic : (q === sel ? {} : null))});
(0, eval)(MIC_JS);
(async () => {
  const out = {};
  listeners.click({target: inMic('.record-button')});
  if (scenario.noMedia) { out.msg = msg.textContent; console.log(JSON.stringify(out)); process.exit(0); }
  const p = navigator.mediaDevices.getUserMedia({audio: true}).catch((e) => { out.thrown = e.name; });
  if (!scenario.error) {
    await new Promise((r) => setTimeout(r, 1700));
    out.waiting = msg.textContent;
    clock = 9300; resolveGum(); await p;
    await new Promise((r) => setTimeout(r, 150));
    out.live = time.textContent; out.meterHidden = meter.hidden; out.width = bar.style.width;
    clock = 9300 + (scenario.recordMs || 14100); track.stop();
    out.final = time.textContent; out.state = meter.dataset.state; out.tone = meter.dataset.tone;
    out.finalWidth = bar.style.width;
  } else { await p; }
  out.msg = msg.textContent;
  console.log(JSON.stringify(out));
  process.exit(0);
})();
"""

    def run_js(self, **scenario):
        code = self.HARNESS % (json.dumps(app._MIC_JS), json.dumps(scenario))
        r = subprocess.run(["node", "-"], input=code, capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout.strip().splitlines()[-1])

    def test_denied_in_mac_window(self):
        out = self.run_js(error="NotAllowedError", pywebview=True, platform="MacIntel")
        self.assertEqual(out, {"thrown": "NotAllowedError", "msg": "MAC"})  # hata Gradio'ya da iletilir

    def test_denied_in_windows_window_and_browser(self):
        self.assertEqual(self.run_js(error="NotAllowedError", pywebview=True, platform="Win32")["msg"], "WIN")
        self.assertEqual(self.run_js(error="NotAllowedError", pywebview=False, platform="MacIntel")["msg"], "BROWSER")

    def test_no_device_busy_and_unsupported(self):
        self.assertEqual(self.run_js(error="NotFoundError", platform="Win32")["msg"], "NODEV")
        self.assertEqual(self.run_js(error="NotReadableError", platform="Win32")["msg"], "BUSY")
        self.assertEqual(self.run_js(noMedia=True, platform="MacIntel")["msg"], "UNSUP")

    def test_wait_hint_then_live_duration(self):
        out = self.run_js(platform="MacIntel", pywebview=True)
        self.assertEqual(out["waiting"], "WAIT")  # izin penceresi beklenirken
        self.assertEqual(out["msg"], "")  # izin gelince ileti kalkar
        self.assertFalse(out["meterHidden"])
        self.assertEqual(out["final"], "14.1 uygun")  # 9.3 sn'de başladı, 23.4 sn'de durdu
        self.assertEqual(out["state"], "ok")

    def test_clone_reference_uses_its_own_duration_rule(self):
        # Ses Klonlama referansı: kurallar kutunun data-steps / data-scale özniteliklerinden (1–30 sn, 3–15 önerilir).
        html = app._mic_status_html("klon")
        steps = json.loads(re.search(r'data-steps="([^"]+)"', html).group(1).replace("&quot;", '"'))
        data = {"steps": json.dumps(steps), "scale": re.search(r'data-scale="([^"]+)"', html).group(1),
                "cshort": "{sn} 1alti", "cbrief": "{sn} kisa", "ok": "{sn} uygun", "clong": "{sn} uzun",
                "cover": "{sn} fazla"}
        beklenen = {500: ("0.5 1alti", "short"), 2000: ("2.0 kisa", "short"), 9000: ("9.0 uygun", "ok"),
                    22000: ("22.0 uzun", "long"), 31000: ("31.0 fazla", "over")}
        for ms, (metin, ton) in beklenen.items():
            with self.subTest(ms=ms):
                out = self.run_js(platform="Win32", pywebview=True, data=data, recordMs=ms)
                self.assertEqual((out["final"], out["tone"]), (metin, ton))
        self.assertEqual(self.run_js(platform="Win32", data=data, recordMs=40000)["finalWidth"], "100.0%")


class CloneReferenceMicTests(unittest.TestCase):
    """Ses Klonlama → Referans ses: aynı bileşende dosya ya da mikrofon; kayıt dosyayla aynı denetimden
    (1–30 sn) ve aynı yazıya dökmeden geçer. Model yüklenmez (get_model / Whisper taklit)."""

    @classmethod
    def setUpClass(cls):
        cls.demo = _demo()
        cls.comps = cls.demo.config["components"]

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _refs(self):
        return [c for c in self.comps if c["type"] == "audio" and "sv-mic-ref" in (c["props"].get("elem_classes") or [])]

    def test_reference_offers_upload_and_microphone_on_every_page(self):
        refs = self._refs()
        self.assertEqual(len(refs), len(i18n.LANGUAGES))
        for c in refs:
            p = c["props"]
            self.assertEqual(p["sources"], ["upload", "microphone"])  # dosya varsayılan, mikrofon ikinci
            self.assertEqual(p["type"], "filepath")
            self.assertNotIn("share", p.get("buttons") or [])
            self.assertIsNone(p.get("format"))  # kayıt tarayıcıda WAV olur; sunucuda ikinci dönüştürme yok
        self.assertIn("Referans ses (gerekli)", {c["props"]["label"] for c in refs})
        htmls = [str(c["props"].get("value")) for c in self.comps if c["type"] == "html"]
        durum = [h for h in htmls if "sv-mic-status-klon" in h]
        self.assertEqual(len(durum), len(i18n.LANGUAGES))
        tr = next(h for h in durum if "Mikrofon izni verilmedi" in h)
        for anahtar in ("wait", "denied-mac", "denied-win", "denied-browser", "nodevice", "busy", "unsupported",
                        "error", "cshort", "cbrief", "ok", "clong", "cover", "steps", "scale"):
            self.assertRegex(tr, rf'data-{anahtar}="[^"]+"')
        self.assertIn("en az 1 sn", tr)
        self.assertIn("30 sn", tr)
        notlar = [h for h in htmls if "sv-mic-note" in h]
        self.assertEqual(len(notlar), len(i18n.LANGUAGES))
        self.assertTrue(any("Kayıt yalnız bu bilgisayarda kalır." in h for h in notlar))

    def test_clone_rule_matches_server_limits(self):
        steps = app._MIC_RULES["klon"]["steps"]
        self.assertEqual(steps[0][0], 1)  # generate_audio: 1 <= süre
        self.assertAlmostEqual(steps[-2][0], 30, delta=0.1)  # süre <= 30
        self.assertEqual(app._MIC_RULES["klon"]["band"], (3, 15))  # önerilen
        self.assertEqual(app._MIC_RULES["yukle"]["band"], (audio_prep.MIN_SECONDS, audio_prep.MAX_SECONDS))

    def test_transcribe_button_reads_the_same_reference(self):
        ref_ids = {c["id"] for c in self._refs()}
        tr = [f for f in self.demo.fns.values() if f.fn is app.auto_transcribe]
        self.assertEqual(len(tr), len(i18n.LANGUAGES))
        for f in tr:
            self.assertEqual(len(f.inputs), 1)
            self.assertIn(f.inputs[0]._id, ref_ids)  # dosya da kayıt da aynı değer
        uret = [f for f in self.demo.fns.values() if getattr(f.fn, "__name__", "") == "_clone_generate"
                or getattr(getattr(f.fn, "__wrapped__", None), "__name__", "") == "_clone_generate"]
        for f in uret:
            self.assertIn(f.inputs[1]._id, ref_ids)

    def test_recording_is_checked_like_a_file(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        model = SimpleNamespace(tts_model=SimpleNamespace(sample_rate=48000), generate=Mock(return_value=np.zeros(4800)))
        uygun = recorder_wav(self.tmp / "audio.wav", 8)  # Gradio kaydı: 44.1 kHz stereo 16-bit
        dosya = self.tmp / "yuklenen.wav"
        shutil.copy(uygun, dosya)
        with patch.object(app, "OUTPUT_DIR", self.tmp / "out"), patch.object(app, "get_model", return_value=model):
            for ref in (uygun, str(dosya)):
                list(app._clone_generate("Merhaba.", ref, "Nötr", None))
                self.assertEqual(model.generate.call_args.kwargs.get("reference_wav_path"), ref)
        for sn, lead, tail in ((31, 0.6, 0.8), (0.4, 0.1, 0.1)):  # 30 sn üstü / 1 sn altı: ikisi de aynı ret
            kayit = recorder_wav(self.tmp / f"audio-{sn}.wav", sn, lead_s=lead, tail_s=tail)
            kopya = self.tmp / f"dosya-{sn}.wav"
            shutil.copy(kayit, kopya)
            for ref in (kayit, str(kopya)):
                with self.subTest(sn=sn, ref=Path(ref).name), patch.object(app, "get_model") as load:
                    with self.assertRaisesRegex(app.gr.Error, "1–30 saniyelik"):
                        list(app._clone_generate("Merhaba.", ref, "Nötr", None))
                    load.assert_not_called()
                    with self.assertRaisesRegex(app.gr.Error, "1–30 saniyelik"):
                        app.kuyruga_ekle_klon_ui("Merhaba.", ref, "Nötr", "")

    def test_auto_transcribe_runs_on_the_recording(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        kayit = recorder_wav(self.tmp / "audio.wav", 5)
        whisper = Mock(transcribe=Mock(return_value=([SimpleNamespace(text=" Bu benim sesim. ")], None)))
        with patch.object(app, "_get_whisper", return_value=whisper):
            self.assertEqual(app.auto_transcribe(kayit), "Bu benim sesim.")
        self.assertEqual(whisper.transcribe.call_args.args[0], kayit)  # kaydın kendisi, değişmeden

    def test_clone_texts_translated_without_em_dash(self):
        kaynak = json.loads((ROOT / "locales" / "_kaynak.json").read_text(encoding="utf-8"))
        self.assertNotIn("Örnek sesi yükleyin", kaynak)  # yerine "... ya da kaydedin"
        for k in CLONE_KEYS:
            self.assertIn(k, kaynak)
            self.assertNotIn("\u2014", k)
        for lang in i18n.LANGUAGES:
            if lang == i18n.DEFAULT:
                continue
            d = json.loads((ROOT / "locales" / f"{lang}.json").read_text(encoding="utf-8"))
            for k in CLONE_KEYS:
                with self.subTest(dil=lang, anahtar=k[:30]):
                    self.assertTrue(d.get(k, "").strip())
                    self.assertNotIn("\u2014", d[k])
                    self.assertEqual(re.findall(r"\{[^{}]*\}", k), re.findall(r"\{[^{}]*\}", d[k]))
        for lang in ("tr", "en", "ar"):
            with i18n.use(lang):
                for h in (app._clone_mic_hint_html(), app._mic_status_html("klon")):
                    self.assertNotIn("\u2014", h)


class MacPackagingTests(unittest.TestCase):
    def test_info_plist_has_microphone_usage(self):
        with open(ROOT / "SesVer.app" / "Contents" / "Info.plist", "rb") as f:
            info = plistlib.load(f)
        metin = info["NSMicrophoneUsageDescription"]
        self.assertIn("mikrofon", metin)
        self.assertIn("microphone", metin)
        self.assertNotIn("\u2014", metin)
        # DMG paketinde silinen anahtarlar yalnız klasör izinleri; mikrofon metni kalır.
        rel = (ROOT / "macos" / "release_mac.sh").read_text(encoding="utf-8")
        silinen = rel.split("for k in ")[1].split("; do")[0]
        self.assertNotIn("NSMicrophoneUsageDescription", silinen)
        self.assertIn('cp "$SRC/SesVer.app/Contents/Info.plist"', rel)

    def test_entitlements_only_audio_input(self):
        with open(ROOT / "macos" / "SesVer.entitlements", "rb") as f:
            ent = plistlib.load(f)
        self.assertEqual(ent, {"com.apple.security.device.audio-input": True})
        doc = (ROOT / "docs" / "macos-yayin.md").read_text(encoding="utf-8")
        self.assertIn("requires entitlement com.apple.security.device.audio-input but it is missing", doc)


class WindowsCiSmokeTests(unittest.TestCase):
    """windows-installer.yml: mikrofon duman testi ayrı bir job; başarısızlık kırmızı, yayın akışı aynı."""

    @classmethod
    def setUpClass(cls):
        import yaml
        cls.wf = yaml.safe_load((ROOT / ".github" / "workflows" / "windows-installer.yml").read_text(encoding="utf-8"))

    def test_job_runs_the_tool_in_the_real_window_with_fake_device(self):
        job = self.wf["jobs"]["mikrofon-duman"]
        self.assertEqual(job["runs-on"], "windows-latest")
        self.assertEqual(job["permissions"], {"contents": "read"})
        adim = next(s for s in job["steps"] if s.get("name", "").startswith("Mikrofon kaydı duman testi"))
        self.assertNotIn("continue-on-error", adim)
        self.assertNotIn("continue-on-error", job)
        bayrak = adim["env"]["SV_CI_WEBVIEW2_BAYRAKLARI"]
        for b in ("--remote-debugging-port=9222", "--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"):
            self.assertIn(b, bayrak)
        run = adim["run"]
        self.assertIn("-ArgumentList '-E', '-s', 'desktop.py'", run)  # tarayıcı değil, kısayolla aynı gerçek pencere
        self.assertIn(r"python-embed\pythonw.exe", run)
        self.assertIn(r"tools\mikrofon_duman.py --cdp http://127.0.0.1:9222 --uygulama http://127.0.0.1:7860", run)
        self.assertIn("--bekle 300 --cdp-bekle 90", run)  # açılmazsa 5 dk, açıldıysa port için 90 sn
        self.assertNotIn("--alan", run)  # varsayılan "hepsi": Ses Oluştur ve Ses Klonlama birlikte
        self.assertIn("if ($kod -ne 0) { throw", run)
        self.assertIn("[Console]::OutputEncoding = [System.Text.Encoding]::UTF8", run)

    def test_webview2_flags_go_through_hklm_policy_because_the_runner_is_elevated(self):
        # 1.4.2'nin ikinci CI koşusu: WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS ortam değişkeniyle 9222
        # hiç açılmadı. GitHub'ın Windows makineleri yönetici (UAC kapalı) çalışır; WebView2 150+
        # yükseltilmiş süreçte WEBVIEW2_* değişkenlerini yok sayar, HKLM ilkesini okur
        # (MicrosoftEdge/WebView2Feedback#5640). Biçim: ...\WebView2\AdditionalBrowserArguments
        # anahtarı, değer adı ana sürecin dosya adı (CreateCoreWebView2EnvironmentWithOptions).
        adim = next(s for s in self.wf["jobs"]["mikrofon-duman"]["steps"]
                    if s.get("name", "").startswith("Mikrofon kaydı duman testi"))
        run = adim["run"]
        self.assertIn(r"'HKLM:\SOFTWARE\Policies\Microsoft\Edge\WebView2\AdditionalBrowserArguments'", run)
        self.assertIn("New-ItemProperty -Path $pol -Name 'pythonw.exe' -PropertyType String "
                      "-Value $env:SV_CI_WEBVIEW2_BAYRAKLARI", run)
        self.assertNotIn("-Name '*'", run)  # yalnız SesVer'in süreci, bütün WebView2 uygulamaları değil
        # İlke SesVer başlatılmadan önce yazılır; tanı (bütünlük düzeyi, WebView2 sürümü, ana sürecin
        # komut satırı, 9222) kanıt dosyasına girer.
        self.assertLess(run.index("New-ItemProperty"), run.index("Start-Process -FilePath $pyw"))
        for tani in ("whoami /groups", "EdgeUpdate\\Clients\\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}",
                     "Name='msedgewebview2.exe'", "Get-NetTCPConnection -LocalPort 9222",
                     "sesver-mikrofon-tani.txt"):
            self.assertIn(tani, run)
        # Ortam değişkeni yolu kalmadı (yükseltilmiş süreçte etkisiz, yanıltıcı olur).
        self.assertNotIn("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", json.dumps(adim.get("env", {})))

    def test_exit_codes_are_explained_and_powershell_strings_parse(self):
        adim = next(s for s in self.wf["jobs"]["mikrofon-duman"]["steps"]
                    if s.get("name", "").startswith("Mikrofon kaydı duman testi"))
        run = adim["run"]
        for kod in ("1 {", "2 {", "4 {", "5 {"):
            self.assertIn(kod, run)
        # "...$kod: ..." PowerShell'de sürücü önekli değişken sanılır ve betik ayrıştırılamaz
        # (810d368'deki surum notu hatası); çift tırnak içinde $ad: yalnız ${ad}: biçiminde.
        for satir in run.splitlines():
            for parca in re.findall(r'"[^"]*"', satir):
                self.assertNotRegex(parca, r"\$(?!env:|global:|script:)[A-Za-z_]\w*:", satir)

    def test_environment_is_installed_by_the_real_launcher(self):
        # 1.4.2'nin ilk CI koşusu, iş bat'taki kurulumu elle kopyaladığı ve torch-pypi'yi --no-deps'siz
        # kurduğu için düştü. Artık kurulum yalnız WINDOWS_BASLAT.bat /yalniz-kurulum ile yapılır:
        # job'da paket listesi, pip bayrağı ya da ayrı Python yoktur (kopya kalmadı, sapma olamaz).
        job = self.wf["jobs"]["mikrofon-duman"]
        adlar = [s.get("name", "") for s in job["steps"]]
        kur_i = next(i for i, a in enumerate(adlar) if a.startswith("SesVer ortamını kur"))
        duman_i = next(i for i, a in enumerate(adlar) if a.startswith("Mikrofon kaydı duman testi"))
        self.assertLess(kur_i, duman_i)
        kur = job["steps"][kur_i]
        self.assertNotIn("continue-on-error", kur)
        run = kur["run"]
        self.assertIn(r'WINDOWS_BASLAT.bat`"", ' + "'/yalniz-kurulum'", run)
        self.assertIn("$durum -notlike '*|tamam'", run)  # bat'ın son durum satırı (sihirbazla aynı biçim)
        self.assertIn(r"python-embed\sesver_kurulum_tamam.txt", run)
        self.assertIn(r"tools\mikrofon_duman.py --paket-denetimi", run)
        tum = "\n".join(s.get("run", "") for s in job["steps"])
        for yasak in ("pip install", "--require-hashes", "--no-deps", "kilit\\", "RUNNER_TOOL_CACHE", ".venv"):
            self.assertNotIn(yasak, tum)

    def test_launcher_first_install_order_and_flags(self):
        # CI artık bat'a güvendiği için bat'ın sırası ve bayrakları burada sabitlenir: pip, torch ve
        # voxcpm --no-deps (torch'un filelock vb. bağımlılıkları temel kilitte hash'li gelir;
        # --no-deps olmadan --require-hashes "versions pinned" hatasıyla düşer), temel kilit en son.
        bat = (ROOT / "WINDOWS_BASLAT.bat").read_text(encoding="utf-8").replace("\r\n", "\n")

        def kurulumlar(bas, son):
            blok = bat.split(f"\n{bas}\n", 1)[1].split(f"\n{son}\n", 1)[0]
            ek, out = None, []
            for satir in blok.splitlines():
                m = re.match(r'set "?SV_EK=([^"]*)"?$', satir.strip())
                if m:
                    ek = m.group(1)
                m = re.match(r'call :kilitli_kur "([^"]+)"$', satir.strip())
                if m:
                    out.append((m.group(1), ek))
            return out

        self.assertEqual(kurulumlar(":ilk_kurulum", ":kurulum_bitti"), [
            (r"kilit\pip.txt", "--no-deps"),
            (r"kilit\torch-%CUDA_ETIKET%.txt", "--no-deps"),
            (r"kilit\torch-pypi.txt", "--no-deps"),
            (r"kilit\voxcpm.txt", "--no-deps"),
            ("%TEMEL_KILIT%", ""),
        ])
        self.assertEqual(kurulumlar(":esitle", ":esitle_hata"), [
            (r"kilit\pip.txt", "--no-deps"),
            ("%TORCH_KILIT%", "--no-deps"),
            (r"kilit\voxcpm.txt", "--no-deps"),
            ("%TEMEL_KILIT%", "%SV_KISIT%"),
        ])
        self.assertIn('set "KILIT_PIP=--require-hashes --only-binary=:all:', bat)
        self.assertIn('"%PYEXE%" -m pip install %KILIT_PIP% %SV_EK% -r "%~1"', bat)

    def test_package_check_lists_what_the_smoke_test_needs(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("mikrofon_duman_pk", ROOT / "tools" / "mikrofon_duman.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        # Pencere (pywebview + WebView2 köprüsü pythonnet), arayüz, ses, yazıya dökme ve model paketleri.
        for ad in ("gradio", "numpy", "soundfile", "scipy", "webview", "pythonnet", "faster_whisper", "torch", "voxcpm"):
            self.assertIn(ad, mod.GEREKLI_PAKETLER)
        self.assertEqual(mod.eksik_paketler(("json", "boyle_bir_paket_yok_sv")), ["boyle_bir_paket_yok_sv"])
        kilit = (ROOT / "kilit" / "windows-x64-py311.txt").read_text(encoding="utf-8")
        for paket in ("gradio==", "numpy==", "soundfile==", "scipy==", "pywebview==", "pythonnet==",
                      "faster-whisper=="):
            self.assertRegex(kilit, rf"(?m)^{re.escape(paket)}")  # Windows temel kilidinde gerçekten var
        self.assertRegex((ROOT / "kilit" / "torch-pypi.txt").read_text(encoding="utf-8"), r"(?m)^torch==")
        self.assertRegex((ROOT / "kilit" / "voxcpm.txt").read_text(encoding="utf-8"), r"(?m)^voxcpm==")

    def test_release_and_existing_jobs_unchanged(self):
        self.assertEqual(self.wf["jobs"]["release"]["needs"], "build")
        self.assertEqual(set(self.wf["jobs"]), {"build", "release", "full-launch", "mikrofon-duman"})
        self.assertNotIn("needs", self.wf["jobs"]["mikrofon-duman"])

    def test_tool_uses_only_the_standard_library(self):
        # Kilitli Windows paket listesinde WebSocket kütüphanesi yok; araç ek paket istememeli.
        import ast
        kaynak = (ROOT / "tools" / "mikrofon_duman.py").read_text(encoding="utf-8")
        modul = set()
        for n in ast.walk(ast.parse(kaynak)):
            if isinstance(n, ast.Import):
                modul |= {a.name.split(".")[0] for a in n.names}
            elif isinstance(n, ast.ImportFrom):
                modul.add(n.module.split(".")[0])
        self.assertLessEqual(modul, set(sys.stdlib_module_names))

    def test_websocket_client_roundtrip(self):
        import importlib.util
        import socket
        import struct
        spec = importlib.util.spec_from_file_location("mikrofon_duman", ROOT / "tools" / "mikrofon_duman.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        # Klon referansı denetimi: sunucudan inen kaydın süresi, sunucunun 1–30 sn sınırıyla.
        with tempfile.TemporaryDirectory() as d:
            veri = Path(recorder_wav(Path(d) / "audio.wav", 10)).read_bytes()
        sure, kanal, genislik = mod.wav_bilgisi(veri)
        self.assertAlmostEqual(sure, 11.4, places=2)
        self.assertEqual((kanal, genislik), (2, 2))
        self.assertEqual((mod.KLON_MIN, mod.KLON_MAX), (1.0, 30.0))
        with self.assertRaises(ValueError):
            mod.wav_bilgisi(b"RIFF bozuk")
        with self.assertRaises(ValueError):  # kayıt yalnız yerel sunucudan indirilir
            mod._yerel_indir("http://example.com/gradio_api/file=/x.wav")
        with self.assertRaises(ValueError):  # yalnız yerel adres
            mod.WebSocket("ws://example.com:9222/devtools/page/x")
        a, b = socket.socketpair()
        ws = object.__new__(mod.WebSocket)
        ws.sock = a
        a.settimeout(20)
        b.settimeout(20)
        ws.send('{"id": 1}')
        b1, b2 = b.recv(2)
        self.assertEqual(b1, 0x81)
        self.assertTrue(b2 & 0x80)  # istemci çerçevesi maskeli
        n = b2 & 0x7F
        mask = b.recv(4)
        veri = bytes(x ^ mask[i % 4] for i, x in enumerate(b.recv(n)))
        self.assertEqual(veri, b'{"id": 1}')
        uzun = ("x" * 70000).encode()

        def gonder():  # soket tamponu küçük: sunucu tarafı ayrı thread'den yazar
            b.sendall(bytes([0x89, 0]))  # ping → pong yanıtlanır, atlanır
            b.sendall(bytes([0x01, 126]) + struct.pack("!H", 3) + b"abc")  # parçalı ileti, 1. parça
            b.sendall(bytes([0x80, 127]) + struct.pack("!Q", len(uzun)) + uzun)  # devam, son parça

        import threading
        th = threading.Thread(target=gonder, daemon=True)
        th.start()
        a.settimeout(20)
        self.assertEqual(ws.recv(), "abc" + "x" * 70000)
        th.join(20)
        b.settimeout(20)
        self.assertEqual(b.recv(2), bytes([0x8A, 0x80]))  # pong, boş, maskeli
        a.close()
        b.close()


def _duman_modulu(ad="mikrofon_duman_t"):
    import importlib.util
    spec = importlib.util.spec_from_file_location(ad, ROOT / "tools" / "mikrofon_duman.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# Son kullanıcıda WebView2'ye uzaktan hata ayıklama portu ya da sahte medya açtırabilecek her şey.
CI_BAYRAKLARI = ("remote-debugging", "REMOTE_DEBUGGING_PORT", "use-fake-device-for-media-stream",
                 "use-fake-ui-for-media-stream", "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS",
                 "AdditionalBrowserArguments", "SV_CI_WEBVIEW2_BAYRAKLARI", "open_devtools", "debug=True")


class NoDebugPortOutsideCiTests(unittest.TestCase):
    """Siberguvenlik: CDP portu ve sahte medya yalnız CI duman adımında; kurulan SesVer'de asla."""

    def _dagitilan_dosyalar(self):
        # windows/SesVer.iss ve macos/release_mac.sh'in kopyaladığı kod: kökteki *.py, engines/*.py,
        # başlatıcılar ve Mac paketinin kendi dosyaları (tools/ ve tests/ dağıtılmaz).
        yollar = sorted(ROOT.glob("*.py")) + sorted((ROOT / "engines").glob("*.py"))
        yollar += [ROOT / "WINDOWS_BASLAT.bat", ROOT / "windows" / "SesVer.iss",
                   ROOT / "macos" / "release_mac.sh", ROOT / "macos" / "build_app_launcher.sh",
                   ROOT / "macos" / "sesver_app_launcher.c",
                   ROOT / "SesVer.app" / "Contents" / "Resources" / "sesver_app.sh"]
        return [p for p in yollar if p.is_file()]

    def test_shipped_code_never_sets_debug_port_or_fake_media(self):
        dosyalar = self._dagitilan_dosyalar()
        self.assertIn(ROOT / "desktop.py", dosyalar)
        self.assertIn(ROOT / "app.py", dosyalar)
        for p in dosyalar:
            metin = p.read_text(encoding="utf-8", errors="replace")
            for b in CI_BAYRAKLARI:
                self.assertNotIn(b, metin, f"{p.relative_to(ROOT)}: {b}")
        # Dağıtım listeleri tools/ klasörünü (duman aracı) içermez.
        iss = (ROOT / "windows" / "SesVer.iss").read_text(encoding="utf-8")
        self.assertFalse([s for s in iss.splitlines() if s.startswith("Source:") and "tools" in s])
        mac = (ROOT / "macos" / "release_mac.sh").read_text(encoding="utf-8")
        self.assertNotRegex(mac, r"cp [^\n]*tools/")

    def test_window_starts_without_debug_even_if_ci_variable_is_set(self):
        import desktop
        import webview
        ortam = {"SV_CI_WEBVIEW2_BAYRAKLARI": "--remote-debugging-port=9222 --use-fake-device-for-media-stream"}
        eski = dict(webview.settings.items())  # pywebview'in sözlüğü yeni anahtar kabul etmez: elle geri yükle
        try:
            with patch.dict("os.environ", ortam), \
                    patch.object(desktop, "_check_webview_backend"), \
                    patch.object(webview, "create_window") as cw, patch.object(webview, "start") as st:
                desktop._run_window(object())
                self.assertIsNone(webview.settings["REMOTE_DEBUGGING_PORT"])
                self.assertFalse(webview.settings["OPEN_DEVTOOLS_IN_DEBUG"] and st.call_args.kwargs.get("debug"))
                self.assertNotIn("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", __import__("os").environ)
        finally:
            for k, v in eski.items():
                webview.settings[k] = v
        cw.assert_called_once()
        st.assert_called_once()
        self.assertFalse(st.call_args.kwargs.get("debug", False))
        self.assertNotIn("debug", cw.call_args.kwargs)

    def test_flags_only_in_the_ci_smoke_step(self):
        import yaml
        wf = yaml.safe_load((ROOT / ".github" / "workflows" / "windows-installer.yml").read_text(encoding="utf-8"))
        self.assertFalse(any(b in json.dumps(wf.get("env", {})) for b in CI_BAYRAKLARI))
        bulunan = []
        for jad, job in wf["jobs"].items():
            self.assertFalse(any(b in json.dumps(job.get("env", {})) for b in CI_BAYRAKLARI), jad)
            for s in job.get("steps", []):
                metin = json.dumps(s, ensure_ascii=False)
                if any(b in metin for b in ("remote-debugging", "use-fake-", "Edge\\\\WebView2")):
                    bulunan.append((jad, s.get("name", "")))
        self.assertEqual(bulunan, [("mikrofon-duman", "Mikrofon kaydı duman testi (WebView2 sahte cihaz, tools/mikrofon_duman.py)")])


class SmokeToolWaitAndOutputTests(unittest.TestCase):
    """tools/mikrofon_duman.py: duvar saatiyle bekleme, açık çıkış kodları, cp1252 konsolda çökmeme."""

    @classmethod
    def setUpClass(cls):
        cls.mod = _duman_modulu()

    def _bekle(self, cdp_yanit, uygulama_acilis=None, uygulama="http://127.0.0.1:7860", **kw):
        saat = [0.0]

        def simdi():
            saat[0] += 1.0  # her tur ~1 sn (Windows'ta kapalı porta bağlantı ~2 sn de sürebilir)
            return saat[0]

        with patch.object(self.mod, "_cdp_sekmesi", side_effect=lambda cdp: cdp_yanit(saat[0])), \
                patch.object(self.mod, "_yanit_veriyor",
                             side_effect=lambda u: uygulama_acilis is not None and saat[0] >= uygulama_acilis), \
                patch("builtins.print"):
            sonuc = self.mod.sekme_bekle("http://127.0.0.1:9222", uygulama, uyku=0, saat=simdi, **kw)
        return sonuc, saat[0]

    def test_app_never_opens_ends_at_five_minutes_with_code_2(self):
        (sekme, kod, ileti), t = self._bekle(lambda t: (False, None))
        self.assertEqual((sekme, kod), (None, 2))
        self.assertIn("300 sn içinde açılmadı", ileti)
        self.assertLess(t, 305)  # tur sayısı değil saat: 15 dk değil 5 dk

    def test_app_open_but_no_debug_port_ends_early_with_code_4(self):
        (sekme, kod, ileti), t = self._bekle(lambda t: (False, None), uygulama_acilis=40)
        self.assertEqual((sekme, kod), (None, 4))
        self.assertIn("açılmadı", ileti)
        self.assertIn("HKLM", ileti)
        self.assertLess(t, 40 + 90 + 5)

    def test_port_open_without_sesver_tab_is_code_4(self):
        (sekme, kod, ileti), _ = self._bekle(lambda t: (True, None), uygulama_acilis=10)
        self.assertEqual(kod, 4)
        self.assertIn("yanıt veriyor ama", ileti)

    def test_tab_found(self):
        hedef = {"url": "http://127.0.0.1:7860/tr", "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/1"}
        (sekme, kod, ileti), _ = self._bekle(lambda t: (t >= 60, hedef if t >= 60 else None), uygulama_acilis=30)
        self.assertEqual((sekme, kod, ileti), (hedef, 0, None))

    def test_without_app_url_old_behaviour_code_2(self):
        (sekme, kod, ileti), t = self._bekle(lambda t: (False, None), uygulama=None, bekle=20)
        self.assertEqual(kod, 2)
        self.assertIn("bulunamadı", ileti)
        self.assertLess(t, 25)

    def _calistir(self, *args):
        ortam = dict(__import__("os").environ, PYTHONIOENCODING="cp1252")  # Windows CI konsolu gibi
        return subprocess.run([sys.executable, str(ROOT / "tools" / "mikrofon_duman.py"), *args],
                              capture_output=True, env=ortam, timeout=60)

    def test_turkish_error_on_cp1252_console_keeps_exit_code(self):
        # 284e33b koşusu: "bulunamadı" cp1252'de UnicodeEncodeError → çıkış 1 ("kayıt geçmedi" sanıldı).
        r = self._calistir("--cdp", "http://127.0.0.1:9", "--bekle", "1")
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertNotIn(b"UnicodeEncodeError", r.stderr)
        self.assertEqual(json.loads(r.stdout.decode("utf-8").strip().splitlines()[-1])["kod"], 2)
        self.assertIn("bulunamadı", r.stdout.decode("utf-8"))

    def test_unexpected_error_is_5_not_1(self):
        r = self._calistir("--cdp", "http://example.com:9222", "--bekle", "1")
        self.assertEqual(r.returncode, 5)
        self.assertIn("yalnız yerel adres", r.stdout.decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
