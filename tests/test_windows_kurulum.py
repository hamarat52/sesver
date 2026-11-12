"""Windows kurulum sihirbazı ↔ WINDOWS_BASLAT.bat yalnız-kurulum kipi (statik sınamalar).

Bu makinede Windows/Inno Setup yok; gerçek çalıştırma CI'dadır
(.github/workflows/windows-installer.yml). Burada sınananlar:

* Durum satırı biçimi tek yerde (tools/kurulum_durum_bicimi.py): bat'ın yazdığı her
  satır ayrıştırılabilir, iss'teki sabitler ve Pascal ayrıştırıcının Python karşılığı
  aynı sonucu verir.
* Bat'ın goto akışı: yalnız-kurulum kipinde hiçbir ``pause`` satırına ve SesVer'i
  başlatan satırlara ulaşılamaz (normal kipte hepsine ulaşılır — çözümleyici boş değil).
* Bat CRLF, komut satırları ASCII; iss [Code] blok dengesi ve [CustomMessages] TR+EN.
"""
import importlib
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

kd = importlib.import_module("kurulum_durum_bicimi")

BAT_YOLU = ROOT / "WINDOWS_BASLAT.bat"
ISS_YOLU = ROOT / "windows" / "SesVer.iss"


def bat_satirlari():
    raw = BAT_YOLU.read_bytes()
    return raw.decode("utf-8").split("\r\n")


def iss_metni():
    raw = ISS_YOLU.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf"), "SesVer.iss UTF-8 BOM'lu olmalı"
    return raw[3:].decode("utf-8")


def iss_bolumu(ad):
    metin = iss_metni()
    m = re.search(r"^\[" + re.escape(ad) + r"\]\n(.*?)(?=^\[[A-Za-z]+\]\n|\Z)", metin, re.M | re.S)
    assert m, f"[{ad}] bölümü yok"
    return m.group(1)


def pascal_govde(kod, tur, ad):
    """[Code] içindeki ``function Ad(...)`` / ``procedure Ad(...)`` gövdesi (ilk sütundaki end;'e dek)."""
    m = re.search(rf"{tur} {ad}\(.*?\nend;", kod, re.S)
    assert m, f"{tur} {ad} yok"
    return m.group(0)


# ---------------------------------------------------------------- [Code] statik denetimi (ISCC'siz)
# Bu makinede ISCC yok; Inno Setup'ın Pascal Script'ten ÖNCE yaptığı satır temelli ayrıştırmanın
# bilinen tuzakları burada yakalanır (1.4.1: satır başındaki "[" → "Invalid section tag", CI kırmızı).

ISPP_YONERGELERI = {"define", "undef", "if", "ifdef", "ifndef", "ifexist", "ifnexist", "elif", "else", "endif",
                    "include", "pragma", "emit", "expr", "insert", "append", "error", "sub", "endsub", "for",
                    "redim", "dim"}


def code_satirlari(metin):
    """[Code] başlığından sonraki satırlar: (satır_no, satır). Inno [Code]'u dosyanın sonuna kadar okur."""
    satirlar = metin.split("\n")
    bas = next(i for i, s in enumerate(satirlar) if s.strip().lower() == "[code]")
    return [(i + 1, s) for i, s in enumerate(satirlar) if i > bas]


def code_satir_sorunlari(metin):
    """Inno'nun satır ayrıştırıcısını bozan satırlar. Yorum ya da metin içinde olsa da sayılır:
    Inno bölüm başlığını Pascal'dan önce, satırın ilk boş olmayan karakterine bakarak arar."""
    sorunlar = []
    for no, s in code_satirlari(metin):
        bas = s.lstrip(" \t")
        if bas.startswith("["):
            sorunlar.append((no, "satır başında '[' (Inno bölüm başlığı sanar: Invalid section tag)", s))
        elif bas.startswith("#"):
            kelime = re.match(r"#\s*([A-Za-z]*)", bas).group(1).lower()
            if kelime not in ISPP_YONERGELERI:
                sorunlar.append((no, "satır başında '#' (ISPP yönergesi sanılır; ör. #13#10'u önceki satıra al)", s))
    return sorunlar


def pascal_jetonlari(kod):
    """Yorumları ({ }, (* *), //) ve 'metin' sabitlerini atıp anahtar kelimeleri döndürür."""
    kod = re.sub(r"\{[^}]*\}|\(\*.*?\*\)", " ", kod, flags=re.S)
    temiz = []
    for satir in kod.split("\n"):
        satir = re.sub(r"'(?:[^']|'')*'", "''", satir)
        temiz.append(satir.split("//", 1)[0])
    return re.findall(r"[A-Za-z_][A-Za-z0-9_]*", "\n".join(temiz))


def pascal_blok_dengesi(kod):
    """begin/try/case/record ... end sayısı. Dengesiz blok ISCC'de 'Identifier expected' gibi
    hatalara yol açar. Döner: (açan, kapanan)."""
    jetonlar = [j.lower() for j in pascal_jetonlari(kod)]
    acan = sum(jetonlar.count(k) for k in ("begin", "try", "case", "record"))
    return acan, jetonlar.count("end")


# ---------------------------------------------------------------- bat akış çözümleyici

GOTO = re.compile(r"\bgoto\s+:([A-Za-z0-9_]+)", re.I)
CALL_ETIKET = re.compile(r"\bcall\s+:([A-Za-z0-9_]+)", re.I)
YK_DOGRU = '"%sv_yk%"=="1"'


def _kosul_durumu(s, kip):
    """Satırın eylemi (goto/exit) bu kipte: 'her zaman', 'asla' ya da 'belki' çalışır."""
    d = s.lower()
    yk_kosulu = YK_DOGRU in d
    if not d.startswith("if ") and "||" not in d and "&&" not in d:
        return "her zaman"
    if not yk_kosulu:
        return "belki"
    olumsuz = ("if not " + YK_DOGRU) in d
    dogru = (kip == "yk") != olumsuz
    if not dogru:
        return "asla"
    # Yalnız SV_YK koşuluna bağlıysa kesin; başka koşul da varsa (if errorlevel 1 if ...) belki.
    tek = d.startswith("if " + YK_DOGRU) or d.startswith("if not " + YK_DOGRU)
    return "her zaman" if tek else "belki"


def bat_akisi(kip):
    """(ulaşılan satır indeksleri, pause indeksleri, etiketler) — kip: 'yk' ya da 'normal'.

    Muhafazakâr çözümleme: SV_YK dışındaki tüm koşullar iki yönlü kabul edilir.
    ``call :etiket`` alt yordamı ayrı bir kök olarak gezilir ve çağıranda sonraki satıra
    dönülür; ``exit`` o çerçeveyi bitirir; ``call "%~f0"`` (kendini yeniden çağırma)
    satır 0'dan başlar ki zaten kök.
    """
    satirlar = bat_satirlari()
    etiketler = {}
    for i, ham in enumerate(satirlar):
        s = ham.strip()
        if s.startswith(":") and not s.startswith("::"):
            etiketler[s[1:].split()[0].lower()] = i
    pauses = {i for i, ham in enumerate(satirlar) if re.match(r"^@?pause\b", ham.strip(), re.I)}

    ulasilan, yigin = set(), [0]
    while yigin:
        i = yigin.pop()
        if i >= len(satirlar) or i in ulasilan:
            continue
        ulasilan.add(i)
        s = satirlar[i].strip().lstrip("@")
        d = s.lower()
        if not s or d.startswith("rem ") or d == "rem" or s.startswith(":"):
            yigin.append(i + 1)
            continue
        for ad in CALL_ETIKET.findall(s):
            yigin.append(etiketler[ad.lower()])
        hedefler = [etiketler[h.lower()] for h in GOTO.findall(s)]
        cikis = re.search(r"(^|\s)exit(\s|$)", d) is not None
        durum = _kosul_durumu(s, kip)
        if hedefler or cikis:
            if durum in ("asla", "belki"):
                yigin.append(i + 1)
            if durum in ("her zaman", "belki"):
                yigin.extend(hedefler)
        else:
            yigin.append(i + 1)
    return ulasilan, pauses, etiketler


