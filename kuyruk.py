"""SesVer üretim kuyruğu çekirdeği (arayüzden bağımsız; Gradio/torch içe aktarmaz).

- Öğeler sırayla, tek tek üretilir. Uzun öğe (>500 karakter) metin_bolme ile parçalara
  bölünür; her parça ayrı üretilir, en sonda ses_birlestirme ile tek WAV olur. Kısa öğe tek
  parçalı uzun öğe gibi işlenir (tek kod yolu).
- Durum her değişiklikte `kuyruk/kuyruk.json` dosyasına atomik yazılır. Uygulama kapanırsa
  biten parçalar kaybolmaz; açılışta yarıda kalan öğe "bekliyor"a döner ve kuyruk
  DURAKLATILMIŞ açılır: işçi kendiliğinden BAŞLAMAZ (kullanıcı "devam" demelidir).
- Bir öğe hata verirse kuyruk durmaz, sonrakine geçer; yalnız art arda iki öğe sistemik
  hatayla (model indirilemedi / disk dolu) düşerse kuyruk duraklatılır ve iki öğe de
  "bekliyor"a döner.
- "Durdur": şu anki PARÇA bitince durur (model.generate() güvenle kesilemez).
- Elle (kuyruksuz) üretim `elle_uretim()` bağlamıyla araya girer: işçi yeni parçaya başlamadan bekler.
- Uyku engeli yalnız işçi çalışırken açıktır (uyku_engeli.acik, işçi iş parçacığında).
- Aynı kuyruğu iki SesVer süreci işlemesin diye süreç kilidi (`kuyruk/.calisiyor.lock`) kullanılır.

Kayıtta metin düz yazıyla durur (yalnız yerel disk). Günlüğe metin ve dosya adı YAZILMAZ;
yalnız öğe kimliği, parça no, süre ve hata kodu yazılır. Kullanıcıya dönen hatalar kod taşır
(KuyrukHatasi.kod); arayüz kodları sayfa dilinde metne çevirir.
"""
import contextlib
import datetime
import json
import logging
import os
import re
import shutil
import threading
import time
import unicodedata
import uuid
from pathlib import Path

import metin_bolme

log = logging.getLogger("sesver")

ROOT = Path(__file__).resolve().parent
KUYRUK_DIR = ROOT / "kuyruk"
CIKTI_DIR = ROOT / "outputs"

SEMA = 1
KUYRUK_EN_FAZLA = 50
OGE_METIN_EN_FAZLA = 10_000
PARCA_EN_FAZLA = metin_bolme.EN_FAZLA  # elle üretimin sınırıyla aynı (500)
RASTGELE = "rastgele"
TURLER = ("kutuphane", "klon")
SISTEMIK_KODLAR = frozenset({"download", "disk"})
KLASOR_EKI = "AI-ile-uretildi"
GECICI_EK = ".yaziliyor.wav"
AD_EN_FAZLA = 60
UYKU_GEREKCESI = "SesVer: ses uretim kuyrugu"  # ASCII: powerd Türkçe harfli adı boş gösteriyor

# Öğe durumları
BEKLIYOR, URETILIYOR, BITTI, HATA = "bekliyor", "uretiliyor", "bitti", "hata"
# Kuyruk durumları
BOS, HAZIR, CALISIYOR, DURUYOR, DURAKLATILDI, TAMAMLANDI = (
    "bos", "hazir", "calisiyor", "duruyor", "duraklatildi", "tamamlandi")


class KuyrukHatasi(Exception):
    """Kullanıcı işleminin reddi. `kod`: tur_gecersiz, metin_bos, metin_uzun, rastgele_uzun,
    ref_yok, ref_kopyalanamadi, dolu, baska_surec, calisiyor, oge_yok, uretiliyor, durum_gecersiz."""

    def __init__(self, kod, **bilgi):
        super().__init__(kod)
        self.kod = kod
        self.bilgi = bilgi


# --- Dosya adları ---------------------------------------------------------------------------

_TR_ASCII = str.maketrans({"ı": "i", "İ": "I", "ş": "s", "Ş": "S", "ğ": "g", "Ğ": "G",
                           "ç": "c", "Ç": "C", "ö": "o", "Ö": "O", "ü": "u", "Ü": "U"})
_WIN_AYRILMIS = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}


def slug(metin, kelime=None, en_fazla=30):
    """ASCII, küçük harf, tireli kısa ad (Türkçe harfler çevrilir; çevrilemeyen yazı atılır)."""
    s = unicodedata.normalize("NFKD", (metin or "").translate(_TR_ASCII)).encode("ascii", "ignore").decode()
    kelimeler = re.findall(r"[a-z0-9]+", s.lower())
    if kelime:
        kelimeler = kelimeler[:kelime]
    out = "-".join(kelimeler)[:en_fazla].strip("-")
    return out


