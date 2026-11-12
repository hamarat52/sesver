"""SesVer'in kendi geçici dosya alanı (mikrofon kayıtları, yüklenen dosyalar, hazırlık kopyaları).

Neden: Gradio yüklenen dosyaları (mikrofon kaydı dahil) varsayılan olarak sistem geçici
klasöründeki ORTAK `gradio/` klasörüne yazar ve hiç silmez; ses kaydı biyometrik nitelikte bir
veridir ve kullanıcının hesabında birikmemelidir.

Nasıl:
- Her SesVer süreci kendi oturum klasörünü kullanır: `<sistem geçici>/sesver-gecici/<pid>-<rastgele>`.
  `GRADIO_TEMP_DIR` bu klasöre yönlendirilir (arayüz kurulmadan ÖNCE: Gradio bileşenleri ve
  sunucu yükleme klasörünü kurulurken okur). Başka uygulamaların Gradio dosyalarına (ortak
  `gradio/` klasörü) hiç dokunulmaz.
- Kapanışta (pencere kapanınca, Ctrl+C, normal çıkış) oturum klasörü tümüyle silinir.
- Uzun oturumda her ARALIK_SN'de bir: kullanıcıdan gelen dosyalar (mikrofon kaydı ve yüklemeler,
  Gradio'nun `upload_file_set`'i) ve hazırlık kopyaları (`hazirlik/`) YAS_SN boyunca
  kullanılmadıysa silinir. "Kullanıldı" = oluşturuldu ya da bir işlev onu okudu (`dokun`). Üretilen
  seslerin Gradio kopyaları (asılları outputs/'ta) oturum boyunca kalır: dinleme/indirme bozulmaz.
- Bir kayıt sese dönüştürülünce (voices/ altına kopyalanınca) geçici kopyaları hemen silinir (`sil`).
- Çökmüş/zorla kapatılmış bir süreçten kalan oturum klasörü sonraki açılışta silinir. Canlı süreç
  kendi klasöründeki `.kilit` dosyasını kilitli tutar; kilit alınabiliyorsa süreç yoktur. Böylece
  aynı anda açık ikinci bir SesVer'in klasörüne dokunulmaz.

Silinmeyenler (bu modül yalnız `sesver-gecici/` altında çalışır): voices/ (kaydedilen sesler),
outputs/ (üretilen sesler), kuyruk/ (kuyruk durumu ve çıktıları), models/ (Hızlı Mod).
Yalnız standart kütüphane.
"""
import atexit
import logging
import os
import re
import shutil
import stat
import tempfile
import threading
import time
import uuid
from pathlib import Path

log = logging.getLogger("sesver")

KOK_ADI = "sesver-gecici"
ARALIK_SN = 30 * 60        # aralıklı temizlik sıklığı
YAS_SN = 2 * 60 * 60       # bu kadar süre kullanılmayan kayıt/yükleme silinir
KILIT_ADI = ".kilit"
HAZIRLIK_ADI = "hazirlik"
_OTURUM_ADI = re.compile(r"^\d+-[0-9a-f]{8}$")
_KILITSIZ_BEKLE_SN = 10 * 60  # kilidi henüz yazılmamış (kurulmakta olan) klasöre dokunma


def _kilitle(f):
    if os.name == "nt":
        import msvcrt
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _kilidi_coz(f):
    if os.name == "nt":
        import msvcrt
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def varsayilan_kok():
    return Path(tempfile.gettempdir()) / KOK_ADI