class BatAkisTests(unittest.TestCase):
    def test_for_f_komutlari_cmd_tirnak_soymasina_dayanikli(self):
        """``for /f ... in (`komut`)`` komutu ``cmd /c`` ile çalışır. cmd, komut tırnakla
        başlıyorsa ve tam iki tırnak + aradaki adın boşluksuz bir dosya olması koşulları
        tutmuyorsa İLK ve SON tırnağı soyar (``cmd /?``, "old behavior"). 1.3.1'in ilk
        CI koşusu bu yüzden düştü: ``"%PYEXE%" -c "..." `` dört tırnaklıydı, soyulunca
        komut bozuldu ve Python sürümü boş okundu. Kural: for /f komutunda en fazla iki
        tırnak olur, ikisi de yalnız başlangıçtaki boşluksuz program yolunu sarar (soyulması
        zararsız) ve ``python -c`` kullanılmaz (çıktı geçici dosyaya yazdırılıp set /p ile okunur).
        """
        komut_re = re.compile(r"\bin\s*\(`(.*)`\)\s*do\b", re.I)
        bulunan = 0
        for i, ham in enumerate(bat_satirlari()):
            s = ham.strip()
            if s.lower().startswith("rem") or not re.match(r"for\s+/f\b", s, re.I):
                continue
            m = komut_re.search(s)
            if not m:
                continue
            bulunan += 1
            komut = m.group(1)
            self.assertNotRegex(komut, r"\s-c\s", f"satır {i + 1}: for /f içinde python -c: {s}")
            self.assertLessEqual(komut.count('"'), 2, f"satır {i + 1}: for /f komutunda 2'den fazla tırnak: {s}")
            if komut.count('"') == 2:
                bas = re.match(r'^"([^"]*)"\s', komut)
                assert bas is not None, f"satır {i + 1}: tırnaklar program yolunu sarmıyor: {s}"
                self.assertNotRegex(bas.group(1), r"[\s&<>()@^|]",
                                    f"satır {i + 1}: soyulan program yolunda boşluk/özel karakter: {s}")
        self.assertGreaterEqual(bulunan, 2)  # --onerilen-etiket satırları

    def test_python_cikti_okumalari_gecici_dosyadan(self):
        bat = "\n".join(bat_satirlari())
        for tmp, degisken in (("sesver_pyv.tmp", "SV_PYV"), ("sesver_torch_etiket.tmp", "SV_TORCH_ETIKET")):
            self.assertIn(f'>"{tmp}" 2>nul', bat)
            self.assertIn(f'if exist "{tmp}" set /p {degisken}=<"{tmp}"', bat)
            self.assertIn(f'del /f /q "{tmp}" >nul 2>nul', bat)
        # Sürüm okunamazsa sessizce değil, ayrı bir uyarıyla düşer.
        kilit_sec = bat.split("\n:kilit_sec\n")[1].split("\n:kilitli_kur\n")[0]
        self.assertIn('if "%SV_PYV%"=="" goto :kilit_sec_okunamadi', kilit_sec)
        self.assertIn("[UYARI] Python surumu okunamadi", kilit_sec)

    def test_goto_hedefleri_etiketli_ve_var(self):
        satirlar = bat_satirlari()
        _, _, etiketler = bat_akisi("normal")
        for i, ham in enumerate(satirlar):
            s = ham.strip()
            if s.lower().startswith("rem") or s.startswith(":"):
                continue
            for kelime in re.findall(r"\bgoto\s+(\S+)", s, re.I):
                self.assertTrue(kelime.startswith(":"), f"satır {i + 1}: goto iki noktasız: {s}")
            for ad in GOTO.findall(s) + CALL_ETIKET.findall(s):
                self.assertIn(ad.lower(), etiketler, f"satır {i + 1}: tanımsız etiket :{ad}")

    def test_yalniz_kurulum_kipinde_pause_yok(self):
        ulasilan, pauses, _ = bat_akisi("yk")
        self.assertEqual(len(pauses), 5)  # mevcut normal-kip pause'ları (bkz. rapor)
        self.assertEqual(sorted(p + 1 for p in pauses & ulasilan), [],
                         "yalnız-kurulum kipinde ulaşılabilen pause satırları")

    def test_normal_kipte_tum_pauselara_ulasilir(self):
        # Çözümleyicinin boş geçmediğinin kanıtı: çift tık davranışı değişmedi.
        ulasilan, pauses, _ = bat_akisi("normal")
        self.assertEqual(pauses & ulasilan, pauses)

    def test_yalniz_kurulum_kipinde_sesver_baslatilmaz(self):
        satirlar = bat_satirlari()
        ulasilan, _, etiketler = bat_akisi("yk")
        baslatanlar = [i for i, s in enumerate(satirlar)
                       if "desktop.py" in s and not s.strip().lower().startswith(("rem", "echo"))]
        self.assertGreaterEqual(len(baslatanlar), 2)  # start pythonw + konsollu yedek
        self.assertEqual([i + 1 for i in baslatanlar if i in ulasilan], [])
        for etiket in ("yk_tamam", "yk_hata", "yk_isaret_hata", "ilk_kurulum", "esitle", "embed_kur"):
            self.assertIn(etiketler[etiket], ulasilan, etiket)
        for etiket in ("baslat_bekle", "baslat_durum", "baslat_konsollu", "baslat_zaman_asimi"):
            self.assertNotIn(etiketler[etiket], ulasilan, etiket)

    def test_normal_kipte_yalniz_kurulum_sonlarina_girilmez(self):
        ulasilan, _, etiketler = bat_akisi("normal")
        for etiket in ("yk_tamam", "yk_hata", "yk_isaret_hata", "yk_gunluk_acik", "yk_mimari_tamam"):
            self.assertNotIn(etiketler[etiket], ulasilan, etiket)

    def test_crlf_ve_komut_satirlari_ascii(self):
        raw = BAT_YOLU.read_bytes()
        self.assertEqual(raw.count(b"\n"), raw.count(b"\r\n"), "çıplak LF var")
        for i, ham in enumerate(bat_satirlari()):
            if ham.strip().lower().startswith("rem"):
                continue
            ham.encode("ascii")  # echo/komut satırlarında Türkçe karakter yok (konsol kod sayfası)


# ---------------------------------------------------------------- durum satırı biçimi

DURUM_CAGRISI = re.compile(r'^call :durum (\S+) "([^"]*)"$')
ORNEK_DEGISKENLER = {
    "%SV_TOPLAM_ADIM%": str(kd.TOPLAM_ADIM),
    "%SV_ADIM_NO%": "6",
    "%CUDA_ETIKET%": "cu128",
    "%ADIM%": "requirements.txt kurulumu",
}


def bat_durum_satirlari():
    """Bat'taki her ``call :durum N "metin"`` çağrısının yazacağı satır (örnek değişkenlerle)."""
    sonuc = []
    for ham in bat_satirlari():
        m = DURUM_CAGRISI.match(ham.strip())
        if not m:
            continue
        adim, metin = m.groups()
        for degisken, deger in ORNEK_DEGISKENLER.items():
            adim, metin = adim.replace(degisken, deger), metin.replace(degisken, deger)
        sonuc.append((int(adim), metin, kd.bicimle(adim, metin)))
    return sonuc


class DurumBicimiTests(unittest.TestCase):
    def test_bat_durum_yordami_tek_bicimi_yazar(self):
        satirlar = [s.strip() for s in bat_satirlari()]
        self.assertIn(f'set "SV_TOPLAM_ADIM={kd.TOPLAM_ADIM}"', satirlar)
        # cmd'de | kaçışı ^| ; dosya adı tek kaynaktaki ile aynı.
        self.assertIn(f'>"{kd.DURUM_DOSYASI}" echo %~1/%SV_TOPLAM_ADIM%^{kd.AYIRICI}%~2', satirlar)
        self.assertIn(f'if /i "%~1"=="{kd.YALNIZ_KURULUM_ARGUMANI}" set "{kd.YALNIZ_KURULUM_ORTAM_DEGISKENI}=1"',
                      satirlar)
        bat = "\r\n".join(satirlar)
        self.assertIn(f'>"{kd.GUNLUK_DOSYASI}" 2>&1', bat)
        self.assertIn(f'>"{kd.PID_DOSYASI}"', bat)

    def test_bat_tum_durum_satirlari_ayristirilir(self):
        satirlar = bat_durum_satirlari()
        self.assertGreaterEqual(len(satirlar), 12)
        adimlar = set()
        for adim, metin, satir in satirlar:
            satir.encode("ascii")
            self.assertEqual(kd.ayristir(satir), (adim, kd.TOPLAM_ADIM, metin), satir)
            self.assertEqual(kd.pascal_ayristir(satir), kd.ayristir(satir), satir)
            adimlar.add(adim)
        self.assertEqual(adimlar, set(range(kd.TOPLAM_ADIM + 1)))
        metinler = [m for _, m, _ in satirlar]
        self.assertIn(kd.TAMAM, metinler)
        self.assertEqual(sum(m.startswith(kd.HATA_ONEKI) for m in metinler), 1)
        self.assertEqual(set(kd.ADIMLAR), set(range(kd.TOPLAM_ADIM + 1)))

    def test_bitis_satirlari(self):
        self.assertEqual(kd.bitis("tamam"), ("tamam", None))
        self.assertEqual(kd.bitis("hata:requirements.txt kurulumu"), ("hata", "requirements.txt kurulumu"))
        self.assertIsNone(kd.bitis("PyTorch kuruluyor (cu128)"))
        self.assertIsNone(kd.bitis("Tamam"))  # büyük/küçük harf duyarlı (Pascal '=' gibi)

    def test_pascal_ayristirici_kati_ayristiriciyla_ayni_karar(self):
        ornekler = ["", "3/6", "3/6|", "3/6|  ", "/6|x", "7/6|x", "0/0|x", "a/6|x", "6/6|tamam",
                    "6/6|hata:pip guncelleme", "12/6|x", "3/6|a|b", "0/6|Basliyor", "3|x", "3/|x",
                    "4/6|PyTorch kuruluyor (cu128)", "-1/6|x"]
        for s in ornekler:
            self.assertEqual(kd.pascal_ayristir(s), kd.ayristir(s), repr(s))
        self.assertIsNone(kd.ayristir("3/6"))  # yarım yazılmış satır yok sayılır
        self.assertEqual(kd.ayristir("3/6|a|b"), (3, 6, "a|b"))


# ---------------------------------------------------------------- iss

def _pascal_kodu_temizle(kod):
    """Dizgileri ve yorumları (//, { }, (* *)) tek geçişte boşaltır."""
    cikti, i, n = [], 0, len(kod)
    while i < n:
        c = kod[i]
        if c == "'":
            j = i + 1
            while j < n:
                if kod[j] == "'" and j + 1 < n and kod[j + 1] == "'":
                    j += 2
                elif kod[j] == "'":
                    break
                else:
                    j += 1
            cikti.append("''")
            i = j + 1
        elif kod.startswith("//", i):
            j = kod.find("\n", i)
            i = n if j < 0 else j
        elif c == "{":
            i = kod.index("}", i) + 1
        elif kod.startswith("(*", i):
            i = kod.index("*)", i) + 2
        else:
            cikti.append(c)
            i += 1
    return "".join(cikti)


