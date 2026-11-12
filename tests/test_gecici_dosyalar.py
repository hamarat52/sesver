"""1.4.2: mikrofon kayıtları ve yüklemeler SesVer'in kendi geçici klasöründe; birikmez (gecici.py).

Temizlik yalnız SesVer'in oturum klasörüne dokunur; kaydedilen sesler, outputs/, kuyruk ve modeller,
başka uygulamaların Gradio dosyaları ve canlı başka bir SesVer'in klasörü korunur. Model yüklenmez.
"""
import os
import re
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import soundfile as sf

import app
import desktop
import gecici
import voice_library as vl

ROOT = Path(__file__).resolve().parent.parent


def _wav(path, sn=10, sr=16000):
    t = np.arange(int(sn * sr)) / sr
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), (0.3 * np.sin(2 * np.pi * 200 * t)).astype(np.float32), sr, subtype="PCM_16")
    return str(path)


def _eskit(yol, sn):
    eski = time.time() - sn
    os.utime(yol, (eski, eski))


class _Blocks:
    def __init__(self):
        self.upload_file_set = set()


@unittest.skipIf(os.name == "nt", "POSIX izin/sahiplik denetimi")
class KokGuvenligiTests(unittest.TestCase):
    """siberguvenlik D4: kök ve oturum 0o700; kök bağ ya da başkasınınsa kullanılmaz (güvenli yedek)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    @staticmethod
    def _mod(yol):
        return os.lstat(yol).st_mode & 0o777

    def test_yeni_kok_ve_oturum_0o700(self):
        eski = os.umask(0o022)
        try:
            alan = gecici.GeciciAlan(kok=self.tmp / "sesver-gecici")
            oturum = alan.kur(gradio_env=False, zamanlayici=False)
        finally:
            os.umask(eski)
        self.assertEqual(self._mod(self.tmp / "sesver-gecici"), 0o700)
        self.assertEqual(self._mod(oturum), 0o700)
        self.assertEqual(oturum.parent, self.tmp / "sesver-gecici")
        alan.kapat()

    def test_eski_surumun_0o755_koku_0o700_yapilir(self):
        kok = self.tmp / "sesver-gecici"
        kok.mkdir()
        os.chmod(kok, 0o755)
        self.assertEqual(gecici.kok_hazirla(kok), (True, ""))
        self.assertEqual(self._mod(kok), 0o700)

    def test_bag_kok_reddedilir_kayit_hedefe_yazilmaz(self):
        hedef = self.tmp / "baskasinin"
        hedef.mkdir()
        kok = self.tmp / "sesver-gecici"
        os.symlink(hedef, kok)
        ok, neden = gecici.kok_hazirla(kok)
        self.assertFalse(ok)
        self.assertIn("bağ", neden)
        alan = gecici.GeciciAlan(kok=kok)
        with self.assertLogs("sesver", "WARNING") as kayit:
            oturum = alan.kur(gradio_env=False, zamanlayici=False)
        self.assertIn("güvensiz", kayit.output[0])
        self.assertEqual(list(hedef.iterdir()), [])            # bağın hedefine hiçbir şey yazılmadı
        self.assertFalse(gecici._icinde(oturum, hedef))
        self.assertTrue(oturum.parent.name.startswith("sesver-gecici-"))  # mkdtemp yedeği
        self.assertEqual(self._mod(oturum.parent), 0o700)
        self.assertEqual(self._mod(oturum), 0o700)
        yedek = oturum.parent
        alan.kapat()
        self.assertFalse(yedek.exists())                       # yedek kök kapanışta kaldırılır
        self.assertTrue(os.path.islink(kok))                   # bağa dokunulmadı

    def test_baskasinin_koku_reddedilir(self):
        kok = self.tmp / "sesver-gecici"
        kok.mkdir(mode=0o700)
        with patch.object(gecici.os, "getuid", return_value=os.lstat(kok).st_uid + 1):
            ok, neden = gecici.kok_hazirla(kok)
        self.assertFalse(ok)
        self.assertIn("sahibi başka kullanıcı", neden)

    def test_dosya_olan_kok_reddedilir(self):
        kok = self.tmp / "sesver-gecici"
        kok.write_text("x")
        self.assertEqual(gecici.kok_hazirla(kok), (False, "klasör değil"))


class GeciciAlanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.kok = self.tmp / "sesver-gecici"
        self.alan = gecici.GeciciAlan(kok=self.kok)
        self.oturum = self.alan.kur(gradio_env=False, zamanlayici=False)
        self.blocks = _Blocks()
        self.alan.izle(self.blocks)

    def tearDown(self):
        self.alan.kapat()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _yukleme(self, ad="audio.wav"):
        """Gradio'nun /upload yolu: <önbellek>/<özet>/<ad> ve blocks.upload_file_set."""
        y = _wav(self.oturum / os.urandom(8).hex() / ad)
        self.blocks.upload_file_set.add(y)
        return y

    def test_constants_are_reasonable(self):
        self.assertEqual(gecici.ARALIK_SN, 30 * 60)
        self.assertEqual(gecici.YAS_SN, 2 * 60 * 60)
        self.assertEqual(gecici.KOK_ADI, "sesver-gecici")
        self.assertEqual(gecici.varsayilan_kok(), Path(tempfile.gettempdir()) / "sesver-gecici")

    def test_session_folder_and_gradio_env(self):
        self.assertTrue(re.match(r"^\d+-[0-9a-f]{8}$", self.oturum.name))
        self.assertTrue((self.oturum / gecici.KILIT_ADI).is_file())
        self.assertTrue(gecici._icinde(self.oturum, self.kok))
        alan = gecici.GeciciAlan(kok=self.tmp / "baska")
        with patch.dict(os.environ, {}, clear=False):
            oturum = alan.kur(zamanlayici=False)
            self.assertEqual(os.environ["GRADIO_TEMP_DIR"], str(oturum))
            self.assertEqual(alan.kur(), oturum)  # bir kez kurulur
        alan.kapat()

    def test_interval_cleanup_threshold_and_scope(self):
        kayit = self._yukleme()                                    # mikrofon kaydı
        taze = self._yukleme("yeni.wav")                           # az önce yüklendi
        hazir = _wav(self.alan.hazirlik_klasoru() / "yukleme-x.wav")
        kopya = _wav(self.oturum / "ozet" / "ai-ile-uretildi-1.wav")  # outputs/'taki sesin Gradio kopyası
        disari = _wav(self.tmp / "outputs" / "ai-ile-uretildi-1.wav")
        baska = _wav(self.tmp / "gradio" / "abc" / "baska-uygulama.wav")  # ortak gradio/ klasörü
        self.blocks.upload_file_set.update({disari, baska})       # olmaz ama olsa da dokunulmamalı
        for y in (kayit, hazir, kopya, disari, baska):
            _eskit(y, gecici.YAS_SN + 60)
        _eskit(taze, gecici.YAS_SN - 60)                           # eşiğin altında
        silinen = self.alan.temizle()
        self.assertEqual(sorted(silinen), sorted([kayit, hazir]))
        for y in (taze, kopya, disari, baska):
            self.assertTrue(Path(y).exists(), y)
        self.assertNotIn(kayit, self.blocks.upload_file_set)
        self.assertFalse(Path(kayit).parent.exists())              # boş özet klasörü de gider
        # Eşik: YAS_SN'yi geçen silinir, geçmeyen kalır.
        _eskit(taze, gecici.YAS_SN + 1)
        self.assertEqual(self.alan.temizle(), [taze])

    def test_file_in_use_is_kept(self):
        kayit = self._yukleme()
        _eskit(kayit, gecici.YAS_SN + 600)
        self.alan.dokun(kayit)                                     # bir işlev şimdi okudu
        self.assertEqual(self.alan.temizle(), [])
        self.assertTrue(Path(kayit).exists())

    def test_timer_runs_cleanup(self):
        alan = gecici.GeciciAlan(kok=self.tmp / "zaman", aralik=0.05, yas=0)
        oturum = alan.kur(gradio_env=False)
        b = _Blocks()
        alan.izle(b)
        y = _wav(oturum / "ozet" / "audio.wav")
        b.upload_file_set.add(y)
        _eskit(y, 5)
        for _ in range(100):
            if not Path(y).exists():
                break
            time.sleep(0.05)
        self.assertFalse(Path(y).exists())
        alan.kapat()
        self.assertFalse(alan._zamanlayici.is_alive() and not alan._dur.is_set())

    def test_close_removes_only_own_session(self):
        y = self._yukleme()
        komsu = self.kok / "notlar.txt"
        komsu.write_text("dokunma")
        self.assertTrue(self.alan.kapat())
        self.assertFalse(self.oturum.exists())
        self.assertFalse(Path(y).exists())
        self.assertTrue(komsu.exists())                            # adı oturum biçiminde olmayan şey kalır
        self.assertFalse(self.alan.kapat())                        # ikinci çağrı güvenli

    def test_stale_sessions_removed_live_ones_kept(self):
        canli = gecici.GeciciAlan(kok=self.kok)                    # aynı anda açık ikinci SesVer
        canli_oturum = canli.kur(gradio_env=False, zamanlayici=False)
        _wav(canli_oturum / "y" / "audio.wav")
        olu = self.kok / "123-deadbeef"                            # çökmüş SesVer'den kalan
        _wav(olu / "x" / "audio.wav")
        (olu / gecici.KILIT_ADI).write_bytes(b"")                  # sahibi yok: kilit alınabilir
        yeni_kilitsiz = self.kok / "456-0badc0de"                  # henüz kuruluyor (kilit yok, yeni)
        yeni_kilitsiz.mkdir()
        yabanci = self.kok / "baska-klasor"
        yabanci.mkdir()
        silinen = self.alan.eski_oturumlari_temizle()
        self.assertEqual(silinen, [str(olu)])
        for d in (canli_oturum, yeni_kilitsiz, yabanci, self.oturum):
            self.assertTrue(d.exists(), d)
        self.assertFalse(olu.exists())
        # Açılışta da: yeni bir SesVer kurulurken ölü oturumu siler, canlı olanı bırakır.
        _wav(olu / "x" / "audio.wav")
        (olu / gecici.KILIT_ADI).write_bytes(b"")
        ucuncu = gecici.GeciciAlan(kok=self.kok)
        ucuncu.kur(gradio_env=False, zamanlayici=False)
        self.assertFalse(olu.exists())
        self.assertTrue(canli_oturum.exists())
        ucuncu.kapat()
        canli.kapat()

    def test_delete_only_inside_session(self):
        icerde = self._yukleme()
        disari = _wav(self.tmp / "voices" / "seslerim" / "ses" / "ref.wav")
        kilit = str(self.oturum / gecici.KILIT_ADI)
        kacak = str(self.oturum / ".." / ".." / "voices" / "seslerim" / "ses" / "ref.wav")
        self.assertEqual(self.alan.sil(icerde, disari, kilit, kacak, None, ""), 1)
        self.assertTrue(Path(disari).exists())
        self.assertTrue(Path(kilit).exists())


class AppIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.alan = gecici.GeciciAlan(kok=self.tmp / "sesver-gecici")
        self.oturum = self.alan.kur(gradio_env=False, zamanlayici=False)
        self.patches = [patch.object(gecici, "_alan", self.alan),
                        patch.object(app, "OUTPUT_DIR", self.tmp / "outputs"),
                        patch.object(vl, "VOICES_DIR", self.tmp / "voices")]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.alan.kapat()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_prepared_copies_go_to_temp_not_outputs(self):
        kayit = _wav(self.oturum / "ozet" / "audio.wav", sn=10)
        full, prepared, *_ = app.mic_analyze_ui(kayit)
        for y in (full, prepared):
            self.assertTrue(gecici._icinde(y, self.oturum / gecici.HAZIRLIK_ADI), y)
        self.assertFalse((self.tmp / "outputs").exists() and any((self.tmp / "outputs").iterdir()))

    def test_saving_a_voice_deletes_temp_copies_and_keeps_the_voice(self):
        kayit = _wav(self.oturum / "ozet" / "audio.wav", sn=12)
        full, prepared, *_ = app.mic_analyze_ui(kayit)
        cikti = _wav(self.tmp / "outputs" / "ai-ile-uretildi-1.wav")
        # İzin kutucuğu işaretli değil: kaydetme reddedilir, HİÇBİR şey silinmez.
        with self.assertRaisesRegex(app.gr.Error, "izin"):
            app.save_uploaded_and_clean_ui(prepared, "Merhaba bu benim sesim.", "Sesim", "", "", False,
                                           full, None, kayit)
        for y in (kayit, full, prepared):
            self.assertTrue(Path(y).exists(), y)
        out = app.save_uploaded_and_clean_ui(prepared, "Merhaba bu benim sesim.", "Sesim", "", "", True,
                                             full, None, kayit)
        self.assertEqual(out[4:], (None, None, None, None, None))  # u_full, u_prepared, u_preview, u_file, u_mic
        for y in (kayit, full, prepared):
            self.assertFalse(Path(y).exists(), y)
        ses = vl.get_voice(out[1])
        self.assertTrue((self.tmp / "voices" / "seslerim").is_dir())
        self.assertEqual(ses["ad"], "Sesim")
        self.assertTrue(any((self.tmp / "voices" / "seslerim").rglob("ref.wav")))  # kaydedilen ses yerinde
        self.assertTrue(Path(cikti).exists())                              # outputs/ korunur

    def test_handlers_mark_files_as_in_use(self):
        ref = _wav(self.oturum / "ozet" / "audio.wav", sn=5)
        _eskit(ref, gecici.YAS_SN + 600)
        from types import SimpleNamespace
        from unittest.mock import Mock
        whisper = Mock(transcribe=Mock(return_value=([SimpleNamespace(text=" Merhaba. ")], None)))
        with patch.object(app, "_get_whisper", return_value=whisper):
            app.auto_transcribe(ref)
        self.assertLess(time.time() - os.stat(ref).st_mtime, 60)


class WiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch.object(app.guncelleme.urllib.request, "urlopen", side_effect=AssertionError("ağ çağrıldı")):
            cls.demo = app.build_app()

    def test_build_app_routes_gradio_cache_to_the_session(self):
        oturum = gecici.oturum()
        self.assertIsNotNone(oturum)
        self.assertEqual(os.environ.get("GRADIO_TEMP_DIR"), str(oturum))
        self.assertTrue(gecici._icinde(oturum, gecici.varsayilan_kok()))
        audio = next(b for b in self.demo.blocks.values() if type(b).__name__ == "Audio")
        self.assertEqual(Path(audio.GRADIO_CACHE), oturum)  # bileşen önbelleği de oturumda
        self.assertIs(gecici._alan._blocks, self.demo)

    def test_save_event_cleans_temp_copies(self):
        fns = [f for f in self.demo.fns.values() if f.fn is app.save_uploaded_and_clean_ui]
        self.assertGreaterEqual(len(fns), 1)
        for f in fns:
            tipler = [type(i).__name__ for i in f.inputs]
            self.assertEqual(tipler[-2:], ["File", "Audio"])  # dosya kutusu ve mikrofon kaydı da gelir
            self.assertEqual([type(o).__name__ for o in f.outputs][-2:], ["File", "Audio"])
        self.assertFalse([f for f in self.demo.fns.values() if f.fn is app.save_uploaded_ui])

    def test_atexit_registered_once(self):
        with patch.object(gecici, "_atexit_kayitli", False), patch.object(gecici.atexit, "register") as reg, \
                patch.object(gecici._alan, "kur", return_value=Path("x")):
            gecici.kur()
            gecici.kur()
        reg.assert_called_once_with(gecici._alan.kapat)