def dosya_adi(no, ses_adi, metin):
    """`NN_ses-adi_metnin-ilk-kelimeleri` (uzantısız, en fazla 60 karakter, Windows'ta geçerli)."""
    parcalar = [f"{int(no or 0):02d}", slug(ses_adi, en_fazla=24) or "ses", slug(metin, kelime=4, en_fazla=30) or "metin"]
    ad = "_".join(parcalar)[:AD_EN_FAZLA].rstrip("-_. ")
    if ad.split(".")[0].lower() in _WIN_AYRILMIS:
        ad = f"_{ad}"
    return ad


def _benzersiz(klasor, ad):
    aday, n = ad, 2
    while any((klasor / f"{aday}{ek}").exists() for ek in (".wav", "_efektli.wav", GECICI_EK)):
        aday = f"{ad}-{n}"
        n += 1
    return aday


def sure_metni(sn):
    sn = int(round(sn or 0))
    sa, kalan = divmod(sn, 3600)
    dk, s = divmod(kalan, 60)
    if sa:
        return f"{sa} sa {dk:02d} dk"
    if dk:
        return f"{dk} dk {s:02d} sn"
    return f"{s} sn"


# --- Süreç kilidi ---------------------------------------------------------------------------

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


class _SurecKilidi:
    def __init__(self, yol):
        self.yol = Path(yol)
        self._f = None

    @property
    def tutuluyor(self):
        return self._f is not None

    def al(self):
        if self._f is not None:
            return True
        self.yol.parent.mkdir(parents=True, exist_ok=True)
        f = open(self.yol, "a+b")  # noqa: SIM115 — kilit süresince açık kalır
        try:
            _kilitle(f)
        except OSError:
            f.close()
            return False
        self._f = f
        return True

    def birak(self):
        if self._f is None:
            return
        try:
            _kilidi_coz(self._f)
        except OSError:
            pass
        self._f.close()
        self._f = None

    def baskasinda_mi(self):
        if self._f is not None:
            return False
        if self.al():
            self.birak()
            return False
        return True


def _varsayilan_engel(gerekce):
    import uyku_engeli
    return uyku_engeli.acik(gerekce)


def _degistir(kaynak, hedef, deneme=3):
    """os.replace; Windows'ta antivirüs/dizinleyici kısa süre kilitleyebildiği için birkaç kez dener."""
    for i in range(deneme):
        try:
            os.replace(kaynak, hedef)
            return
        except PermissionError:
            if i == deneme - 1:
                raise
            time.sleep(0.05 * (i + 1))


def _ses_suresi(yol):
    try:
        import soundfile as sf
        return float(sf.info(str(yol)).duration)
    except Exception:  # noqa: BLE001 — süre bilgisi yalnız gösterim içindir
        return None


# --- Kuyruk ---------------------------------------------------------------------------------

