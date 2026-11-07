"""Uyku engeli: Windows/Mac yolları (sahte işletim sistemi API'leriyle), her durumda bırakma."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import uyku_engeli as ue  # noqa: E402


class SahteKernel32:
    def __init__(self, create_ok=True, set_ok=True, ste_ok=True):
        self.cagrilar = []
        self.create_ok, self.set_ok, self.ste_ok = create_ok, set_ok, ste_ok

    def PowerCreateRequest(self, ctx):  # noqa: N802 — Win32 adı
        self.cagrilar.append(("PowerCreateRequest",))
        return 1234 if self.create_ok else ue.INVALID_HANDLE_VALUE

    def PowerSetRequest(self, h, tur):  # noqa: N802
        self.cagrilar.append(("PowerSetRequest", h, tur))
        return 1 if self.set_ok else 0

    def PowerClearRequest(self, h, tur):  # noqa: N802
        self.cagrilar.append(("PowerClearRequest", h, tur))
        return 1

    def CloseHandle(self, h):  # noqa: N802
        self.cagrilar.append(("CloseHandle", h))
        return 1

    def SetThreadExecutionState(self, bayrak):  # noqa: N802
        self.cagrilar.append(("SetThreadExecutionState", bayrak))
        return 0x80000000 if self.ste_ok else 0

    def adlar(self):
        return [c[0] for c in self.cagrilar]


class SahteFoundation:
    def __init__(self, hata=False):
        self.cagrilar = []
        self.hata = hata
        dis = self

        class _Bilgi:
            def beginActivityWithOptions_reason_(self, secenek, gerekce):  # noqa: N802
                if dis.hata:
                    raise RuntimeError("pyobjc yok")
                dis.cagrilar.append(("begin", secenek, gerekce))
                return "aktivite"

            def endActivity_(self, aktivite):  # noqa: N802
                dis.cagrilar.append(("end", aktivite))

        self.NSProcessInfo = SimpleNamespace(processInfo=lambda: _Bilgi())


class SahteSurec:
    def __init__(self, argv, **_kw):
        self.argv = argv
        self.sonlandi = False

    def terminate(self):
        self.sonlandi = True

    def wait(self, timeout=None):
        return 0


class WindowsTests(unittest.TestCase):
    def test_powerrequest_ac_kapat(self):
        k = SahteKernel32()
        with ue.acik("SesVer deneme", platform="win32", kernel32=k) as engel:
            self.assertTrue(engel.aktif)
            self.assertEqual(engel.yontem, "windows-powerrequest")
            self.assertEqual(k.adlar(), ["PowerCreateRequest", "PowerSetRequest"])
            self.assertEqual(k.cagrilar[1][2], ue.POWER_REQUEST_SYSTEM_REQUIRED)
        self.assertFalse(engel.aktif)
        self.assertEqual(k.adlar()[2:], ["PowerClearRequest", "CloseHandle"])
        self.assertNotIn("SetThreadExecutionState", k.adlar())

    def test_powerrequest_olmazsa_executionstate_ekran_bayragi_yok(self):
        k = SahteKernel32(create_ok=False)
        with ue.acik(platform="win32", kernel32=k) as engel:
            self.assertEqual(engel.yontem, "windows-executionstate")
        bayraklar = [c[1] for c in k.cagrilar if c[0] == "SetThreadExecutionState"]
        self.assertEqual(bayraklar, [ue.ES_CONTINUOUS | ue.ES_SYSTEM_REQUIRED, ue.ES_CONTINUOUS])
        self.assertFalse(bayraklar[0] & 0x00000002, "ES_DISPLAY_REQUIRED verilmemeli: ekran kapanabilir")

    def test_set_request_basarisizsa_tutamac_kapatilir(self):
        k = SahteKernel32(set_ok=False)
        engel = ue.Engel(platform="win32", kernel32=k)
        engel.ac()
        self.assertEqual(engel.yontem, "windows-executionstate")
        self.assertIn(("CloseHandle", 1234), k.cagrilar)
        engel.kapat()

    def test_hicbiri_olmazsa_yok_ve_hata_firlatmaz(self):
        k = SahteKernel32(create_ok=False, ste_ok=False)
        with ue.acik(platform="win32", kernel32=k) as engel:
            self.assertEqual(engel.yontem, "yok")
            self.assertFalse(engel.aktif)

    def test_istisna_olsa_da_birakilir(self):
        k = SahteKernel32()
        with self.assertRaises(ValueError):
            with ue.acik(platform="win32", kernel32=k):
                raise ValueError("üretim patladı")
        self.assertEqual(k.adlar()[-2:], ["PowerClearRequest", "CloseHandle"])

    def test_tekrar_ac_kapat_zararsiz(self):
        k = SahteKernel32()
        engel = ue.Engel(platform="win32", kernel32=k)
        engel.ac()
        engel.ac()
        engel.kapat()
        engel.kapat()
        self.assertEqual(k.adlar().count("PowerCreateRequest"), 1)
        self.assertEqual(k.adlar().count("CloseHandle"), 1)


class MacTests(unittest.TestCase):
    def test_nsprocessinfo_ac_kapat_ekran_uykusu_engellenmez(self):
        f = SahteFoundation()
        with ue.acik(ue.VARSAYILAN_GEREKCE, platform="darwin", foundation=f) as engel:
            self.assertEqual(engel.yontem, "mac-nsprocessinfo")
            _, secenek, gerekce = f.cagrilar[0]
            self.assertEqual(gerekce, "SesVer: ses uretim kuyrugu")
            self.assertTrue(gerekce.isascii(), "powerd ASCII olmayan adı boş gösteriyor")
            self.assertTrue(secenek & (1 << 20), "NSActivityIdleSystemSleepDisabled olmalı")
            self.assertFalse(secenek & (1 << 40), "NSActivityIdleDisplaySleepDisabled olmamalı")
        self.assertEqual(f.cagrilar[-1], ("end", "aktivite"))

    def test_foundation_yoksa_caffeinate_i_w_pid(self):
        surecler = []

        def popen(argv, **kw):
            surecler.append(SahteSurec(argv, **kw))
            return surecler[-1]

        with ue.acik(platform="darwin", foundation=SahteFoundation(hata=True), popen=popen) as engel:
            self.assertEqual(engel.yontem, "mac-caffeinate")
            argv = surecler[0].argv
            self.assertEqual(argv[:3], [ue.CAFFEINATE, "-i", "-w"])
            self.assertTrue(argv[3].isdigit())
            self.assertNotIn("-d", argv)
        self.assertTrue(surecler[0].sonlandi)

    def test_caffeinate_de_yoksa_yok(self):
        def popen(argv, **kw):
            raise FileNotFoundError(argv[0])

        with ue.acik(platform="darwin", foundation=SahteFoundation(hata=True), popen=popen) as engel:
            self.assertEqual(engel.yontem, "yok")

    def test_desteklenmeyen_platform(self):
        with ue.acik(platform="linux") as engel:
            self.assertEqual(engel.yontem, "yok")


class PilTests(unittest.TestCase):
    def test_mac_pmset_ciktisi(self):
        self.assertTrue(ue.pilde_mi("darwin", calistir=lambda: "Now drawing from 'Battery Power'\n -InternalBattery-0"))
        self.assertFalse(ue.pilde_mi("darwin", calistir=lambda: "Now drawing from 'AC Power'\n"))
        self.assertIsNone(ue.pilde_mi("darwin", calistir=lambda: ""))

    def test_windows_guc_durumu(self):
        def k32(ac, flag):
            def durum(ptr):
                st = ptr._obj
                st.ACLineStatus, st.BatteryFlag = ac, flag
                return 1
            return SimpleNamespace(GetSystemPowerStatus=durum)

        self.assertTrue(ue.pilde_mi("win32", kernel32=k32(0, 1)))
        self.assertFalse(ue.pilde_mi("win32", kernel32=k32(1, 1)))
        self.assertFalse(ue.pilde_mi("win32", kernel32=k32(255, 128)))  # masaüstü: pil yok
        self.assertIsNone(ue.pilde_mi("win32", kernel32=k32(255, 1)))

    def test_bilinmeyen_platform(self):
        self.assertIsNone(ue.pilde_mi("linux"))


if __name__ == "__main__":
    unittest.main()