class IssTests(unittest.TestCase):
    def test_sabitler_tek_kaynakla_ayni(self):
        kod = iss_bolumu("Code")
        beklenen = {
            "OrtamDurumDosyasi": f"'{kd.DURUM_DOSYASI}'",
            "OrtamGunlukDosyasi": f"'{kd.GUNLUK_DOSYASI}'",
            "OrtamPaylasGunlukDosyasi": f"'{kd.PAYLAS_GUNLUK_DOSYASI}'",
            "OrtamEvMaskesi": f"'{kd.EV_MASKESI}'",
            "OrtamPidDosyasi": f"'{kd.PID_DOSYASI}'",
            "OrtamYalnizKurulumArg": f"'{kd.YALNIZ_KURULUM_ARGUMANI}'",
            "OrtamToplamAdim": str(kd.TOPLAM_ADIM),
            "OrtamDurumTamam": f"'{kd.TAMAM}'",
            "OrtamDurumHataOneki": f"'{kd.HATA_ONEKI}'",
            "OrtamKurParametresi": f"'{kd.ORTAMKUR_PARAMETRESI}'",
            "OrtamHataCikisKodu": str(kd.ORTAM_HATA_CIKIS_KODU),
        }
        for ad, deger in beklenen.items():
            m = re.search(r"^\s*" + ad + r"\s*=\s*(.+?);", kod, re.M)
            self.assertTrue(m, ad)
            self.assertEqual(m.group(1), deger, ad)

    def test_pascal_ayristirici_python_karsiligiyla_ayni_kurallar(self):
        kod = iss_bolumu("Code")
        govde_m = re.search(r"function DurumSatiriniAyristir\(.*?\nend;", kod, re.S)
        self.assertIsNotNone(govde_m)
        govde = govde_m.group(0) if govde_m else ""
        for parca in ("Pos('|', Satir)", "if Cizgi < 4 then", "Pos('/', Sol)", "if Bolu < 2 then",
                      "StrToIntDef(Copy(Sol, 1, Bolu - 1), -1)",
                      "(Adim >= 0) and (Toplam > 0) and (Adim <= Toplam) and (Metin <> '')"):
            self.assertIn(parca, govde)
        bitis_m = re.search(r"function OrtamBitisiniIsle\(.*?\nend;", kod, re.S)
        self.assertIsNotNone(bitis_m)
        bitis = bitis_m.group(0) if bitis_m else ""
        self.assertIn("Metin = OrtamDurumTamam", bitis)
        self.assertIn("Pos(Onek, Metin) = 1", bitis)

    def test_gizli_baslatma_iptal_ve_sessiz_kip(self):
        kod = iss_bolumu("Code")
        self.assertIn("CurStep <> ssPostInstall", kod)
        self.assertIn("CreateOutputProgressPage(", kod)
        # Konsol penceresi yok: ExecAndLogOutput (CREATE_NO_WINDOW) + "start /b"; Exec(ewNoWait) yok.
        self.assertIn("'/d /c start \"\" /b \"' + Cmd + '\" /d /c call \"'", kod)
        self.assertIn("ExecAndLogOutput(Cmd, Komut", kod)
        # Torun cmd.exe Inno'nun çıktı borusunu devralmamalı (CI 41073828284: boru
        # kapanınca bat hiçbir dosya yazmadan bitiyordu, sihirbaz sonsuza dek bekliyordu).
        self.assertIn("OrtamYalnizKurulumArg + ' >nul 2>&1'", kod)
        self.assertIn("(Pid = 0) and (SonSatir = '')", kod)
        self.assertRegex(iss_metni(), r"(?m)^\s*OrtamIlkSinyalSn = \d+;")
        self.assertNotRegex(kod, r"\bExec\([^;]*ewNoWait[^;]*WINDOWS_BASLAT")
        self.assertIn("'/T /F /PID '", kod)
        self.assertIn("WizardSilent() and not KomutSatirindaVar(OrtamKurParametresi)", kod)
        self.assertIn("function GetCustomSetupExitCode(): Integer;", kod)
        run = iss_bolumu("Run")
        self.assertNotIn("RunFirstSetup", run)
        self.assertRegex(run, r'Filename: "\{app\}\\python-embed\\pythonw\.exe";.*'
                              r'Flags: postinstall nowait skipifsilent; Check: OrtamHazirDogrudanAcilir')

    def test_pascal_blok_dengesi(self):
        kod = _pascal_kodu_temizle(iss_bolumu("Code"))
        derinlik, yigin = 0, []
        for kelime in re.findall(r"[A-Za-z_]+", kod):
            k = kelime.lower()
            if k in ("begin", "try", "case"):
                yigin.append(k)
            elif k in ("finally", "except"):
                self.assertTrue(yigin and yigin[-1] == "try", f"{k} try'sız")
                yigin[-1] = "try+"
            elif k == "end":
                self.assertTrue(yigin, "fazla end")
                acan = yigin.pop()
                self.assertNotEqual(acan, "try", "finally/except'siz try")
            derinlik = max(derinlik, len(yigin))
        self.assertEqual(yigin, [], "kapanmamış blok")
        self.assertGreater(derinlik, 2)

    def test_dosya_ozellikleri_signpath_icin_sabit(self):
        """SignPath: ürün adı = proje adı, ürün sürümü = VERSION (her derlemede aynı kaynaktan)."""
        setup = iss_bolumu("Setup")
        metin = iss_metni()
        self.assertIn('#define AppName "SesVer"', metin)
        self.assertRegex(metin, r'(?m)^\s*#define AppVersion Trim\(FileRead\(VersionFile\)\)$')  # VERSION'dan
        for satir in ("VersionInfoProductName={#AppName}", "VersionInfoProductVersion={#AppVersion}",
                      "VersionInfoProductTextVersion={#AppVersion}", "VersionInfoVersion={#AppVersion}",
                      "VersionInfoTextVersion={#AppVersion}", "VersionInfoCompany={#AppPublisher}",
                      "VersionInfoCopyright=Muhammed Yusuf Hamarat - Founder of HamaratLabs"):
            self.assertIn(satir + "\n", setup)
        # Kaldırma korunur: Kaldır/Ekle kaydı var, kullanıcı verisi silinenler listesinde yok.
        self.assertNotIn("Uninstallable=no", setup)
        self.assertNotRegex(iss_bolumu("UninstallDelete"), r'(?m)^Type:.*Name: "\{app\}\\(outputs|voices)')

    def test_ozel_mesajlar_tr_ve_en(self):
        mesajlar = iss_bolumu("CustomMessages")
        diller = {"turkish": set(), "english": set()}
        for dil, ad in re.findall(r"^(turkish|english)\.([A-Za-z0-9]+)=", mesajlar, re.M):
            diller[dil].add(ad)
        self.assertEqual(diller["turkish"], diller["english"])
        metin = iss_metni()
        kullanilan = set(re.findall(r"CustomMessage\('([A-Za-z0-9]+)'\)", metin))
        kullanilan |= set(re.findall(r"\{cm:([A-Za-z0-9]+)\}", metin))
        kullanilan |= {f"OrtamAdim{i}" for i in range(kd.TOPLAM_ADIM + 1)}  # 'OrtamAdim' + IntToStr
        kullanilan -= {"AdditionalIcons"}  # Inno'nun hazır mesajı
        self.assertEqual(sorted(kullanilan - diller["turkish"]), [])
        tr = dict(re.findall(r"^turkish\.([A-Za-z0-9]+)=(.*)$", mesajlar, re.M))
        en = dict(re.findall(r"^english\.([A-Za-z0-9]+)=(.*)$", mesajlar, re.M))
        self.assertIn("hermes.agent.hamarat@gmail.com", tr["OrtamHataMetni"])
        # Gönderilmesi söylenen dosya maskeli kopyadır, kurulum_log.txt değil (bulgu 1).
        for metin in (tr["OrtamHataMetni"], en["OrtamHataMetni"]):
            self.assertIn(kd.PAYLAS_GUNLUK_DOSYASI, metin)
            self.assertNotIn(kd.GUNLUK_DOSYASI, metin)
        self.assertIn("3 GB", tr["OrtamSayfaAciklama"])


# ---------------------------------------------------------------- paylaşılabilir günlük (bulgu 1)

ORNEK_KURULUM_GUNLUGU = "\r\n".join([
    "[SesVer baslatici calisiyor]",
    "Kullanilan Python: python-embed - SesVer'e ozel tasinabilir Python",
    "  Downloading torch-2.14.1+cu128-cp311-cp311-win_amd64.whl (3.1 GB)",
    "  WARNING: The script x.exe is installed in 'C:\\Users\\Ornek Kisi\\AppData\\Local\\Programs\\SesVer"
    "\\python-embed\\Scripts' which is not on PATH.",
    "ERROR: Could not install packages due to an OSError: [Errno 28] No space left on device: "
    "'c:\\users\\ornek kisi\\appdata\\local\\temp\\pip-unpack-1\\torch.whl'",
    "Temp: C:\\Users\\ORNEKK~1\\AppData\\Local\\Temp\\pip-build",
    "repr: 'C:\\\\Users\\\\Ornek Kisi\\\\AppData'",
    "url bicimi: C:/Users/Ornek Kisi/AppData/Local/pip/cache",
    "profil disarida: D:\\Profiller\\digerkisi\\AppData\\Roaming\\pip\\pip.ini",
    "[DURUM] 6/6|hata:requirements.txt kurulumu",
    "",
    "[SIHIRBAZ] Kurulum sureci son durum satirini yazmadan bitti; cikis kodu 1",
])