class Kuyruk:
    """Kalıcı üretim kuyruğu.

    uret_fn(istek: dict, hedef: Path): istek["metin"] parçasını üretip `hedef` WAV'ına yazar;
        hata durumunda istisna fırlatır. istek: tur, metin, ses_id, ses_adi, ref_yol, ref_metin,
        duygu, kalite, oge_id, parca_no, parca_sayisi.
    efekt_fn(ham: Path, hedef: Path, efektler: list): efektli kopyayı yazar (isteğe bağlı).
    siniflandir(exc, oge) -> kod: hata kodu (cuda_oom, ram, disk, download, other …). Hata
        kaydını (hata_raporu.record_error, metin maskeli) da burada yapmak uygulamanın işidir.
    engel(gerekce) -> bağlam yöneticisi: uyku engeli (varsayılan uyku_engeli.acik).
    blok_fn() -> neden|None: doluysa (ör. GPU kurulumu sürüyor) kuyruk duraklatılır.
    temizlik_fn(): her parçadan sonra (gc / önbellek boşaltma).
    """

    def __init__(self, dizin=None, cikti_dir=None, uret_fn=None, efekt_fn=None, siniflandir=None,
                 engel=None, blok_fn=None, temizlik_fn=None, simdi=None, ceviri=None):
        self.dizin = Path(dizin or KUYRUK_DIR)
        self.cikti_dir = Path(cikti_dir or CIKTI_DIR)
        self.yol = self.dizin / "kuyruk.json"
        self._uret_fn = uret_fn
        self._efekt_fn = efekt_fn
        self._siniflandir = siniflandir
        self._engel = engel or _varsayilan_engel
        self._blok_fn = blok_fn
        self._temizlik_fn = temizlik_fn
        self._simdi = simdi or (lambda: datetime.datetime.now().astimezone())
        self._ceviri = ceviri or (lambda s, **kw: s.format(**kw) if kw else s)
        self._kilit = threading.RLock()
        self._cv = threading.Condition(self._kilit)
        self._surec_kilidi = _SurecKilidi(self.dizin / ".calisiyor.lock")
        self._isci = None
        self._dur = False
        self._elle = 0
        self._surum = 0
        self._son_sistemik = None
        self._durdurma_nedeni = None
        self.salt_okunur = False  # başka bir SesVer süreci bu kuyruğu işliyor
        self.onceki_bekleyen = 0  # açılışta önceki oturumdan kalan bekleyen öğe sayısı
        self.bozuk_kayit = None  # okunamayan kayıt kenara alındıysa yolu
        self.kayit_hatasi = None
        self._veri = self._yukle()
        if not self.salt_okunur:
            self._kurtar()

    # --- kayıt -----------------------------------------------------------------------------
    @staticmethod
    def _bos_veri():
        return {"sema": SEMA, "durum": BOS, "duraklatma": None, "oturum": None, "oturum_bitti": True,
                "oturum_sayac": 0, "ogeler": []}

    def _zaman(self):
        return self._simdi().isoformat(timespec="seconds")

    def _yukle(self):
        if not self.yol.exists():
            return self._bos_veri()
        try:
            veri = json.loads(self.yol.read_text(encoding="utf-8"))
            if not isinstance(veri, dict) or veri.get("sema") != SEMA or not isinstance(veri.get("ogeler"), list):
                raise ValueError("şema uyuşmuyor")
            for anahtar, deger in self._bos_veri().items():
                veri.setdefault(anahtar, deger)
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            damga = time.strftime("%Y%m%d-%H%M%S")
            kenar = self.yol.with_name(f"kuyruk.json.bozuk-{damga}")
            try:
                _degistir(self.yol, kenar)
                self.bozuk_kayit = kenar
            except OSError:
                self.bozuk_kayit = self.yol
            log.warning("kuyruk kaydı okunamadı (%s), boş kuyrukla açılıyor", type(exc).__name__)
            return self._bos_veri()
        if self._surec_kilidi.baskasinda_mi():
            self.salt_okunur = True
        return veri

    def _kaydet(self):
        self._surum += 1
        if self.salt_okunur:
            return
        gecici = self.yol.with_name("kuyruk.json.yaz")
        try:
            self.dizin.mkdir(parents=True, exist_ok=True)
            gecici.write_text(json.dumps(self._veri, ensure_ascii=False, indent=1), encoding="utf-8")
            _degistir(gecici, self.yol)
            self.kayit_hatasi = None
        except OSError as exc:
            self.kayit_hatasi = type(exc).__name__
            log.warning("kuyruk kaydı yazılamadı: %s", type(exc).__name__)
            with contextlib.suppress(OSError):
                gecici.unlink()

    def _yarim_dosyalari_sil(self):
        klasorler = [self.dizin / "parca"]
        if self._veri.get("oturum"):
            klasorler.append(self.cikti_dir / self._veri["oturum"])
        for klasor in klasorler:
            if klasor.is_dir():
                for yol in klasor.rglob(f"*{GECICI_EK}"):
                    with contextlib.suppress(OSError):
                        yol.unlink()

    def _kurtar(self):
        """Açılış: yarıda kalanı beklemeye al, eksik parça dosyalarını yeniden üretilecek say.
        İşçi BAŞLATILMAZ."""
        veri = self._veri
        degisti = False
        for oge in veri["ogeler"]:
            if oge.get("durum") == URETILIYOR:
                oge["durum"] = BEKLIYOR
                oge["yarida_kaldi"] = True
                degisti = True
            for p in oge.get("parcalar", []):
                if p.get("durum") == BITTI and not (p.get("dosya") and (self.dizin / p["dosya"]).is_file()):
                    p["durum"], p["dosya"] = BEKLIYOR, None
                    degisti = True
        self._yarim_dosyalari_sil()
        bekleyen = sum(o.get("durum") == BEKLIYOR for o in veri["ogeler"])
        if bekleyen:
            self.onceki_bekleyen = bekleyen
            if veri.get("durum") != DURAKLATILDI or not veri.get("duraklatma"):
                veri["duraklatma"] = {"neden": "yeniden_acilis", "zaman": self._zaman()}
                degisti = True
            if veri.get("durum") != DURAKLATILDI:
                veri["durum"] = DURAKLATILDI
                degisti = True
        elif veri.get("durum") in (CALISIYOR, DURUYOR, HAZIR, DURAKLATILDI):
            veri["durum"] = TAMAMLANDI if veri["ogeler"] else BOS
            veri["duraklatma"] = None
            veri["oturum_bitti"] = True
            degisti = True
        if degisti:
            self._kaydet()

    # --- okuma ----------------------------------------------------------------------------
    @property
    def calisiyor(self):
        return self._isci is not None and self._isci.is_alive()

    def _durum_adi(self):
        if self.calisiyor:
            return DURUYOR if self._dur else CALISIYOR
        return self._veri["durum"]

    def _bul(self, oid):
        for oge in self._veri["ogeler"]:
            if oge["id"] == oid:
                return oge
        raise KuyrukHatasi("oge_yok")

    def _oge_gorunum(self, oge):
        o = {k: v for k, v in oge.items() if k != "parcalar"}
        parcalar = oge.get("parcalar", [])
        o["parca_sayisi"] = len(parcalar)
        o["parca_bitti"] = sum(p.get("durum") == BITTI for p in parcalar)
        o["aktif_parca"] = None
        if oge["durum"] == URETILIYOR:
            o["aktif_parca"] = next((i + 1 for i, p in enumerate(parcalar) if p.get("durum") != BITTI), None)
        o["uzun"] = len(parcalar) > 1
        o["cikti"] = str(self.cikti_dir / oge["cikti"]) if oge.get("cikti") else None
        o["efektli"] = str(self.cikti_dir / oge["efektli"]) if oge.get("efektli") else None
        return o

    def tahmin(self):
        """Kalan süre (sn): bu kayıtta biten parçaların ölçülen saniye/karakter oranıyla; veri yoksa None."""
        with self._kilit:
            sure = karakter = kalan = 0
            for oge in self._veri["ogeler"]:
                for p in oge.get("parcalar", []):
                    if p.get("durum") == BITTI and p.get("sure_sn") is not None:
                        sure += p["sure_sn"]
                        karakter += len(p["metin"])
                    elif oge["durum"] in (BEKLIYOR, URETILIYOR):
                        kalan += len(p["metin"])
            if not karakter:
                return None
            return sure / karakter * kalan

    def durum(self):
        """Arayüz için anlık görüntü (kopya). `surum` her değişiklikte artar."""
        with self._kilit:
            ogeler = [self._oge_gorunum(o) for o in self._veri["ogeler"]]
            sayilar = {d: sum(o["durum"] == d for o in ogeler) for d in (BEKLIYOR, URETILIYOR, BITTI, HATA)}
            oturum = self._veri.get("oturum")
            return {
                "durum": self._durum_adi(), "surum": self._surum, "ogeler": ogeler, "sayilar": sayilar,
                "duraklatma": dict(self._veri["duraklatma"]) if self._veri.get("duraklatma") else None,
                "oturum_klasoru": str(self.cikti_dir / oturum) if oturum else None,
                "onceki_bekleyen": self.onceki_bekleyen, "salt_okunur": self.salt_okunur,
                "bozuk_kayit": str(self.bozuk_kayit) if self.bozuk_kayit else None,
                "kayit_hatasi": self.kayit_hatasi,
                "toplam_sure_sn": sum(o.get("sure_sn") or 0 for o in ogeler),
                "kalan_tahmini_sn": self.tahmin(), "elle_bekleyen": self._elle,
            }

    # --- değiştirme ------------------------------------------------------------------------
    def _yazilabilir_mi(self):
        if self.salt_okunur or self._surec_kilidi.baskasinda_mi():
            raise KuyrukHatasi("baska_surec")

    def _yeni_oge(self, tur, metin, ses_id=None, ses_adi=None, ref_kaynak=None, ref_metin=None,
                  duygu="Nötr", kalite="Dengeli", efektler=None, **_fazla):
        if tur not in TURLER:
            raise KuyrukHatasi("tur_gecersiz")
        metin = (metin or "").strip()
        if not metin:
            raise KuyrukHatasi("metin_bos")
        if len(metin) > OGE_METIN_EN_FAZLA:
            raise KuyrukHatasi("metin_uzun", en_fazla=OGE_METIN_EN_FAZLA, uzunluk=len(metin))
        if tur == "kutuphane":
            ses_id = ses_id or RASTGELE
            # Rastgele ses her parçada başka bir konuşmacı üretebilir: uzun metinde kabul edilmez.
            if ses_id == RASTGELE and len(metin) > PARCA_EN_FAZLA:
                raise KuyrukHatasi("rastgele_uzun", en_fazla=PARCA_EN_FAZLA)
            if ses_id != RASTGELE and not ref_kaynak:
                raise KuyrukHatasi("ref_yok")
        else:
            ses_id = None
            if not ref_kaynak:
                raise KuyrukHatasi("ref_yok")
        if ref_kaynak and not Path(ref_kaynak).is_file():
            raise KuyrukHatasi("ref_yok")
        parcalar = metin_bolme.bol(metin, PARCA_EN_FAZLA)
        return {
            "id": uuid.uuid4().hex[:12], "no": None, "tur": tur, "metin": metin, "ses_id": ses_id,
            "ses_adi": ses_adi or ("Rastgele ses" if ses_id == RASTGELE else ("Klon" if tur == "klon" else ses_id)),
            "ref": None, "_ref_kaynak": str(ref_kaynak) if ref_kaynak else None,
            "ref_metin": (ref_metin or "").strip() or None,
            "duygu": duygu or "Nötr", "kalite": kalite or "Dengeli", "efektler": list(efektler or []),
            "durum": BEKLIYOR,
            "parcalar": [{"metin": p.metin, "ara": metin_bolme.ara_suresi(p.sinir), "durum": BEKLIYOR,
                          "dosya": None, "sure_sn": None} for p in parcalar],
            "hata_kodu": None, "hata_turu": None, "hata_parca": None, "son_hata_kodu": None,
            "cikti": None, "efektli": None, "eklenme": self._zaman(), "baslangic": None, "bitis": None,
            "sure_sn": 0.0, "ses_sn": None, "yarida_kaldi": False,
        }

    def ekle(self, tur, metin, **ayarlar):
        """Tek öğe ekler; doğrulama hatasında KuyrukHatasi. Eklenen öğenin görünümünü döndürür."""
        return self.ekle_toplu([dict(ayarlar, tur=tur, metin=metin)])[0]

    def ekle_toplu(self, istekler):
        """Hepsi ya da hiçbiri: bir istek geçersizse ya da sınır aşılırsa hiçbir şey eklenmez."""
        with self._kilit:
            self._yazilabilir_mi()
            yeni = []
            for sira, istek in enumerate(istekler):
                try:
                    yeni.append(self._yeni_oge(**istek))
                except KuyrukHatasi as exc:
                    exc.bilgi.setdefault("sira", sira)
                    raise
            if len(self._veri["ogeler"]) + len(yeni) > KUYRUK_EN_FAZLA:
                raise KuyrukHatasi("dolu", en_fazla=KUYRUK_EN_FAZLA,
                                   kalan=max(0, KUYRUK_EN_FAZLA - len(self._veri["ogeler"])))
            kopyalar = []
            try:
                for oge in yeni:
                    kaynak = oge.pop("_ref_kaynak")
                    if kaynak:
                        hedef = self.dizin / "ref" / f"{oge['id']}{Path(kaynak).suffix.lower() or '.wav'}"
                        hedef.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(kaynak, hedef)
                        kopyalar.append(hedef)
                        oge["ref"] = hedef.relative_to(self.dizin).as_posix()
            except OSError as exc:
                for yol in kopyalar:
                    with contextlib.suppress(OSError):
                        yol.unlink()
                raise KuyrukHatasi("ref_kopyalanamadi") from exc
            self._veri["ogeler"].extend(yeni)
            if not self.calisiyor and self._veri["durum"] in (BOS, TAMAMLANDI):
                self._veri["durum"] = HAZIR
            self._kaydet()
            log.info("kuyruk: %d öğe eklendi (%s)", len(yeni),
                     ", ".join(f"{o['id']}:{len(o['parcalar'])} parça" for o in yeni))
            return [self._oge_gorunum(o) for o in yeni]

    def _oge_dosyalarini_sil(self, oge):
        if oge.get("ref"):
            with contextlib.suppress(OSError):
                (self.dizin / oge["ref"]).unlink()
        shutil.rmtree(self.dizin / "parca" / oge["id"], ignore_errors=True)

    def _durumu_duzelt(self):
        """İşçi çalışmıyorken öğe listesine göre kuyruk durumunu tutarlı tutar."""
        if self.calisiyor:
            return
        ogeler = self._veri["ogeler"]
        if not ogeler:
            self._veri.update(durum=BOS, duraklatma=None, oturum_bitti=True)
            self.onceki_bekleyen = 0
        elif not any(o["durum"] == BEKLIYOR for o in ogeler):
            self._veri.update(durum=TAMAMLANDI, duraklatma=None, oturum_bitti=True)
            self.onceki_bekleyen = 0
        elif self._veri["durum"] in (BOS, TAMAMLANDI):
            self._veri["durum"] = HAZIR

    def cikar(self, oid):
        """Başlamamış (ya da biten/hatalı) öğeyi listeden çıkarır; üretilen dosyalara dokunmaz."""
        with self._kilit:
            self._yazilabilir_mi()
            oge = self._bul(oid)
            if oge["durum"] == URETILIYOR:
                raise KuyrukHatasi("uretiliyor")
            self._veri["ogeler"].remove(oge)
            self._oge_dosyalarini_sil(oge)
            self._durumu_duzelt()
            self._kaydet()

    def _tasi(self, oid, yon):
        with self._kilit:
            self._yazilabilir_mi()
            ogeler = self._veri["ogeler"]
            oge = self._bul(oid)
            if oge["durum"] != BEKLIYOR:
                return False
            i = ogeler.index(oge)
            j = i + yon
            while 0 <= j < len(ogeler) and ogeler[j]["durum"] != BEKLIYOR:
                j += yon
            if not 0 <= j < len(ogeler):
                return False
            ogeler[i], ogeler[j] = ogeler[j], ogeler[i]
            self._kaydet()
            return True

    def yukari(self, oid):
        return self._tasi(oid, -1)

    def asagi(self, oid):
        return self._tasi(oid, +1)

    def yeniden_dene(self, oid):
        """Hatalı öğeyi sona alıp yeniden beklemeye koyar; biten parçaları korunur (kaldığı yerden)."""
        with self._kilit:
            self._yazilabilir_mi()
            oge = self._bul(oid)
            if oge["durum"] != HATA:
                raise KuyrukHatasi("durum_gecersiz")
            self._beklemeye_al(oge)
            self._veri["ogeler"].remove(oge)
            self._veri["ogeler"].append(oge)
            self._durumu_duzelt()
            self._kaydet()

    def bitenleri_temizle(self):
        with self._kilit:
            self._yazilabilir_mi()
            biten = [o for o in self._veri["ogeler"] if o["durum"] == BITTI]
            for oge in biten:
                self._veri["ogeler"].remove(oge)
                self._oge_dosyalarini_sil(oge)
            self._durumu_duzelt()
            self._kaydet()
            return len(biten)

    def temizle(self):
        """Kuyruğu boşaltır: kayıt, referans kopyaları ve ara parçalar silinir; çıktılar kalır."""
        with self._kilit:
            if self.calisiyor:
                raise KuyrukHatasi("calisiyor")
            self._yazilabilir_mi()
            for alt in ("ref", "parca"):
                shutil.rmtree(self.dizin / alt, ignore_errors=True)
            self._veri = self._bos_veri()
            self.onceki_bekleyen = 0
            self._kaydet()

    # --- çalıştırma ------------------------------------------------------------------------
    def baslat(self):
        """İşçiyi başlatır (bekleyen yoksa ya da zaten çalışıyorsa False). Kendiliğinden çağrılmaz."""
        with self._kilit:
            if self.calisiyor:
                return False
            self._yazilabilir_mi()
            if not any(o["durum"] == BEKLIYOR for o in self._veri["ogeler"]):
                return False
            if not self._surec_kilidi.al():
                raise KuyrukHatasi("baska_surec")
            self._dur = False
            self._son_sistemik = None
            self._durdurma_nedeni = None
            self.onceki_bekleyen = 0
            self._veri.update(durum=CALISIYOR, duraklatma=None)
            if self._veri.get("oturum_bitti") or not self._veri.get("oturum"):
                self._veri.update(oturum=None, oturum_bitti=False, oturum_sayac=0)
            self._kaydet()
            self._isci = threading.Thread(target=self._calis, name="sesver-kuyruk", daemon=True)
            self._isci.start()
            log.info("kuyruk başladı: %d bekleyen öğe", sum(o["durum"] == BEKLIYOR for o in self._veri["ogeler"]))
            return True

    def durdur(self):
        """Şu anki parça bitince durur. Çalışmıyorsa False."""
        with self._cv:
            if not self.calisiyor:
                return False
            self._dur = True
            self._surum += 1
            self._cv.notify_all()
            return True

    def bekle(self, timeout=None):
        isci = self._isci
        if isci is not None:
            isci.join(timeout)
        return not self.calisiyor

    @contextlib.contextmanager
    def elle_uretim(self):
        """Elle üretim bu bağlam içindeyken işçi yeni parçaya başlamaz (şu anki parça biter)."""
        with self._cv:
            self._elle += 1
            self._surum += 1
        try:
            yield
        finally:
            with self._cv:
                self._elle -= 1
                self._surum += 1
                self._cv.notify_all()

    def _calis(self):
        try:
            with self._engel(UYKU_GEREKCESI):
                while True:
                    is_ = self._siradaki_is()
                    if is_ is None:
                        break
                    oge, parca_no = is_
                    if parca_no is None:
                        self._tamamla(oge)
                    else:
                        self._parca_uret(oge, parca_no)
                    if self._temizlik_fn:
                        try:
                            self._temizlik_fn()
                        except Exception as exc:  # noqa: BLE001
                            log.warning("kuyruk: temizlik başarısız (%s)", type(exc).__name__)
        except Exception as exc:  # noqa: BLE001 — işçi hatası kuyruğu bozmasın; beklemeye alınır
            log.exception("kuyruk işçisi beklenmedik hata: %s", type(exc).__name__)
            self._durdurma_nedeni = {"neden": "beklenmeyen"}
        finally:
            with self._cv:
                self._bitir()
            self._surec_kilidi.birak()

    def _oturum_klasoru(self):
        """Bu çalıştırmanın çıktı klasörü (ilk öğede oluşturulur): outputs/kuyruk/<tarih_saat>_AI-ile-uretildi."""
        if not self._veri.get("oturum"):
            ad = f"{self._simdi().strftime('%Y-%m-%d_%H-%M')}_{KLASOR_EKI}"
            aday, n = ad, 2
            while (self.cikti_dir / "kuyruk" / aday).exists():
                aday = f"{ad}-{n}"
                n += 1
            self._veri["oturum"] = f"kuyruk/{aday}"
        klasor = self.cikti_dir / self._veri["oturum"]
        klasor.mkdir(parents=True, exist_ok=True)
        return klasor

    def _siradaki_is(self):
        """(öğe, parça indeksi) ya da (öğe, None: birleştir/bitir) ya da None (dur)."""
        with self._cv:
            while self._elle > 0 and not self._dur and not self._durdurma_nedeni:
                self._cv.wait(0.5)
            if self._durdurma_nedeni:
                return None
            if self._dur:
                self._durdurma_nedeni = {"neden": "kullanici"}
                return None
            if self._blok_fn:
                blok = self._blok_fn()
                if blok:
                    self._durdurma_nedeni = {"neden": "blok", "ayrinti": str(blok)}
                    return None
            ogeler = self._veri["ogeler"]
            oge = next((o for o in ogeler if o["durum"] == URETILIYOR), None) or \
                next((o for o in ogeler if o["durum"] == BEKLIYOR), None)
            if oge is None:
                return None
            if oge["durum"] == BEKLIYOR:
                oge["durum"] = URETILIYOR
                oge["baslangic"] = oge.get("baslangic") or self._zaman()
                if oge.get("no") is None:
                    self._veri["oturum_sayac"] = int(self._veri.get("oturum_sayac") or 0) + 1
                    oge["no"] = self._veri["oturum_sayac"]
                self._oturum_klasoru()
                self._kaydet()
            parca_no = next((i for i, p in enumerate(oge["parcalar"]) if p["durum"] != BITTI), None)
            return oge, parca_no

    def _istek(self, oge, i):
        return {
            "tur": oge["tur"], "metin": oge["parcalar"][i]["metin"], "ses_id": oge.get("ses_id"),
            "ses_adi": oge.get("ses_adi"), "ref_yol": str(self.dizin / oge["ref"]) if oge.get("ref") else None,
            "ref_metin": oge.get("ref_metin"), "duygu": oge.get("duygu"), "kalite": oge.get("kalite"),
            "oge_id": oge["id"], "parca_no": i + 1, "parca_sayisi": len(oge["parcalar"]),
        }

    def _kod(self, exc, oge):
        if self._siniflandir:
            try:
                return str(self._siniflandir(exc, dict(oge)) or "other")
            except Exception:  # noqa: BLE001
                return "other"
        return getattr(exc, "kod", None) or "other"

    def _parca_uret(self, oge, i):
        with self._kilit:
            istek = self._istek(oge, i)
        klasor = self.dizin / "parca" / oge["id"]
        klasor.mkdir(parents=True, exist_ok=True)
        gecici = klasor / f"{i + 1:03d}{GECICI_EK}"
        son = klasor / f"{i + 1:03d}.wav"
        t0 = time.monotonic()
        try:
            if self._uret_fn is None:
                raise RuntimeError("uret_fn tanımlı değil")
            self._uret_fn(istek, gecici)
            if not gecici.is_file():
                raise RuntimeError("üretim dosyası yazılmadı")
            _degistir(gecici, son)
        except Exception as exc:  # noqa: BLE001 — öğe hatası kuyruğu durdurmaz
            with contextlib.suppress(OSError):
                gecici.unlink()
            kod = self._kod(exc, oge)
            with self._cv:
                self._hata(oge, i, exc, kod, time.monotonic() - t0)
            return
        sure = time.monotonic() - t0
        with self._cv:
            p = oge["parcalar"][i]
            p.update(durum=BITTI, dosya=son.relative_to(self.dizin).as_posix(), sure_sn=round(sure, 4))
            oge["sure_sn"] = round((oge.get("sure_sn") or 0) + sure, 3)
            self._son_sistemik = None
            self._kaydet()
        log.info("kuyruk: öğe %s parça %d/%d bitti (%.1f sn)", oge["id"], i + 1, len(oge["parcalar"]), sure)
        if all(p["durum"] == BITTI for p in oge["parcalar"]):
            self._tamamla(oge)

    def _tamamla(self, oge):
        """Parçaları birleştirir (gerekirse efekt uygular), açıklayıcı adla oturum klasörüne yazar."""
        import ses_birlestirme

        with self._kilit:
            dosyalar = [self.dizin / p["dosya"] for p in oge["parcalar"]]
            aralar = [p["ara"] for p in oge["parcalar"][:-1]]
            klasor = self._oturum_klasoru()
            ad = _benzersiz(klasor, dosya_adi(oge["no"], oge.get("ses_adi"), oge["metin"]))
            efektler = list(oge.get("efektler") or [])
        gecici, son = klasor / f"{ad}{GECICI_EK}", klasor / f"{ad}.wav"
        efektli_gecici, efektli_son = klasor / f"{ad}_efektli{GECICI_EK}", klasor / f"{ad}_efektli.wav"
        efektli = False
        try:
            if len(dosyalar) == 1:
                shutil.copyfile(dosyalar[0], gecici)
                ses_sn = _ses_suresi(gecici)
            else:
                ses_sn = ses_birlestirme.birlestir_dosyalar(dosyalar, gecici, aralar)
            if efektler and self._efekt_fn:
                self._efekt_fn(gecici, efektli_gecici, efektler)
                efektli = efektli_gecici.is_file()
            _degistir(gecici, son)
            if efektli:
                _degistir(efektli_gecici, efektli_son)
        except Exception as exc:  # noqa: BLE001
            for yol in (gecici, efektli_gecici):
                with contextlib.suppress(OSError):
                    yol.unlink()
            kod = self._kod(exc, oge)
            with self._cv:
                self._hata(oge, None, exc, kod, 0.0)
            return
        with self._cv:
            oge.update(durum=BITTI, cikti=son.relative_to(self.cikti_dir).as_posix(),
                       efektli=efektli_son.relative_to(self.cikti_dir).as_posix() if efektli else None,
                       ses_sn=round(ses_sn, 2) if ses_sn else None, bitis=self._zaman(),
                       hata_kodu=None, hata_turu=None, hata_parca=None, yarida_kaldi=False)
            self._kaydet()
            self._ozet_yaz()
        shutil.rmtree(self.dizin / "parca" / oge["id"], ignore_errors=True)
        log.info("kuyruk: öğe %s bitti (%d parça)", oge["id"], len(oge["parcalar"]))

    @staticmethod
    def _beklemeye_al(oge):
        oge.update(durum=BEKLIYOR, hata_kodu=None, hata_turu=None, hata_parca=None, bitis=None, yarida_kaldi=False)

    def _hata(self, oge, i, exc, kod, sure):
        """Kilit içinde çağrılır. Öğe hata olur; art arda ikinci sistemik hatada kuyruk duraklatılır."""
        oge.update(durum=HATA, hata_kodu=kod, hata_turu=type(exc).__name__,
                   hata_parca=(i + 1) if i is not None else None, bitis=self._zaman(),
                   sure_sn=round((oge.get("sure_sn") or 0) + sure, 3))
        log.info("kuyruk: öğe %s hata kod=%s tür=%s parça=%s", oge["id"], kod, type(exc).__name__,
                 oge["hata_parca"] or "-")
        if kod in SISTEMIK_KODLAR:
            onceki = next((o for o in self._veri["ogeler"] if o["id"] == self._son_sistemik), None)
            if onceki is not None and onceki is not oge and onceki["durum"] == HATA:
                for o in (onceki, oge):
                    self._beklemeye_al(o)
                    o["son_hata_kodu"] = kod
                self._durdurma_nedeni = {"neden": kod}
                self._son_sistemik = None
                log.warning("kuyruk: art arda sistemik hata (%s), kuyruk duraklatıldı", kod)
            else:
                self._son_sistemik = oge["id"]
        else:
            self._son_sistemik = None
        self._kaydet()
        self._ozet_yaz()

    def _bitir(self):
        """İşçi biterken (kilit içinde): kalan iş varsa duraklat, yoksa tamamla."""
        for oge in self._veri["ogeler"]:
            if oge["durum"] == URETILIYOR:  # durdurma parça arasında geldi: kaldığı yerden sürecek
                oge["durum"] = BEKLIYOR
        bekleyen = any(o["durum"] == BEKLIYOR for o in self._veri["ogeler"])
        neden = self._durdurma_nedeni
        if bekleyen:
            self._veri.update(durum=DURAKLATILDI,
                              duraklatma=dict(neden or {"neden": "beklenmeyen"}, zaman=self._zaman()))
        else:
            self._veri.update(durum=TAMAMLANDI if self._veri["ogeler"] else BOS, duraklatma=None, oturum_bitti=True)
        self._dur = False
        self._durdurma_nedeni = None
        self._kaydet()
        self._ozet_yaz()
        log.info("kuyruk durdu: %s", self._veri["durum"])

    # --- özet dosyası ----------------------------------------------------------------------
    def ozet_metni(self):
        c = self._ceviri
        with self._kilit:
            ogeler = self._veri["ogeler"]
            sayilar = {d: sum(o["durum"] == d for o in ogeler) for d in (BITTI, HATA, BEKLIYOR, URETILIYOR)}
            satirlar = [
                c("SesVer üretim kuyruğu — AI ile üretildi"),
                c("Güncellendi: {zaman}", zaman=self._zaman()),
                c("Bitti: {bitti} · Hata: {hata} · Bekliyor: {bekliyor} · Üretiliyor: {uretiliyor}",
                  bitti=sayilar[BITTI], hata=sayilar[HATA], bekliyor=sayilar[BEKLIYOR], uretiliyor=sayilar[URETILIYOR]),
                c("Toplam üretim süresi: {sure}", sure=sure_metni(sum(o.get("sure_sn") or 0 for o in ogeler))),
                "",
            ]
            etiket = {BITTI: c("bitti"), HATA: c("hata"), BEKLIYOR: c("bekliyor"), URETILIYOR: c("üretiliyor")}
            for oge in sorted(ogeler, key=lambda o: (o.get("no") is None, o.get("no") or 0)):
                no = f"{oge['no']:02d}" if oge.get("no") else "--"
                parcalar = oge["parcalar"]
                biten = sum(p["durum"] == BITTI for p in parcalar)
                ayrinti = Path(oge["cikti"]).name if oge.get("cikti") else ""
                if oge["durum"] == HATA:
                    ayrinti = c("hata kodu: {kod}", kod=oge.get("hata_kodu") or "other")
                ozet = oge["metin"][:40].replace("\n", " ") + ("…" if len(oge["metin"]) > 40 else "")
                satirlar.append(f"{no}  {etiket.get(oge['durum'], oge['durum']):<11} "
                                f"{sure_metni(oge.get('sure_sn')):>10}  {biten}/{len(parcalar):<3} "
                                f"{ayrinti}  | {ozet}")
            return "\n".join(satirlar) + "\n"

    def _ozet_yaz(self):
        if not self._veri.get("oturum") or self.salt_okunur:
            return
        klasor = self.cikti_dir / self._veri["oturum"]
        try:
            klasor.mkdir(parents=True, exist_ok=True)
            gecici = klasor / "ozet.txt.yaz"
            gecici.write_text(self.ozet_metni(), encoding="utf-8")
            _degistir(gecici, klasor / "ozet.txt")
        except OSError as exc:
            log.warning("kuyruk: ozet.txt yazılamadı (%s)", type(exc).__name__)
