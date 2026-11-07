"""Kuyruk çalışırken bilgisayarın boşta uykuya geçmesini engeller (ekran kapanabilir).

Windows: PowerCreateRequest + PowerSetRequest(PowerRequestSystemRequired); olmazsa
         SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED). İkincisi iş
         parçacığına bağlıdır: aynı iş parçacığında açılıp kapatılmalıdır (kuyruk işçisi öyle yapar).
Mac:     NSProcessInfo.beginActivityWithOptions(NSActivityUserInitiated) — boşta uykuyu ve
         App Nap'i engeller; ekranın uyumasını ENGELLEMEZ. Foundation yüklenemezse
         `caffeinate -i -w <pid>` (SesVer çökse de engel kendiliğinden kalkar).

Sınırlar (işletim sistemi kuralı, kodla aşılmaz): kapak kapatma, güç düğmesi ve kullanıcının
"Uyku/Uyut" seçmesi engeli iptal eder; Windows Modern Standby dizüstülerinde pilde istek uyku
zaman aşımından 5 dk sonra düşer; Mac'te pil biterse sistem uyur.

Engel açılamazsa hata fırlatılmaz (üretim yine çalışır); `yontem` "yok" olur ve günlüğe yazılır.
Yalnız standart kütüphane (+ Mac'te zaten bağımlılık olan pyobjc Foundation).
"""
import contextlib
import logging
import os
import subprocess
import sys

log = logging.getLogger("sesver")

# ASCII: macOS powerd Türkçe harfli gerekçeyi `pmset -g assertions` çıktısında boş gösteriyor (ölçüldü).
VARSAYILAN_GEREKCE = "SesVer: ses uretim kuyrugu"

# Windows sabitleri
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
POWER_REQUEST_CONTEXT_VERSION = 0
POWER_REQUEST_CONTEXT_SIMPLE_STRING = 0x1
POWER_REQUEST_SYSTEM_REQUIRED = 1  # POWER_REQUEST_TYPE.PowerRequestSystemRequired
INVALID_HANDLE_VALUE = -1

# Mac: NSActivityUserInitiated = 0x00FFFFFF | NSActivityIdleSystemSleepDisabled (1 << 20).
# NSActivityIdleDisplaySleepDisabled (1 << 40) bilerek YOK: ekran kapanabilir.
NS_ACTIVITY_USER_INITIATED = 0x00FFFFFF | (1 << 20)
CAFFEINATE = "/usr/bin/caffeinate"


def _reason_context(gerekce):
    import ctypes
    from ctypes import wintypes

    class _Detailed(ctypes.Structure):
        _fields_ = [("LocalizedReasonModule", wintypes.HMODULE), ("LocalizedReasonId", wintypes.ULONG),
                    ("ReasonStringCount", wintypes.ULONG), ("ReasonStrings", ctypes.POINTER(wintypes.LPWSTR))]

    class _Reason(ctypes.Union):
        _fields_ = [("Detailed", _Detailed), ("SimpleReasonString", wintypes.LPWSTR)]

    class REASON_CONTEXT(ctypes.Structure):  # noqa: N801 — Win32 adı
        _fields_ = [("Version", wintypes.ULONG), ("Flags", wintypes.DWORD), ("Reason", _Reason)]

    ctx = REASON_CONTEXT()
    ctx.Version = POWER_REQUEST_CONTEXT_VERSION
    ctx.Flags = POWER_REQUEST_CONTEXT_SIMPLE_STRING
    ctx.Reason.SimpleReasonString = gerekce
    return ctx


def _hazirla(k32):
    """Gerçek kernel32'de dönüş/argüman türlerini ayarlar (sahte nesnelerde sessizce atlanır)."""
    import ctypes

    try:
        k32.PowerCreateRequest.restype = ctypes.c_void_p
        k32.PowerSetRequest.argtypes = [ctypes.c_void_p, ctypes.c_int]
        k32.PowerClearRequest.argtypes = [ctypes.c_void_p, ctypes.c_int]
        k32.CloseHandle.argtypes = [ctypes.c_void_p]
        k32.SetThreadExecutionState.restype = ctypes.c_uint32
        k32.SetThreadExecutionState.argtypes = [ctypes.c_uint32]
    except (AttributeError, TypeError):
        pass