class PaylasilabilirGunlukTests(unittest.TestCase):
    def test_python_karsiligi_ev_yollarini_gizler(self):
        out = kd.pascal_gunluk_maskele(ORNEK_KURULUM_GUNLUGU, "D:\\Profiller\\digerkisi")
        for sizinti in ("Ornek", "ornek", "ORNEKK~1", "Kisi", "kisi", "digerkisi"):
            self.assertNotIn(sizinti, out)
        self.assertIn("'<ev>\\AppData\\Local\\Programs\\SesVer\\python-embed\\Scripts'", out)
        self.assertIn("'<ev>\\appdata\\local\\temp\\pip-unpack-1\\torch.whl'", out)
        self.assertIn("Temp: <ev>\\AppData\\Local\\Temp\\pip-build", out)
        self.assertIn("repr: '<ev>\\\\AppData'", out)
        self.assertIn("url bicimi: <ev>/AppData/Local/pip/cache", out)
        self.assertIn("profil disarida: <ev>\\AppData\\Roaming\\pip\\pip.ini", out)
        # Teknik içerik ve satır yapısı korunur.
        self.assertIn("[DURUM] 6/6|hata:requirements.txt kurulumu", out)
        self.assertIn("No space left on device", out)
        self.assertEqual(out.count("\r\n"), ORNEK_KURULUM_GUNLUGU.count("\r\n"))
        # Kısa (8.3) ad profil X:\Users dışındaysa da gizlenir; ev kökü kısa yoldan da eşleşir.
        kisa = kd.pascal_gunluk_maskele("a D:\\PROFIL~1\\digerkisi\\x b", "D:\\Profiller\\digerkisi",
                                        kisa_ad="D:\\PROFIL~1\\digerkisi")
        self.assertEqual(kisa, "a <ev>\\x b")
        self.assertEqual(kd.pascal_gunluk_maskele("x", ""), "x")  # USERPROFILE yoksa yalnız kalıp

    def test_python_karsiligi_hata_raporu_maskesiyle_ayni_sonuc(self):
        import hata_raporu
        for satir in ORNEK_KURULUM_GUNLUGU.split("\r\n"):
            with self.subTest(satir=satir):
                self.assertEqual(kd.pascal_ev_yollarini_maskele(satir),
                                 hata_raporu.sanitize(satir, homes=[]) if "@" not in satir else satir)

    def test_iss_maskeleme_python_karsiligiyla_ayni_kurallar(self):
        kod = iss_bolumu("Code")
        isaret = pascal_govde(kod, "function", "IlkEvIsareti")
        for p in kd.EV_ISARETLERI:
            self.assertIn(f"'{p}'", isaret)
        maske = pascal_govde(kod, "function", "EvYollariniMaskele")
        # Pascal'da tek tırnak '' ile yazılır; #9 #10 #13 = sekme, LF, CR.
        self.assertIn("Bitis := '\\/\"''<>|' + #9 + #10 + #13;", maske)
        self.assertEqual(kd.EV_ADI_BITISLERI, "\\/\"'<>|\t\n\r")
        for parca in ("(Kucuk[P - 1] >= 'a') and (Kucuk[P - 1] <= 'z')", "Bas := P - 1;", "Son := P + Uzunluk;",
                      "Pos(Copy(Kalan, Son, 1), Bitis) = 0", "Copy(Kalan, 1, Bas - 1) + OrtamEvMaskesi"):
            self.assertIn(parca, maske)
        gunluk = pascal_govde(kod, "function", "GunlukMaskele")
        degistir = pascal_govde(kod, "function", "HarfDuyarsizDegistir")
        self.assertIn("KucukBul := AnsiLowercase(Bul);", degistir)  # ASCII dışı harf de duyarsız (bulgu B)
        self.assertIn("Kucuk := AnsiLowercase(Kalan);", degistir)
        for parca in ("if Length(Ev) > 3 then", "StringChangeEx(Egik, '\\', '/', True);", "GetShortName(Ev)",
                      "Result := EvYollariniMaskele(Result);"):
            self.assertIn(parca, gunluk)
        yaz = pascal_govde(kod, "function", "PaylasilabilirGunlukYaz")
        self.assertIn("PaylasilabilirGunlukBaytlari(Ham, GetEnv('USERPROFILE'))", yaz)
        self.assertIn("SaveStringToFile(Hedef,", yaz)
        baytlar = pascal_govde(kod, "function", "PaylasilabilirGunlukBaytlari")
        for parca in ("if GecerliUtf8(Ham) then", "Utf8Encode(GunlukMaskele(Utf8Decode(Ham), Ev))",
                      "EvUtf8 := Utf8Encode(Ev);", "EvUtf8Okunusu := String(EvUtf8);",
                      "KucukEvUtf8 := Utf8Encode(AnsiLowercase(Ev));",
                      "Metin := GunlukMaskele(String(Ham), EvUtf8Okunusu);",
                      "Metin := GunlukMaskele(Metin, KucukEvUtf8Okunusu);", "Metin := GunlukMaskele(Metin, Ev);"):
            self.assertIn(parca, baytlar)
        utf8 = pascal_govde(kod, "function", "GecerliUtf8")
        for parca in ("(C >= $C2) and (C <= $DF)", "if C = $E0 then\n        Alt := $A0;",
                      "if C = $ED then\n        Ust := $9F;", "if C = $F0 then\n        Alt := $90;",
                      "if C = $F4 then\n        Ust := $8F;", "(C >= $F0) and (C <= $F4)", "if I + Ek > N then",
                      "(Ord(B[J]) < $80) or (Ord(B[J]) > $BF)"):
            self.assertIn(parca, utf8)

    def test_iss_hata_ve_iptalde_kopya_yazilir_ve_gosterilir(self):
        kod = iss_bolumu("Code")
        adim = pascal_govde(kod, "procedure", "CurStepChanged")
        self.assertEqual(adim.count("PaylasilabilirGunlukYaz();"), 2)  # iptal + hata dalı
        self.assertNotIn("PaylasilabilirGunlukYaz", adim.split("osIptal:")[0])  # başarıda yazılmaz
        for ad in ("CurPageChanged", "GunlukDugmesiClick"):
            self.assertIn("Gunluk := GosterilecekGunluk();", pascal_govde(kod, "procedure", ad))
        self.assertIn(f'Type: files; Name: "{{app}}\\{kd.PAYLAS_GUNLUK_DOSYASI}"', iss_bolumu("UninstallDelete"))

    def test_maskeli_kopya_yoksa_ham_gunluk_gosterilmez(self):
        """Bulgu A: kopya yazılamazsa Bitir sayfası ham kurulum_log.txt'yi göstermez, dosya istemez."""
        kod = iss_bolumu("Code")
        goster = pascal_govde(kod, "function", "GosterilecekGunluk")
        self.assertNotIn("OrtamGunlukDosyasi", goster)  # ham günlüğe hiçbir yoldan düşmez
        self.assertIn("Result := '';", goster)
        self.assertIn("if PaylasGunlukHazir and FileExists(", goster)
        yaz = pascal_govde(kod, "function", "PaylasilabilirGunlukYaz")
        self.assertIn("PaylasGunlukHazir := False;", yaz)
        self.assertIn("PaylasGunlukHazir := Result;", yaz)
        self.assertIn("if not FileExists(Kaynak) then", yaz)  # kaynak yoksa boş kopya da yazılmaz
        sayfa = pascal_govde(kod, "procedure", "CurPageChanged")
        for parca in ("FmtMessage(CustomMessage('OrtamHataMetniGunluksuz'), [OrtamHataAdimi])",
                      "Metin := CustomMessage('OrtamIptalMetniGunluksuz');",
                      "GunlukDugmesi.Visible := Gunluk <> '';"):
            self.assertIn(parca, sayfa)
        self.assertNotIn("GunlukDugmesi.Visible := True;", sayfa)
        self.assertIn("if Gunluk = '' then\n    Exit;", pascal_govde(kod, "procedure", "GunlukDugmesiClick"))
        mesajlar = iss_bolumu("CustomMessages")
        for dil in ("turkish", "english"):
            for ad in ("OrtamHataMetniGunluksuz", "OrtamIptalMetniGunluksuz"):
                metin = re.search(rf"^{dil}\.{ad}=(.*)$", mesajlar, re.M).group(1)
                # Dosya gösterilmez/istenmez: ne dosya adı ne %2 (yol) yer tutucusu.
                for yasak in (kd.GUNLUK_DOSYASI, kd.PAYLAS_GUNLUK_DOSYASI, "%2", "gönder", "send", "Open log",
                              "Günlüğü aç"):
                    self.assertNotIn(yasak, metin, f"{dil}.{ad}")
            hata = re.search(rf"^{dil}\.OrtamHataMetniGunluksuz=(.*)$", mesajlar, re.M).group(1)
            self.assertIn("hermes.agent.hamarat@gmail.com", hata)
            self.assertEqual(hata.count("%1"), 2)  # durduğu adım metinde ve bildirilecek bilgi olarak


# ---------------------------------------------------------------- günlük kodlaması (bulgu B)

ASCII_DISI_EV = "D:\\Profiller\\Şükrü Öztürk"  # C:\Users dışında, ASCII dışı ad


def _ornek_gunluk_satirlari(ev):
    return [
        "[SesVer baslatici calisiyor]",
        "[BILGI] Yalniz kurulum kipi: SesVer kurulumdan sonra baslatilmaz.",
        f'[BILGI] Kurulum klasoru: "{ev}\\AppData\\Local\\Programs\\SesVer"',
        f"Requirement already satisfied: pip in {ev.lower()}\\appdata\\local\\programs\\sesver\\python-embed\\lib",
        f"ERROR: [Errno 28] No space left on device: '{ev}\\AppData\\Local\\Temp\\pip-unpack-1\\t.whl'",
        "[DURUM] 5/6|hata:voxcpm kurulumu",
    ]


def _sizinti_var(baytlar, ad="Şükrü"):
    return any(ad.encode(k) in baytlar or ad.lower().encode(k) in baytlar for k in ("utf-8", "cp1254", "cp857"))


class GunlukKodlamasiTests(unittest.TestCase):
    def test_gecerli_utf8_python_cozucusuyle_ayni_karar(self):
        import random
        alfabe = [0x00, 0x41, 0x7F, 0x80, 0x8F, 0x90, 0x9F, 0xA0, 0xBF, 0xC0, 0xC1, 0xC2, 0xC5, 0xDF,
                  0xE0, 0xE2, 0xED, 0xEF, 0xF0, 0xF3, 0xF4, 0xF5, 0xFF]
        rnd = random.Random(20261107)
        ornekler = [b"", "Şükrü Öztürk".encode("utf-8"), "Şükrü".encode("cp1254"), b"\xed\xa0\x80", b"\xf4\x90\x80\x80",
                    b"\xe0\x80\xaf", b"\xc0\xaf", "😀".encode("utf-8"), b"\xe2\x82"]
        ornekler += [bytes(rnd.choice(alfabe) for _ in range(rnd.randint(1, 6))) for _ in range(5000)]
        for b in ornekler:
            try:
                b.decode("utf-8")
                beklenen = True
            except UnicodeDecodeError:
                beklenen = False
            self.assertEqual(kd.pascal_gecerli_utf8(b), beklenen, b)

    def test_ascii_disi_ad_users_disi_profil_utf8_gunlukte_gizlenir(self):
        ham = "\r\n".join(_ornek_gunluk_satirlari(ASCII_DISI_EV)).encode("utf-8")
        # Eski yol (ANSI çözüp USERPROFILE ile karşılaştırma) bu günlükte adı kaçırıyordu.
        eski = kd.ansi_kodla(kd.pascal_gunluk_maskele(kd.ansi_coz(ham), ASCII_DISI_EV))
        self.assertTrue(_sizinti_var(eski), "test anlamsız: eski yol zaten gizliyor")
        out = kd.pascal_paylasilabilir_gunluk_baytlari(ham, ASCII_DISI_EV)
        self.assertFalse(_sizinti_var(out), out)
        self.assertNotIn(b"Profiller", out)
        metin = out.decode("utf-8")  # UTF-8 kalır
        self.assertIn('Kurulum klasoru: "<ev>\\AppData\\Local\\Programs\\SesVer"', metin)
        self.assertIn("pip in <ev>\\appdata", metin)  # küçük harfli Windows yolu da (A-Z duyarsız)
        self.assertIn("[DURUM] 5/6|hata:voxcpm kurulumu", metin)

    def test_karisik_kodlamali_gunlukte_de_gizlenir(self):
        satirlar = _ornek_gunluk_satirlari(ASCII_DISI_EV)
        for bolme in (3, 4):  # küçük harfli pip satırı ANSI kısımda da, UTF-8 kısımda da
            with self.subTest(bolme=bolme):
                ham = ("\r\n".join(satirlar[:bolme]).encode("utf-8") + b"\r\n" +
                       "\r\n".join(satirlar[bolme:]).encode("cp1254"))  # araya ANSI çıktı karışmış
                self.assertFalse(kd.pascal_gecerli_utf8(ham))
                out = kd.pascal_paylasilabilir_gunluk_baytlari(ham, ASCII_DISI_EV)
                self.assertFalse(_sizinti_var(out), out)
                self.assertEqual(out.count(b"<ev>"), 3)
                # Maskelenmeyen baytlar korunur (ANSI yol baytları değiştirmez).
                self.assertIn(b"[DURUM] 5/6|hata:voxcpm kurulumu", out)

    def test_ascii_ad_ve_users_profili_eskisi_gibi(self):
        ev = "C:\\Users\\Ornek Kisi"
        ham = "\r\n".join(_ornek_gunluk_satirlari(ev)).encode("utf-8")
        out = kd.pascal_paylasilabilir_gunluk_baytlari(ham, ev, kisa_ad="C:\\Users\\ORNEKK~1")
        self.assertNotIn(b"Ornek", out)
        self.assertNotIn(b"ornek", out)
        self.assertEqual(out.count(b"<ev>"), 3)

    def test_bat_gunlugu_utf8_yazar_yalniz_kurulum_kipinde(self):
        satirlar = [s.strip() for s in bat_satirlari()]
        chcp = satirlar.index(kd.BAT_KOD_SAYFASI_SATIRI)
        pyenc = satirlar.index(kd.BAT_PYTHON_KODLAMA_SATIRI)
        self.assertEqual(satirlar.count(kd.BAT_KOD_SAYFASI_SATIRI), 1)
        acik = satirlar.index(":yk_gunluk_acik")
        pid = next(i for i, s in enumerate(satirlar) if s.startswith("powershell") and "kurulum_pid.txt" in s)
        klasor = satirlar.index('echo [BILGI] Kurulum klasoru: "%CD%"')
        # PID satırı kod sayfası değişmeden yazılır; günlüğün geri kalanı UTF-8.
        self.assertLess(acik, pid)
        self.assertLess(pid, chcp)
        self.assertLess(chcp, klasor)
        self.assertEqual(pyenc, chcp + 1)
        self.assertLess(klasor, satirlar.index(":yk_hazir"))
        yk, _p, _e = bat_akisi("yk")
        normal, _p, _e = bat_akisi("normal")
        self.assertIn(chcp, yk)
        self.assertNotIn(chcp, normal)  # çift tık çalışmasında kod sayfasına dokunulmaz
        self.assertNotIn(klasor, normal)