class DesktopShutdownTests(unittest.TestCase):
    def test_every_exit_path_cleans_up_first(self):
        import inspect
        kaynak = inspect.getsource(desktop.main)
        satirlar = [s.strip() for s in kaynak.splitlines() if s.strip()]
        cikislar = [i for i, s in enumerate(satirlar) if s.startswith("os._exit(")]
        self.assertEqual(len(cikislar), 2)
        for i in cikislar:  # os._exit atexit'i çalıştırmaz: önce açık temizlik
            self.assertIn("_gecici_kapat()", satirlar[max(0, i - 3):i])
        i = satirlar.index("_run_browser(server)")
        self.assertEqual(satirlar[i + 1], "_gecici_kapat()")

    def test_gecici_kapat_calls_module_and_never_raises(self):
        with patch.object(app.gecici, "kapat", return_value=True) as k:
            desktop._gecici_kapat()
        k.assert_called_once_with()
        with patch.object(app.gecici, "kapat", side_effect=OSError("kilitli")):
            desktop._gecici_kapat()  # kapanışı engellemez


class DocsTests(unittest.TestCase):
    def test_readme_and_changelog_describe_cleanup_without_em_dash(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        en = next(s for s in readme.splitlines() if s.startswith("**Microphone:**"))
        tr = next(s for s in readme.splitlines() if s.startswith("**Türkçe özet:**"))
        self.assertIn("sesver-gecici", en)
        self.assertIn("when SesVer closes", en)
        self.assertNotIn("Gradio's local temporary folder and `outputs/`", en)
        self.assertIn("SesVer kapanınca", tr)
        self.assertIn("sesver-gecici", tr)
        self.assertNotIn("Otomatik silinmez", readme)
        degisiklik = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8").split("## 1.4.1")[0]
        satir = next(s for s in degisiklik.splitlines() if "artık birikmiyor" in s)
        for metin in (en, tr, satir):
            self.assertNotIn("\u2014", metin)


if __name__ == "__main__":
    unittest.main()