class Engel:
    """`ac()` / `kapat()`; tekrar çağrılar zararsızdır. `yontem`: hangi yolun kullanıldığı."""

    def __init__(self, gerekce=VARSAYILAN_GEREKCE, platform=None, kernel32=None, foundation=None, popen=None):
        self.gerekce = gerekce
        self.platform = platform or sys.platform
        self._k32 = kernel32
        self._foundation = foundation
        self._popen = popen or subprocess.Popen
        self.yontem = "yok"
        self.aktif = False
        self._tutamac = None
        self._aktivite = None
        self._surec = None

    # --- Windows ---------------------------------------------------------------------
    def _k32_al(self):
        if self._k32 is None:
            import ctypes
            self._k32 = getattr(ctypes, "WinDLL")("kernel32", use_last_error=True)  # yalnız Windows'ta var
            _hazirla(self._k32)
        return self._k32

    def _ac_windows(self):
        import ctypes

        k32 = self._k32_al()
        try:
            h = k32.PowerCreateRequest(ctypes.byref(_reason_context(self.gerekce)))
            # Hata dönüşü INVALID_HANDLE_VALUE; c_void_p olarak işaretsiz de gelebilir.
            if h and h not in (INVALID_HANDLE_VALUE, 2 ** 64 - 1, 2 ** 32 - 1):
                if k32.PowerSetRequest(h, POWER_REQUEST_SYSTEM_REQUIRED):
                    self._tutamac = h
                    return "windows-powerrequest"
                k32.CloseHandle(h)
        except (AttributeError, OSError, ValueError, TypeError) as exc:
            log.warning("uyku engeli: PowerCreateRequest kullanılamadı (%s)", exc)
        if k32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED):
            return "windows-executionstate"
        return "yok"

    def _kapat_windows(self):
        k32 = self._k32_al()
        if self.yontem == "windows-powerrequest" and self._tutamac:
            k32.PowerClearRequest(self._tutamac, POWER_REQUEST_SYSTEM_REQUIRED)
            k32.CloseHandle(self._tutamac)
            self._tutamac = None
        elif self.yontem == "windows-executionstate":
            k32.SetThreadExecutionState(ES_CONTINUOUS)

    # --- Mac -------------------------------------------------------------------------
    def _ac_mac(self):
        try:
            foundation = self._foundation
            if foundation is None:
                import Foundation as foundation  # pyobjc-framework-Cocoa (requirements.txt)
            bilgi = foundation.NSProcessInfo.processInfo()
            self._aktivite = bilgi.beginActivityWithOptions_reason_(NS_ACTIVITY_USER_INITIATED, self.gerekce)
            if self._aktivite is not None:
                return "mac-nsprocessinfo"
        except Exception as exc:  # noqa: BLE001 — pyobjc yoksa caffeinate'e düş
            log.warning("uyku engeli: NSProcessInfo kullanılamadı (%s), caffeinate deneniyor", exc)
        try:
            self._surec = self._popen([CAFFEINATE, "-i", "-w", str(os.getpid())],
                                      stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                      stderr=subprocess.DEVNULL)
            return "mac-caffeinate"
        except OSError as exc:
            log.warning("uyku engeli: caffeinate başlatılamadı (%s)", exc)
            return "yok"

    def _kapat_mac(self):
        if self.yontem == "mac-nsprocessinfo" and self._aktivite is not None:
            foundation = self._foundation
            if foundation is None:
                import Foundation as foundation
            foundation.NSProcessInfo.processInfo().endActivity_(self._aktivite)
            self._aktivite = None
        elif self.yontem == "mac-caffeinate" and self._surec is not None:
            self._surec.terminate()
            try:
                self._surec.wait(timeout=2)
            except Exception:  # noqa: BLE001 — süreç zaten bittiyse ya da yanıt vermiyorsa
                pass
            self._surec = None

    # --- Ortak -----------------------------------------------------------------------
    def ac(self):
        if self.aktif:
            return self.yontem
        try:
            if self.platform == "win32":
                self.yontem = self._ac_windows()
            elif self.platform == "darwin":
                self.yontem = self._ac_mac()
            else:
                self.yontem = "yok"
        except Exception as exc:  # noqa: BLE001 — engel açılamasa da üretim sürer
            log.warning("uyku engeli açılamadı: %s", exc)
            self.yontem = "yok"
        self.aktif = self.yontem != "yok"
        log.info("uyku engeli: %s", self.yontem if self.aktif else "açılamadı (yok)")
        return self.yontem

    def kapat(self):
        if not self.aktif:
            return
        try:
            if self.platform == "win32":
                self._kapat_windows()
            elif self.platform == "darwin":
                self._kapat_mac()
        except Exception as exc:  # noqa: BLE001
            log.warning("uyku engeli kapatılırken hata: %s", exc)
        finally:
            self.aktif = False
            log.info("uyku engeli kaldırıldı (%s)", self.yontem)


@contextlib.contextmanager
def acik(gerekce=VARSAYILAN_GEREKCE, **kwargs):
    """`with acik():` bloğu boyunca uyku engeli; istisna olsa da bırakılır."""
    engel = Engel(gerekce, **kwargs)
    engel.ac()
    try:
        yield engel
    finally:
        engel.kapat()


def pilde_mi(platform=None, kernel32=None, calistir=None):
    """True: pille çalışıyor; False: prizde; None: bilinmiyor (masaüstü, okunamadı).

    Kuyruk başlarken yalnız UYARI için kullanılır (engellemez)."""
    platform = platform or sys.platform
    try:
        if platform == "win32":
            import ctypes

            class SYSTEM_POWER_STATUS(ctypes.Structure):  # noqa: N801 — Win32 adı
                _fields_ = [("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte),
                            ("BatteryLifePercent", ctypes.c_ubyte), ("SystemStatusFlag", ctypes.c_ubyte),
                            ("BatteryLifeTime", ctypes.c_ulong), ("BatteryFullLifeTime", ctypes.c_ulong)]

            k32 = kernel32 or getattr(ctypes, "WinDLL")("kernel32")
            st = SYSTEM_POWER_STATUS()
            if not k32.GetSystemPowerStatus(ctypes.byref(st)):
                return None
            if st.BatteryFlag == 128:  # pil yok (masaüstü)
                return False
            return {0: True, 1: False}.get(int(st.ACLineStatus))
        if platform == "darwin":
            calistir = calistir or (lambda: subprocess.run(["/usr/bin/pmset", "-g", "batt"], capture_output=True,
                                                           text=True, timeout=3).stdout)
            out = calistir() or ""
            if "'Battery Power'" in out:
                return True
            if "'AC Power'" in out:
                return False
            return None
    except Exception:  # noqa: BLE001 — bilgi yoksa uyarı gösterilmez
        return None
    return None