# ---------------------------------------------------------------- güncelleme denetimi seçeneği

def _uygulama_okur(metin):
    """Uygulamanın gerçek kodu (guncelleme.ayar_acik_mi → i18n.get_setting) bu ayarlar.json'u nasıl okur."""
    import os
    import tempfile
    import guncelleme
    with tempfile.TemporaryDirectory() as d:
        yol = Path(d) / kd.AYAR_DOSYASI
        if metin is not None:
            yol.write_text(metin, encoding="utf-8")
        eski = os.environ.get("SESVER_AYARLAR")
        os.environ["SESVER_AYARLAR"] = str(yol)
        try:
            return guncelleme.ayar_acik_mi()
        finally:
            if eski is None:
                os.environ.pop("SESVER_AYARLAR", None)
            else:
                os.environ["SESVER_AYARLAR"] = eski


def _json(d):
    import json
    return json.dumps(d, ensure_ascii=False, indent=2) + "\n"  # i18n.set_setting biçimi


AYAR_ORNEKLERI = [
    "", _json({}), _json({"arayuz_dili": "en"}), _json({"guncelleme_kontrolu": True, "arayuz_dili": "tr"}),
    _json({"arayuz_dili": "de", "guncelleme_kontrolu": False}), '{"guncelleme_kontrolu":false}', "{}", "{ }",
    '{"guncelleme_kontrolu": 0}', '{"guncelleme_kontrolu": null}', '{\r\n  "guncelleme_kontrolu" : false\r\n}\r\n',
    '{"guncelleme_kontrolu": false', "bozuk", '[1, 2]', _json({"not": "a, b} c", "guncelleme_kontrolu": True}),
    _json({"arayuz_dili": "zh", "ad": "Şükrü"}),
]


