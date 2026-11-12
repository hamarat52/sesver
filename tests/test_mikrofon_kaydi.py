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
        bayrak = adim["env"]["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"]
        for b in ("--remote-debugging-port=9222", "--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"):
            self.assertIn(b, bayrak)
        run = adim["run"]
        self.assertIn("-ArgumentList 'desktop.py'", run)  # tarayıcı değil, gerçek pencere
        self.assertIn(r"tools\mikrofon_duman.py --cdp http://127.0.0.1:9222", run)
        self.assertNotIn("--alan", run)  # varsayılan "hepsi": Ses Oluştur ve Ses Klonlama birlikte
        self.assertIn("if ($kod -ne 0) { throw", run)
        for k in (r"kilit\pip.txt", r"kilit\torch-pypi.txt", r"kilit\windows-x64-py311.txt"):
            self.assertIn(k, run)
        self.assertIn("'--require-hashes'", run)

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


if __name__ == "__main__":
    unittest.main()