def _bag_mi(st):
    """lstat sonucu sembolik bağ ya da (Windows) junction/yeniden ayrıştırma noktası mı?"""
    if stat.S_ISLNK(st.st_mode):
        return True
    return bool(getattr(st, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def kok_hazirla(kok):
    """Kök klasörü güvenle hazırlar: yoksa 0o700 ile açar; varsa gerçek bir klasör (bağ değil) ve
    sahibi geçerli kullanıcı olmalı, izinler 0o700'e çekilir. Güvensizse (bağ, başkasının, klasör
    değil) False ve neden döner: kayıtlar oraya yazılmaz (bkz. GeciciAlan.kur yedek yolu).

    Neden: paylaşımlı /tmp'li sistemlerde (Linux geliştirici kipi) başka bir yerel kullanıcı kökü
    önceden bağ ya da kendi klasörü olarak açıp kayıtları okuyabilirdi (siberguvenlik D4)."""
    kok = Path(kok)
    try:
        os.mkdir(kok, 0o700)
    except FileExistsError:
        pass
    except OSError as exc:
        return False, f"oluşturulamadı: {exc}"
    try:
        st = os.lstat(kok)
    except OSError as exc:
        return False, f"okunamadı: {exc}"
    if _bag_mi(st):
        return False, "bağ (symlink/junction)"
    if not stat.S_ISDIR(st.st_mode):
        return False, "klasör değil"
    if hasattr(os, "getuid") and st.st_uid != os.getuid():
        return False, f"sahibi başka kullanıcı (uid {st.st_uid})"
    if os.name != "nt" and stat.S_IMODE(st.st_mode) & 0o077:
        try:
            os.chmod(kok, 0o700)  # eski sürümün 0o755 açtığı kendi klasörümüz
        except OSError as exc:
            return False, f"izin düzeltilemedi: {exc}"
    return True, ""


def _icinde(yol, kok):
    """`yol` gerçekten `kok`un altında mı (sembolik bağ ve `..` çözülerek)?"""
    try:
        y = os.path.realpath(os.fspath(yol))
        k = os.path.realpath(os.fspath(kok))
    except (TypeError, ValueError, OSError):
        return False
    return y != k and os.path.commonpath([y, k]) == k


def oturum_canli_mi(klasor, simdi=None):
    """Başka bir oturum klasörünün sahibi süreç hâlâ çalışıyor mu? Kilit alınabiliyorsa hayır."""
    kilit = Path(klasor) / KILIT_ADI
    if not kilit.exists():
        try:
            yas = (simdi or time.time()) - Path(klasor).stat().st_mtime
        except OSError:
            return False
        return yas < _KILITSIZ_BEKLE_SN
    try:
        f = open(kilit, "a+b")
    except OSError:
        return True  # açılamıyor (Windows'ta sahibi tutuyor): canlı say
    try:
        try:
            _kilitle(f)
        except OSError:
            return True
        _kilidi_coz(f)
        return False
    finally:
        f.close()


class GeciciAlan:
    def __init__(self, kok=None, aralik=ARALIK_SN, yas=YAS_SN):
        self.kok = Path(kok) if kok else varsayilan_kok()
        self.aralik, self.yas = aralik, yas
        self.oturum = None
        self._kilit = None
        self._yedek_kok = None   # güvensiz kök yerine açılan mkdtemp kökü (kapanışta kaldırılır)
        self._blocks = None
        self._dur = threading.Event()
        self._zamanlayici = None
        self._lock = threading.Lock()

    # --- yaşam döngüsü ---------------------------------------------------------------
    def kur(self, gradio_env=True, zamanlayici=True):
        """Oturum klasörünü kurar (bir kez). GRADIO_TEMP_DIR'i ona yönlendirir; eski ölü oturumları siler."""
        with self._lock:
            if self.oturum is not None:
                return self.oturum
            guvenli, neden = kok_hazirla(self.kok)
            if not guvenli:
                # Güvenli yedek: bu sürece özel, rastgele adlı, 0o700 yeni bir kök (mkdtemp
                # önceden oluşturulmuş bir ada/bağa yazmaz). Kayıtlar yine ayrı ve kapanışta silinir;
                # yalnız bu kökün ölü oturumları sonraki açılışta toplanamaz.
                yedek = Path(tempfile.mkdtemp(prefix=KOK_ADI + "-"))
                log.warning("Geçici klasör kökü güvensiz (%s: %s); yerine %s kullanılıyor",
                            self.kok, neden, yedek)
                self.kok, self._yedek_kok = yedek, yedek
            oturum = self.kok / f"{os.getpid()}-{uuid.uuid4().hex[:8]}"
            os.mkdir(oturum, 0o700)
            f = open(oturum / KILIT_ADI, "a+b")
            try:
                _kilitle(f)
            except OSError:
                f.close()
                raise
            self.oturum, self._kilit = oturum, f
            if gradio_env:
                os.environ["GRADIO_TEMP_DIR"] = str(oturum)
            if zamanlayici and self.aralik:
                self._dur.clear()
                self._zamanlayici = threading.Thread(target=self._dongu, name="sesver-gecici-temizlik",
                                                     daemon=True)
                self._zamanlayici.start()
        self.eski_oturumlari_temizle()
        return oturum

    def kapat(self):
        """Kapanış: zamanlayıcıyı durdurur, oturum klasörünü tümüyle siler. Birden çok çağrı güvenli."""
        with self._lock:
            oturum, f = self.oturum, self._kilit
            self.oturum, self._kilit, self._blocks = None, None, None
            self._dur.set()
        if oturum is None:
            return False
        if f is not None:
            try:
                _kilidi_coz(f)
            except OSError:
                pass
            f.close()
        if _icinde(oturum, self.kok) and _OTURUM_ADI.match(oturum.name):
            shutil.rmtree(oturum, ignore_errors=True)
        if self._yedek_kok is not None:
            try:
                os.rmdir(self._yedek_kok)  # yalnız boşsa
            except OSError:
                pass
        return not oturum.exists()

    def _dongu(self):
        while not self._dur.wait(self.aralik):
            try:
                self.temizle()
            except Exception:  # noqa: BLE001 — temizlik hatası uygulamayı durdurmasın
                log.exception("Geçici dosya temizliği başarısız")

    # --- kullanım ----------------------------------------------------------------------
    def izle(self, blocks):
        """Gradio uygulaması: kullanıcı yüklemeleri (mikrofon kaydı dahil) `blocks.upload_file_set`'te."""
        self._blocks = blocks

    def hazirlik_klasoru(self):
        oturum = self.oturum or self.kur()
        d = oturum / HAZIRLIK_ADI
        d.mkdir(exist_ok=True)
        return d

    def bizim_mi(self, yol):
        return bool(yol) and self.oturum is not None and _icinde(yol, self.oturum)

    def dokun(self, *yollar):
        """Bu dosyalar şu an kullanılıyor: aralıklı temizlikte yaş yeniden başlar."""
        for y in yollar:
            if self.bizim_mi(y):
                try:
                    os.utime(y)
                except OSError:
                    pass

    def sil(self, *yollar):
        """Yalnız bu oturumun dosyalarını siler (ör. ses olarak kaydedilen kaydın geçici kopyaları)."""
        silinen = 0
        for y in dict.fromkeys(str(y) for y in yollar if y):
            if not self.bizim_mi(y) or os.path.basename(y) == KILIT_ADI:
                continue
            try:
                os.remove(y)
                silinen += 1
            except OSError:
                continue
            self._bos_ust_klasoru_sil(Path(y))
        return silinen

    def _bos_ust_klasoru_sil(self, yol):
        ust = yol.parent
        if ust != self.oturum and self.oturum is not None and _icinde(ust, self.oturum):
            try:
                ust.rmdir()  # yalnız boşsa
            except OSError:
                pass

    def temizle(self, simdi=None):
        """Aralıklı temizlik: YAS_SN boyunca kullanılmayan kullanıcı yüklemeleri ve hazırlık kopyaları."""
        if self.oturum is None:
            return []
        simdi = simdi or time.time()
        adaylar = set()
        hazirlik = self.oturum / HAZIRLIK_ADI
        if hazirlik.is_dir():
            adaylar.update(str(p) for p in hazirlik.iterdir() if p.is_file())
        yuklemeler = getattr(self._blocks, "upload_file_set", None)
        if yuklemeler:
            adaylar.update(str(p) for p in list(yuklemeler))
        silinen = []
        for y in sorted(adaylar):
            if not self.bizim_mi(y):
                continue
            try:
                if simdi - os.lstat(y).st_mtime <= self.yas:
                    continue
            except OSError:
                continue
            if self.sil(y):
                silinen.append(y)
        if yuklemeler is not None and silinen:
            yuklemeler.difference_update(silinen)
        self.eski_oturumlari_temizle(simdi)
        return silinen

    def eski_oturumlari_temizle(self, simdi=None):
        """Çökmüş/zorla kapatılmış SesVer süreçlerinden kalan oturum klasörleri (yalnız sesver-gecici/ altında)."""
        silinen = []
        try:
            cocuklar = list(self.kok.iterdir())
        except OSError:
            return silinen
        for d in cocuklar:
            if d == self.oturum or not _OTURUM_ADI.match(d.name) or d.is_symlink() or not d.is_dir():
                continue
            if oturum_canli_mi(d, simdi):
                continue
            shutil.rmtree(d, ignore_errors=True)
            if not d.exists():
                silinen.append(str(d))
        return silinen


_alan = GeciciAlan()
_atexit_kayitli = False


def kur():
    global _atexit_kayitli
    oturum = _alan.kur()
    if not _atexit_kayitli:
        # Normal çıkış (Ctrl+C, sys.exit). os._exit yolunda desktop.py kapat()'ı kendisi çağırır.
        atexit.register(_alan.kapat)
        _atexit_kayitli = True
    return oturum


def kapat():
    return _alan.kapat()


def izle(blocks):
    _alan.izle(blocks)


def hazirlik_klasoru():
    if _alan.oturum is None:
        kur()
    return _alan.hazirlik_klasoru()


def dokun(*yollar):
    _alan.dokun(*yollar)


def sil(*yollar):
    return _alan.sil(*yollar)


def temizle():
    return _alan.temizle()


def oturum():
    return _alan.oturum