class GuncellemeSecenegiTests(unittest.TestCase):
    def test_okuma_uygulamanin_gercek_koduyla_ayni(self):
        for metin in AYAR_ORNEKLERI:
            with self.subTest(metin=metin):
                self.assertEqual(kd.pascal_guncelleme_ayari_acik_mi(metin), _uygulama_okur(metin))
        self.assertTrue(_uygulama_okur(None))  # dosya yok: açık

    def test_yazilan_metni_uygulama_secilen_degerle_okur_diger_ayarlar_korunur(self):
        import json
        for metin in AYAR_ORNEKLERI:
            for acik in (True, False):
                with self.subTest(metin=metin, acik=acik):
                    yeni = kd.pascal_guncelleme_ayarini_yerlestir(metin, acik)
                    veri = json.loads(yeni)
                    self.assertIs(veri["guncelleme_kontrolu"], acik)
                    try:
                        once = json.loads(metin)
                    except ValueError:
                        once = {}
                    if isinstance(once, dict):
                        once.pop("guncelleme_kontrolu", None)
                        self.assertEqual({k: v for k, v in veri.items() if k != "guncelleme_kontrolu"}, once)
                    self.assertEqual(_uygulama_okur(yeni), acik)
                    self.assertEqual(kd.pascal_guncelleme_ayari_acik_mi(yeni), acik)

    def test_karar_onceki_secimi_ezmez(self):
        karar = kd.pascal_guncelleme_karari
        # Sessiz kurulum: parametre yoksa dokunulmaz (Ayarlar'da kapatılmış seçim güncellemede kalır).
        self.assertEqual(karar(True, -1, True, False), (False, None))
        self.assertEqual(karar(True, -1, True, True), (False, None))
        self.assertEqual(karar(True, 0, True, True), (True, False))
        self.assertEqual(karar(True, 0, True, False), (False, False))
        self.assertEqual(karar(True, 1, False, False), (True, True))
        # Etkileşimli: kutu mevcut ayarla açılır; değiştirilmediyse yazılmaz.
        self.assertEqual(karar(False, -1, False, False), (False, False))
        self.assertEqual(karar(False, -1, True, True), (False, True))
        self.assertEqual(karar(False, -1, False, True), (True, False))
        self.assertEqual(karar(False, -1, True, False), (True, True))

    def test_beklenmedik_bicimdeki_dosya_yerinde_duzenlenmez(self):
        """Siberguvenlik 1.2.1 G: metin üzerinde düzenleme yalnız uygulamanın yazdığı biçimde yapılır."""
        import json
        bicim = kd.pascal_guncelleme_yazim_bicimi
        beklenen = {
            "": kd.AYAR_YOK, " \r\n": kd.AYAR_YOK,
            "bozuk": kd.AYAR_BOZUK, "[1, 2]": kd.AYAR_BOZUK, '{"guncelleme_kontrolu": false': kd.AYAR_BOZUK,
            '{"guncelleme_kontrolu": 0}': kd.AYAR_DEGER_BEKLENMEDIK,
            '{"guncelleme_kontrolu": null}': kd.AYAR_DEGER_BEKLENMEDIK,
            '{"guncelleme_kontrolu": "false"}': kd.AYAR_DEGER_BEKLENMEDIK,
            '{"guncelleme_kontrolu": falsey}': kd.AYAR_DEGER_BEKLENMEDIK,
            '{"guncelleme_kontrolu": "a, b"}': kd.AYAR_DEGER_BEKLENMEDIK,
            '{"guncelleme_kontrolu":false}': kd.AYAR_TANIDIK, '{"guncelleme_kontrolu": true }': kd.AYAR_TANIDIK,
        }
        for metin, sonuc in beklenen.items():
            with self.subTest(metin=metin):
                self.assertEqual(bicim(metin), sonuc)
        for metin in AYAR_ORNEKLERI:
            with self.subTest(ornek=metin):
                b = bicim(metin)
                if b == kd.AYAR_BOZUK:  # uygulama da bu dosyayı yok sayar (boş ayar)
                    try:
                        self.assertNotIsInstance(json.loads(metin), dict)
                    except ValueError:
                        pass
                if b == kd.AYAR_TANIDIK:  # geçerli nesne, anahtar yok ya da boolean
                    self.assertIn(json.loads(metin).get("guncelleme_kontrolu", True), (True, False))

    def test_tercih_bozuk_dosyayi_once_yedekler_beklenmedik_degere_dokunmaz(self):
        import json
        uygula = kd.pascal_guncelleme_tercihini_uygula
        yok = lambda ad: False  # noqa: E731
        # Bozuk dosya + kapalı seçim: önce olduğu gibi yedek, sonra yeni nesne.
        ham = b'{"arayuz_dili": "en", '
        yeni, yedek = uygula(ham, True, False, -1, False, yok)
        self.assertEqual(yedek, "ayarlar.json.bozuk")
        self.assertEqual(json.loads(yeni), {"guncelleme_kontrolu": False})
        dolu = {"ayarlar.json.bozuk"} | {f"ayarlar.json.bozuk-{n}" for n in range(2, 21)}
        self.assertEqual(uygula(ham, True, False, -1, False, dolu.__contains__), (None, None))  # yedek yeri yok
        dolu.discard("ayarlar.json.bozuk-7")
        self.assertEqual(uygula(ham, True, False, -1, False, dolu.__contains__)[1], "ayarlar.json.bozuk-7")
        # Bozuk dosya + varsayılan (açık) seçim: uygulama zaten açık sayar, dosyaya dokunulmaz.
        self.assertEqual(uygula(ham, True, False, -1, True, yok), (None, None))
        # Okunamayan dosya ve boolean olmayan değer: dokunulmaz.
        self.assertEqual(uygula(b"", False, True, 0, True, yok), (None, None))
        self.assertEqual(uygula(b'{"guncelleme_kontrolu": null, "a": 1}', True, True, 0, True, yok), (None, None))
        # Uygulamanın biçimi: yerinde, diğer ayar korunur, yedek yok.
        yeni, yedek = uygula(_json({"arayuz_dili": "ja"}).encode("utf-8"), True, True, 0, True, yok)
        self.assertIsNone(yedek)
        self.assertEqual(json.loads(yeni), {"guncelleme_kontrolu": False, "arayuz_dili": "ja"})
        # Dosya yok: yeni nesne.
        yeni, yedek = uygula(b"", True, True, 0, True, yok)
        self.assertEqual((json.loads(yeni), yedek), ({"guncelleme_kontrolu": False}, None))

    def test_iss_yazim_bicimi_ve_yedek_python_karsiligiyla_ayni(self):
        kod = iss_bolumu("Code")
        for ad, deger in (("AyarYok", str(kd.AYAR_YOK)), ("AyarTanidik", str(kd.AYAR_TANIDIK)),
                          ("AyarBozuk", str(kd.AYAR_BOZUK)), ("AyarDegerBeklenmedik", str(kd.AYAR_DEGER_BEKLENMEDIK)),
                          ("AyarYedekEki", f"'{kd.AYAR_YEDEK_EKI}'"), ("AyarYedekSiniri", str(kd.AYAR_YEDEK_SINIRI))):
            m = re.search(r"^\s*" + ad + r"\s*=\s*(.+?);", kod, re.M)
            self.assertTrue(m, ad)
            self.assertEqual(m.group(1), deger, ad)
        bicim = pascal_govde(kod, "function", "GuncellemeYazimBicimi")
        for parca in ("if Trim(Metin) = '' then", "Result := AyarYok", "else if not AyarGovdesiGecerli(Metin) then",
                      "Result := AyarBozuk", "if P = 0 then",
                      "(Copy(Metin, P, 4) = 'true') and DegerSinirindaMi(Metin, P + 4)",
                      "(Copy(Metin, P, 5) = 'false') and DegerSinirindaMi(Metin, P + 5)",
                      "Result := AyarDegerBeklenmedik;"):
            self.assertIn(parca, bicim)
        self.assertIn("Pos(Copy(Metin, I, 1), ',}] ' + #9 + #10 + #13) > 0",
                      pascal_govde(kod, "function", "DegerSinirindaMi"))
        yedek = pascal_govde(kod, "function", "AyarYedekAdi")
        for parca in ("Result := Yol + AyarYedekEki;", "while FileExists(Result) do", "if N > AyarYedekSiniri then",
                      "Result := Yol + AyarYedekEki + '-' + IntToStr(N);"):
            self.assertIn(parca, yedek)
        uygula = pascal_govde(kod, "procedure", "GuncellemeTercihiniUygula")
        sira = [uygula.index(p) for p in (
            "if not AyarDosyasiniOku(Yol, Ham) then", "Metin := AyarMetni(Ham);",
            "if not GuncellemeKarari(", "Bicim := GuncellemeYazimBicimi(Metin);",
            "if Bicim = AyarDegerBeklenmedik then", "if Bicim = AyarBozuk then",
            "if (Yedek = '') or not SaveStringToFile(Yedek, Ham, False) then",
            "SaveStringToFile(Yol, Utf8Encode(GuncellemeAyariniYerlestir(Metin, Yeni)), False)")]
        self.assertEqual(sira, sorted(sira))
        oku = pascal_govde(kod, "function", "AyarDosyasiniOku")
        self.assertIn("Result := LoadStringFromFile(Yol, Ham);", oku)

    def test_iss_sayfa_kutu_ve_ayar_kurallari_python_karsiligiyla_ayni(self):
        import guncelleme
        kod = iss_bolumu("Code")
        self.assertEqual(kd.GUNCELLEME_AYAR_ANAHTARI, guncelleme.AYAR_ANAHTARI)
        for ad, deger in (("AyarDosyasi", f"'{kd.AYAR_DOSYASI}'"),
                          ("GuncellemeAyarAnahtari", f"'{kd.GUNCELLEME_AYAR_ANAHTARI}'"),
                          ("GizlilikPolitikasiAdresi", "'{#AppURL}#privacy-policy'")):
            m = re.search(r"^\s*" + ad + r"\s*=\s*(.+?);", kod, re.M)
            self.assertTrue(m, ad)
            self.assertEqual(m.group(1), deger, ad)
        self.assertIn('#define AppURL "https://github.com/hamarat52/sesver"', iss_metni())
        self.assertIn("\n## Privacy policy\n", (ROOT / "README.md").read_text(encoding="utf-8"))
        self.assertIn("ExpandConstant('{param:" + kd.GUNCELLEME_PARAMETRESI.lstrip("/") + "|}')", kod)

        baslat = pascal_govde(kod, "procedure", "InitializeWizard")
        for parca in ("CreateCustomPage(wpSelectTasks, CustomMessage('GizlilikSayfaBaslik')",
                      "GuncellemeKutusu := TNewCheckBox.Create(GuncellemeSayfasi);",
                      "GuncellemeKutusu.Caption := CustomMessage('GuncellemeSecenegi');",
                      "GuncellemeKutusu.Checked := True;", "CustomMessage('GizlilikOzeti')",
                      "CustomMessage('GuncellemeAciklama')", "GizlilikBaglantisi.OnClick := @GizlilikBaglantisiClick;"):
            self.assertIn(parca, baslat)
        self.assertIn("ShellExecAsOriginalUser('open', GizlilikPolitikasiAdresi,",
                      pascal_govde(kod, "procedure", "GizlilikBaglantisiClick"))
        adim = pascal_govde(kod, "procedure", "CurStepChanged")
        # Seçim ilk kurulumun atlanmasından (sessiz kurulum) önce uygulanır.
        self.assertLess(adim.index("GuncellemeTercihiniUygula();"),
                        adim.index("WizardSilent() and not KomutSatirindaVar(OrtamKurParametresi)"))
        sayfa = pascal_govde(kod, "procedure", "CurPageChanged")
        self.assertIn("if CurPageID = GuncellemeSayfasi.ID then", sayfa)
        self.assertIn("GuncellemeKutusunuHazirla();", sayfa)
        hazirla = pascal_govde(kod, "procedure", "GuncellemeKutusunuHazirla")
        for parca in ("if Klasor = GuncellemeKutusuKlasoru then", "GuncellemeKutusu.Checked := Parametre = 1",
                      "GuncellemeAyariAcikMi(AyarMetniniOku(AddBackslash(Klasor) + AyarDosyasi))"):
            self.assertIn(parca, hazirla)
        uygula = pascal_govde(kod, "procedure", "GuncellemeTercihiniUygula")
        for parca in ("Sessiz := WizardSilent() or (GuncellemeKutusuKlasoru = '');",
                      "GuncellemeKarari(Sessiz, GuncellemeParametresi(), GuncellemeKutusu.Checked, Mevcut, Yeni)",
                      "SaveStringToFile(Yol, Utf8Encode(GuncellemeAyariniYerlestir(Metin, Yeni)), False)"):
            self.assertIn(parca, uygula)
        karar = pascal_govde(kod, "function", "GuncellemeKarari")
        for parca in ("if Parametre < 0 then", "Yeni := Parametre = 1;", "Yeni := Kutu;", "Result := Yeni <> Mevcut;"):
            self.assertIn(parca, karar)
        self.assertIn("(Length(G) >= 2) and (Copy(G, 1, 1) = '{') and (Copy(G, Length(G), 1) = '}')",
                      pascal_govde(kod, "function", "AyarGovdesiGecerli"))
        konum = pascal_govde(kod, "function", "GuncellemeDegerKonumu")
        for parca in ("Pos('\"' + GuncellemeAyarAnahtari + '\"', Metin)", "I := P + Length(GuncellemeAyarAnahtari) + 2;",
                      "(Copy(Metin, I, 1) <= ' ')", "if Copy(Metin, I, 1) <> ':' then"):
            self.assertIn(parca, konum)
        self.assertIn("Result := Copy(Metin, P, 5) <> 'false';", pascal_govde(kod, "function", "GuncellemeAyariAcikMi"))
        yerlestir = pascal_govde(kod, "function", "GuncellemeAyariniYerlestir")
        for parca in ("Result := '{' + #10 + '  \"' + GuncellemeAyarAnahtari + '\": ' + Deger + #10 + '}' + #10;",
                      "Pos(Copy(Metin, Son, 1), ',}] ' + #9 + #10 + #13) = 0",
                      "Result := Copy(Metin, 1, P - 1) + Deger + Copy(Metin, Son, Length(Metin));",
                      "if Copy(TrimLeft(Kalan), 1, 1) = '}' then",
                      "+ Deger + #10 + TrimLeft(Kalan)", "+ Deger + ',' + Kalan;"):
            self.assertIn(parca, yerlestir)

    def test_sayfa_metinleri_tr_ve_en(self):
        import json
        mesajlar = iss_bolumu("CustomMessages")
        tr = dict(re.findall(r"^turkish\.([A-Za-z0-9]+)=(.*)$", mesajlar, re.M))
        en = dict(re.findall(r"^english\.([A-Za-z0-9]+)=(.*)$", mesajlar, re.M))
        # Kutunun adı uygulamanın Ayarlar'daki etiketiyle aynı (iki dilde).
        en_katalog = json.loads((ROOT / "locales" / "en.json").read_text(encoding="utf-8"))
        self.assertIn('label=t("Açılışta güncellemeleri denetle")', (ROOT / "app.py").read_text(encoding="utf-8"))
        self.assertEqual(tr["GuncellemeSecenegi"], "Açılışta güncellemeleri denetle")
        self.assertEqual(en["GuncellemeSecenegi"], en_katalog["Açılışta güncellemeleri denetle"])
        for d, ayarlar in ((tr, "Ayarlar"), (en, "Settings")):
            self.assertIn("Hugging Face", d["GizlilikOzeti"])
            self.assertIn("GitHub", d["GuncellemeAciklama"])
            self.assertIn(ayarlar, d["GuncellemeAciklama"])
            self.assertIn("github.com/hamarat52/sesver#privacy-policy", d["GizlilikBaglantisi"])
            for ad in ("GizlilikSayfaBaslik", "GizlilikSayfaAciklama", "GizlilikOzeti", "GuncellemeSecenegi",
                       "GuncellemeAciklama", "GizlilikBaglantisi", "OrtamHataMetniGunluksuz", "OrtamIptalMetniGunluksuz"):
                self.assertNotIn("\u2014", d[ad], ad)  # em dash yok


class CodeBolumuStatikTests(unittest.TestCase):
    """ISCC'siz statik denetim: Inno'nun satır ayrıştırıcısı ve Pascal blok dengesi."""

    def test_code_bolumunde_satir_basi_koseli_parantez_ve_yabanci_diyez_yok(self):
        sorunlar = code_satir_sorunlari(iss_metni())
        self.assertEqual(sorunlar, [], "\n".join(f"SesVer.iss:{n}: {neden}\n    {s}" for n, neden, s in sorunlar))

    def test_denetim_kendisi_hatayi_yakalar(self):
        # 1.4.1'de CI'ı kıran biçim (TaskDialogMsgBox düğme dizisi yeni satırda "[" ile).
        kotu = ("[Setup]\nAppName=X\n[Code]\nbegin\n  Cevap := TaskDialogMsgBox('a', 'b', mbConfirmation, MB_YESNO,\n"
                "    ['Sakla', 'Sil'], 0);\n  S := 'x' +\n    #13#10 + 'y';\n#ifdef DEBUG\n#endif\nend;\n")
        sorunlar = code_satir_sorunlari(kotu)
        self.assertEqual([n for n, _, _ in sorunlar], [6, 8])
        self.assertIn("Invalid section tag", sorunlar[0][1])
        # Düzgün biçim (dizi önceki satırda başlar) temiz.
        iyi = kotu.replace("MB_YESNO,\n    ['Sakla'", "MB_YESNO, [\n    'Sakla'").replace("+\n    #13#10", "+ #13#10")
        self.assertEqual(code_satir_sorunlari(iyi), [])

    def test_pascal_bloklari_dengeli(self):
        acan, kapanan = pascal_blok_dengesi(iss_bolumu("Code"))
        self.assertGreater(acan, 50)
        self.assertEqual(acan, kapanan)
        # Denetim yorum ve metin içindeki kelimeleri saymaz.
        self.assertEqual(pascal_blok_dengesi("// begin\n{ try }\nS := 'case end';\nbegin\nend;"), (1, 1))


