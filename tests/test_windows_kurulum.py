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
        self.assertIn("hermes.agent.hamarat@gmail.com", tr["OrtamHataMetni"])
        self.assertIn("kurulum_log.txt", tr["OrtamHataMetni"])
        self.assertIn("3 GB", tr["OrtamSayfaAciklama"])


if __name__ == "__main__":
    unittest.main()