# ---------------------------------------------------------------- 1.4.1: kaldırırken bileşenleri sakla

class BilesenSaklamaTests(unittest.TestCase):
    """Kaldırma: python-embed\\ / .venv\\ (~3 GB) etkileşimli kaldırmada sorulur, sessizde silinir
    (/BILESENLERISAKLA ile saklanır). Gerçek kaldırma CI'da (build: Kaldırma testi; full-launch: ölçüm)."""

    def test_bilesenler_uninstalldelete_listesinde_degil(self):
        silinen = iss_bolumu("UninstallDelete")
        self.assertNotRegex(silinen, r'(?m)^Type:.*Name: "\{app\}\\(python-embed|\.venv)"')
        # Diğer geçici dosyalar eskisi gibi silinir.
        for ad in ("pbs_tmp", "__pycache__", "sesver_log.txt", "kurulum_log.txt"):
            self.assertIn(ad, silinen)

    def test_karar_sessizde_sil_parametreyle_sakla_etkilesimde_sor(self):
        kod = iss_bolumu("Code")
        self.assertIn("BilesenSaklaParametresi = '/BILESENLERISAKLA';", kod)
        ilk = pascal_govde(kod, "function", "InitializeUninstall")
        self.assertIn("BilesenleriSakla := UninstallSilent() and KomutSatirindaVar(BilesenSaklaParametresi);", ilk)
        adim = pascal_govde(kod, "procedure", "CurUninstallStepChanged")
        # Soru yalnız etkileşimli kaldırmada ve dosyalar silinmeden önce (usUninstall), bileşen varsa.
        self.assertRegex(adim, r"\(CurUninstallStep = usUninstall\) and not UninstallSilent\(\) and\s+"
                               r"\(DirExists\(App \+ '\\python-embed'\) or DirExists\(App \+ '\\\.venv'\)\) then\s+"
                               r"BilesenleriSakla := BilesenSaklamaSorusu\(App\);")
        # Silme SesVer dosyalarından sonra (usPostUninstall) ve yalnız saklanmadıysa.
        sonra = adim.split("if CurUninstallStep = usPostUninstall then")[1]
        self.assertLess(sonra.index("if BilesenleriSakla then"), sonra.index("IndirilenBilesenleriSil(App);"))
        self.assertIn("Log('Kaldirma: indirilen bilesenler saklandi", sonra)  # CI bu satırı arar (ASCII)
        self.assertIn("Log('Kaldirma: indirilen bilesenler siliniyor", sonra)
        sil = pascal_govde(kod, "procedure", "IndirilenBilesenleriSil")
        self.assertIn("DelTree(App + '\\python-embed', True, True, True)", sil)
        self.assertIn("DelTree(App + '\\.venv', True, True, True)", sil)
        self.assertNotRegex(sil, r"seslerim|outputs")  # kullanıcı verisine dokunulmaz
        self.assertIn("RemoveDir(App)", sil)  # yalnız boşsa kalkar

    def test_soru_metni_dugmeleri_ve_varsayilan(self):
        kod = iss_bolumu("Code")
        soru = pascal_govde(kod, "function", "BilesenSaklamaSorusu")
        self.assertIn("TaskDialogMsgBox(CustomMessage('KaldirSaklaBaslik')", soru)
        self.assertIn("MB_YESNO", soru)
        # İlk düğme (Evet, varsayılan) = Sakla; yalnız açıkça "Sil" seçilirse silinir.
        self.assertLess(soru.index("KaldirSaklaDugmesi"), soru.index("KaldirSilDugmesi"))
        self.assertIn("Result := Cevap <> IDNO;", soru)
        self.assertIn("MB_YESNO, [SaklaDugmesi, SilDugmesi], 0);", soru)  # 1. düğme = Sakla
        self.assertIn("GBMetni(IndirilenBilesenBoyutu(App))", soru)
        mesajlar = iss_bolumu("CustomMessages")
        tr = dict(re.findall(r"^turkish\.([A-Za-z0-9]+)=(.*)$", mesajlar, re.M))
        en = dict(re.findall(r"^english\.([A-Za-z0-9]+)=(.*)$", mesajlar, re.M))
        for ad in ("KaldirSaklaBaslik", "KaldirSaklaMetni", "KaldirSaklaDugmesi", "KaldirSaklaNotu",
                   "KaldirSilDugmesi", "KaldirSilNotu"):
            for d in (tr, en):
                self.assertIn(ad, d)
                self.assertNotIn("\u2014", d[ad], ad)
        self.assertEqual((tr["KaldirSaklaDugmesi"], tr["KaldirSilDugmesi"]), ("Sakla", "Sil"))
        for d in (tr, en):
            self.assertIn("%1 GB", d["KaldirSaklaMetni"])  # gerçek boyut
            self.assertIn("%2", d["KaldirSaklaMetni"])  # klasör yolu
            self.assertIn("%1 GB", d["KaldirSilNotu"])
        self.assertIn("yeniden indirilmez", tr["KaldirSaklaMetni"])
        self.assertIn("Seslerim ve outputs", tr["KaldirSaklaMetni"])

    def test_boyut_hesabi_baglanti_noktasina_girmez_ve_gb_metni(self):
        kod = iss_bolumu("Code")
        boyut = pascal_govde(kod, "function", "KlasorBoyutu")
        self.assertIn("FILE_ATTRIBUTE_REPARSE_POINT = 0", boyut)
        self.assertIn("FindClose(K)", boyut)
        gb = pascal_govde(kod, "function", "GBMetni")
        self.assertIn("(Bayt * 10 + BirGB div 2) div BirGB", gb)
        self.assertRegex(iss_metni(), r"(?m)^\s*BirGB = 1073741824;")

        # Python karşılığı (onda bir yuvarlama, TR virgül / EN nokta).
        def gb_metni(bayt, dil="turkish"):
            onda = (bayt * 10 + 1073741824 // 2) // 1073741824
            return f"{onda // 10}{'.' if dil == 'english' else ','}{onda % 10}"

        self.assertEqual(gb_metni(3_300_000_000), "3,1")
        self.assertEqual(gb_metni(3_300_000_000, "english"), "3.1")
        self.assertEqual(gb_metni(0), "0,0")

    def test_ayni_yere_yeniden_kurulumda_isaret_ayni_kalir(self):
        """Bat'ın kurulum işareti yalnız kilit\\*.txt içeriği + voxcpm sürümünden hesaplanır (kurulum yolu,
        tarih ya da makine içermez); kurulum programı kilit\\*.txt'yi olduğu gibi kopyalar. Aynı sürüm aynı
        yere kurulunca işaret aynıdır → bat ':kurulum'da doğrudan :baslat'a gider (indirme yok)."""
        import glob
        import hashlib
        import os
        import shutil
        import tempfile
        bat = "\r\n".join(bat_satirlari())
        hesap = [s for s in bat_satirlari() if "kilit_sha256=" in s and "glob.glob('kilit/*.txt')" in s]
        self.assertEqual(len(hesap), 1, "işaret hesabı tek satır olmalı")
        self.assertNotRegex(hesap[0], r"%CD%|%~dp0|getcwd|abspath|time|platform")
        akis = bat.split("\r\n:kurulum\r\n")[1].split("\r\n:esitle\r\n")[0]
        self.assertIn('if not exist "%MARK%" goto :ilk_kurulum', akis)
        self.assertIn('if not "%SV_ISARET%"=="%SV_BEKLENEN%" goto :esitle', akis)
        self.assertTrue(akis.rstrip().endswith("goto :baslat"))
        self.assertIn('Source: "{#SrcRoot}\\kilit\\*.txt"; DestDir: "{app}\\kilit"', iss_bolumu("Files"))

        def isaret(kok):
            onceki = os.getcwd()
            os.chdir(kok)
            try:
                h = hashlib.sha256()
                for f in sorted(glob.glob("kilit/*.txt")):
                    h.update(open(f, "rb").read())
                return "kilit_sha256=" + h.hexdigest() + " voxcpm=2.0.3"
            finally:
                os.chdir(onceki)

        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            for hedef in (a, b):
                shutil.copytree(ROOT / "kilit", Path(hedef) / "kilit")
            self.assertEqual(isaret(a), isaret(b))
            self.assertEqual(isaret(a), isaret(ROOT))
            # Kilit değişirse (gerçek güncelleme) işaret değişir → :esitle yalnız eksik/değişeni kurar.
            (Path(b) / "kilit" / "pip.txt").write_text("degisti", encoding="utf-8")
            self.assertNotEqual(isaret(a), isaret(b))
        self.assertIn('set "VOXCPM_SURUM=2.0.3"', bat)


class KurulumDurdurTests(unittest.TestCase):
    """"Kurulumu durdur": süreç ağacı yeniden denemeli sonlanır (CI 43265425949).

    Tek ``taskkill /T /F /PID <cmd>`` ağacın anlık listesini alıp kökü (bat'ın cmd.exe'si) EN SON
    sonlandırır; kök o arada bitmekte olan kısa ömürlü python'un (pip --version, sürüm okuma)
    ardından sonrakini başlatabiliyor, yeni süreç listede olmadığı için yetim kalıyordu.
    """

    PS1 = ROOT / "windows" / "kurulum_durdur.ps1"

    @classmethod
    def setUpClass(cls):
        cls.ps1 = cls.PS1.read_text(encoding="utf-8")
        cls.kod = iss_bolumu("Code")

    def test_betik_kurulur_ve_ascii(self):
        self.PS1.read_bytes().decode("ascii")  # Windows PowerShell 5.1 BOM'suz dosyayı ANSI okur
        self.assertIn('Source: "kurulum_durdur.ps1"; DestDir: "{app}"; Flags: ignoreversion', iss_bolumu("Files"))
        self.assertRegex(self.kod, r"(?m)^\s*OrtamDurdurBetigi = 'kurulum_durdur\.ps1';")

    def test_sihirbaz_betigi_calistirir_eski_yol_yedek(self):
        govde = pascal_govde(self.kod, "procedure", "OrtamSureciniDurdur")
        self.assertIn("ExpandConstant('{app}\\') + OrtamDurdurBetigi", govde)
        self.assertIn("'-NoProfile -NonInteractive -ExecutionPolicy Bypass -File \"' + Betik + '\" -Kok ' +", govde)
        self.assertIn("' -Klasor \"' + ExpandConstant('{app}') + '\"'", govde)
        self.assertIn("{sys}\\WindowsPowerShell\\v1.0\\powershell.exe", govde)
        # Betik çalıştıysa sonucu kesin: doğrulanmamış bir PID'e taskkill yedeği uygulanmaz (D1/D3).
        self.assertIn("SW_HIDE, ewWaitUntilTerminated, RC, @BaslaticiCiktisi) then\n      begin\n"
                      "        Log('Sonlandırma çıkış kodu: ' + IntToStr(RC));", govde)
        self.assertNotIn("((RC = 0) or (RC = 2))", govde)
        self.assertIn("if RC = 1 then", govde)
        self.assertIn("Log('Sonlandırma betiği başlatılamadı (", govde)
        # Betik önce; yoksa ya da başarısızsa eski taskkill / PowerShell yolu.
        self.assertLess(govde.index("OrtamDurdurBetigi"), govde.index("'/T /F /PID '"))
        # İptal düğmesi ve PID'siz yedek bu yordamdan geçer.
        self.assertIn("OrtamSureciniDurdur(Pid);", self.kod)
        self.assertIn("OrtamSureciniDurdur(0);", self.kod)

    def test_kok_once_sonra_agac_ve_klasor_tekrarli(self):
        p = self.ps1
        kok = p.index("foreach ($k in $kokler) {\n    Stop-Process")
        dongu = p.index("while ($true)")
        self.assertLess(kok, dongu)  # kök önce: yeni alt süreç doğamaz
        self.assertNotIn("taskkill", p.split("param(")[1])  # tek seferlik ağaç öldürmeye dayanmaz
        # Ağaç: üst süreç numarası + oluşma zamanı (PID yeniden kullanımına karşı), torunlar dahil.
        self.assertIn("if ($p.CreationDate -lt $agac[$ust]) { continue }", p)
        self.assertIn("} while ($eklendi)", p)
        # Güvenlik ağı yalnız SesVer'in python-embed'i ve kökten sonra başlamış süreçler:
        # kurulumdan önce açılmış SesVer'e ve başka uygulamalara dokunulmaz.
        self.assertIn("$embed = (Join-Path $Klasor 'python-embed')", p)
        self.assertIn("StartsWith($embed, [StringComparison]::OrdinalIgnoreCase) -and $p.CreationDate -ge $esik", p)
        self.assertIn("if ($bosTur -ge 3) { break }", p)  # ardışık boş turlar: geç doğan da yakalanır
        self.assertIn("$bitis = $basla.AddSeconds($SureSn)", p)
        # Son denetim ve anlamlı çıkış kodları.
        self.assertIn("$kalan = @(Surecler | Where-Object { Kaynak $_ })", p)
        for kod in ("exit 0", "exit 1", "exit 2"):
            self.assertIn(kod, p)
        self.assertNotIn("Stop-Process -Name", p)  # adla toplu öldürme yok

    # --- siberguvenlik D1-D3 (PowerShell bu makinede yok: yapı testleri; gerçek çalıştırma CI build) ---
    def test_d1_kok_ad_ve_komut_satiriyla_dogrulanir(self):
        p = self.ps1
        self.assertIn("function KurulumKokuMu($p) {\n    return ($p -and $p.Name -eq 'cmd.exe' -and "
                      "$p.CommandLine -like '*WINDOWS_BASLAT.bat*/yalniz-kurulum*')", p)
        # -Kok verilse de kök yalnız doğrulananlardır; aday (PID'in şimdiki sahibi) kök sayılmaz.
        self.assertIn("$aday = @($tum | Where-Object { [int]$_.ProcessId -eq $Kok })", p)
        self.assertIn("$kokler = @($aday | Where-Object { KurulumKokuMu $_ })", p)
        self.assertIn("ona ve alt sureclerine dokunulmaz", p)
        self.assertEqual(p.count("$aday"), 4)  # yalnız tanım, süzme, sayım ve ileti: durdurulmaz
        # Durdurma ve ağaç tohumu yalnız $kokler'den; doğrulanmayan kökün çocukları ağaca girmez.
        self.assertIn("foreach ($k in $kokler) { $agac[[int]$k.ProcessId] = $k.CreationDate }", p)
        self.assertIn("foreach ($k in $kokler) {\n    Stop-Process -Id ([int]$k.ProcessId) -Force", p)
        stoplar = [m.start() for m in re.finditer(r"Stop-Process", p)]
        self.assertEqual(len(stoplar), 2)  # kök (doğrulanmış) + Kaynak'tan geçen süreç
        self.assertIn("foreach ($p in $kalan) {\n            Stop-Process", p)
        # Doğrulanan kök yoksa çıkış 2 (yetim taraması yine yapılır, D3).
        self.assertIn("if ($kokler.Count -eq 0) {\n    Write-Output (\"kurulum_durdur: kok yoktu", p)
        self.assertIn("exit 2\n}\nWrite-Output (\"kurulum_durdur: tamam", p)

    def test_d2_canli_ust_surec_kayitli_olusma_zamaniyla_eslesmeli(self):
        p = self.ps1
        dongu = p.split("do {\n        $eklendi = $false", 1)[1].split("} while ($eklendi)", 1)[0]
        self.assertIn("if ($canli.ContainsKey($ust) -and $canli[$ust].CreationDate -ne $agac[$ust]) { continue }", dongu)
        self.assertIn("if ($p.CreationDate -lt $agac[$ust]) { continue }", dongu)
        self.assertLess(dongu.index("$canli.ContainsKey($ust)"), dongu.index("$agac[$id] = $p.CreationDate"))
        self.assertIn("foreach ($p in $tum) { $canli[[int]$p.ProcessId] = $p }", p)  # her turda tazelenir
        # 'agac' kaynağı da PID + oluşma zamanı ikilisiyle.
        self.assertIn("if ($agac.ContainsKey($id) -and $agac[$id] -eq $p.CreationDate) { return 'agac' }", p)

    def test_d3_kok_yokken_yetim_taramasi_kurulum_baslangicindan_sonrasi(self):
        p = self.ps1
        kokyok = p.split("} else {\n    Write-Output \"kurulum_durdur: dogrulanan kok surec yok", 1)[1].split("\n}\n", 1)[0]
        # Kurulum başlangıcı = bat'ın ilk iş yazdığı kurulum_pid.txt'nin yazılma zamanı
        # (oluşma zamanı değil: Windows dosya tüneli silinip yeniden yazılan dosyaya eskisini verebilir).
        self.assertIn("$pd = Get-Item -LiteralPath $pidDosyasi", kokyok)
        self.assertIn("if ($pd) { $esik = $pd.LastWriteTime }", kokyok)
        self.assertNotIn("CreationTime", p)
        # Başlangıç bilinmiyorsa hiçbir şey durdurulmaz.
        self.assertIn("python-embed taramasi yapilmaz\"\n        exit 2", kokyok)
        self.assertLess(p.index("python-embed taramasi yapilmaz"), p.index("Stop-Process"))
        self.assertIn("$pidDosyasi = Join-Path $Klasor 'kurulum_pid.txt'", p)
        # Yalnız python-embed'den ve eşikten sonra başlamışlar; eşik yoksa klasör kuralı kapalı.
        self.assertIn("if ($null -ne $esik -and $p.ExecutablePath -and $p.ExecutablePath.StartsWith($embed, "
                      "[StringComparison]::OrdinalIgnoreCase) -and $p.CreationDate -ge $esik) { return 'klasor' }", p)
        # Sihirbaz her kurulumdan önce kurulum_pid.txt'yi siler (eşik eski bir koşudan kalmaz),
        # bat da ilk iş olarak yeniden yazar.
        self.assertIn("DeleteFile(PidYolu);", self.kod)
        bat = BAT_YOLU.read_text(encoding="utf-8")
        self.assertLess(bat.index('del /f /q "kurulum_pid.txt"'), bat.index(':ilk_kurulum'))

    def test_ci_d1_d3_senaryosu_gercek_windowsta(self):
        wf = (ROOT / ".github" / "workflows" / "windows-installer.yml").read_text(encoding="utf-8")
        blok = wf.split("--- kurulum_durdur.ps1: yanlış kök (D1) + kök yokken yetim (D3) ---", 1)[1].split("} finally {", 1)[0]
        sira = [blok.index(s) for s in ("$eski = Start-Process -FilePath $embedPy", "$yabanci = Start-Process",
                                         "Set-Content -LiteralPath $pidD -Value $yabanci.Id",
                                         "$yetim = Start-Process -FilePath $embedPy",
                                         "-File $durdur -Kok $yabanci.Id -Klasor $app")]
        self.assertEqual(sira, sorted(sira))  # eski < kurulum başlangıcı < yetim < durdurma
        for beklenen in ("if ($dkod -ne 2)", "'D1: kurulum cmd.exe''si olmayan süreç durduruldu'",
                         "'D1: yabancı sürecin alt süreci durduruldu'",
                         "'D3: kurulumdan önce açılmış python-embed süreci durduruldu'",
                         "'D3: kök yokken kurulumdan sonra doğmuş python-embed süreci durdurulmadı'"):
            self.assertIn(beklenen, blok)

    def test_ci_iptal_testi_sihirbazla_ayni_betigi_kullanir(self):
        wf = (ROOT / ".github" / "workflows" / "windows-installer.yml").read_text(encoding="utf-8")
        blok = wf.split("::group::Yalnız-kurulum kipi (sihirbaz akışı) + iptal", 1)[1].split("::endgroup::", 1)[0]
        self.assertIn("$durdur = Join-Path $app 'kurulum_durdur.ps1'", blok)
        self.assertIn("& $winPs -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $durdur -Kok $ykPid -Klasor $app", blok)
        self.assertIn('$winPs = "$env:SystemRoot\\System32\\WindowsPowerShell\\v1.0\\powershell.exe"', blok)
        self.assertNotIn("& taskkill.exe /T /F /PID $ykPid", blok)
        self.assertIn("foreach ($gecikme in 0, 700, 1500)", blok)  # yarışa farklı anlarda denk gel
        # Denetim gevşemedi: betik 0, kök yok, SesVer klasöründen süreç yok (hemen ve 3 sn sonra),
        # tamam işareti yok.
        self.assertIn("if ($dkod -ne 0)", blok)
        self.assertIn("'İptalden hemen sonra SesVer klasöründen süreç kaldı'", blok)
        self.assertIn("Start-Sleep -Seconds 3", blok)
        self.assertIn("'İptalden 3 sn sonra SesVer klasöründen süreç kaldı'", blok)
        self.assertIn("ExecutablePath.StartsWith($app, [StringComparison]::OrdinalIgnoreCase)", blok)
        self.assertIn("'İptal edilen kurulum tamam işareti yazmış'", blok)


if __name__ == "__main__":
    unittest.main()
