"""Kurulum kilitleri (kilit/*.txt): biçim, paketleme ve gerçek pip ile hash davranışı.

Gerçek pip testleri ağsız çalışır: küçük sahte tekerlekler geçici bir klasöre yazılır,
pip PIP_NO_INDEX + PIP_FIND_LINKS ile yalnız oradan kurar. macOS başlatıcısı
(macos_ortak.sh) geçici bir proje klasöründe, python-embed/ yerine konan bir sanal
ortamla uçtan uca koşturulur: özet bozukken kurulum durur, işaret yazılmaz, mesaj
SHA-256'yı söyler; özet düzelince sonraki açılış kurulumu tamamlar.
"""
import base64
import csv
import hashlib
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KILIT = ROOT / "kilit"
BASH = "/bin/bash"
PY_ETIKET = f"py{sys.version_info[0]}{sys.version_info[1]}"
DESTEKLI_PY = (3, 10) <= sys.version_info[:2] <= (3, 12)


def _gereksinimler(metin):
    """Kilit dosyasındaki (ad, sürüm, özetler) üçlüleri; satır devamları birleştirilir."""
    birlesik = re.sub(r"\\\n\s*", " ", metin)
    sonuc = []
    for satir in birlesik.splitlines():
        satir = satir.strip()
        if not satir or satir.startswith(("#", "--")):
            continue
        m = re.match(r"^([A-Za-z0-9_.\-]+)==([^\s;]+)", satir)
        sonuc.append((m.group(1) if m else satir, m.group(2) if m else None,
                      re.findall(r"--hash=sha256:([0-9a-f]{64})", satir)))
    return sonuc


class KilitBicimiTests(unittest.TestCase):
    BEKLENEN = {"pip.txt", "voxcpm.txt", "torch-pypi.txt", "torch-cu126.txt", "torch-cu128.txt",
                "torch-cu130.txt"} | {f"{p}-py3{v}.txt" for p in ("macos-arm64", "windows-x64")
                                       for v in (10, 11, 12)}

    def test_beklenen_dosyalar_var(self):
        self.assertEqual({p.name for p in KILIT.glob("*.txt")}, self.BEKLENEN)

    def test_her_paket_sabit_surumlu_ve_ozetli(self):
        for dosya in KILIT.glob("*.txt"):
            paketler = _gereksinimler(dosya.read_text(encoding="utf-8"))
            self.assertTrue(paketler, dosya.name)
            for ad, surum, ozetler in paketler:
                self.assertIsNotNone(surum, f"{dosya.name}: sabit olmayan satır {ad}")
                self.assertTrue(ozetler, f"{dosya.name}: {ad} özetsiz")

    def test_torch_yalniz_torch_katmaninda(self):
        for dosya in KILIT.glob("*-py3*.txt"):
            adlar = {ad.lower() for ad, _, _ in _gereksinimler(dosya.read_text(encoding="utf-8"))}
            self.assertFalse(adlar & {"torch", "torchaudio"}, dosya.name)
            self.assertIn("torchcodec", adlar, dosya.name)
            self.assertNotIn("voxcpm", adlar, dosya.name)

    def test_cuda_katmanlari_kendi_indeksinden(self):
        for etiket in ("cu126", "cu128", "cu130"):
            metin = (KILIT / f"torch-{etiket}.txt").read_text(encoding="utf-8")
            self.assertIn(f"--index-url https://download.pytorch.org/whl/{etiket}", metin)
            for ad, surum, _ in _gereksinimler(metin):
                self.assertTrue(surum.endswith(f"+{etiket}"), f"{etiket}: {ad}=={surum}")

    def test_hizlandirmanin_onerebildigi_her_etiketin_kilidi_var(self):
        sys.path.insert(0, str(ROOT))
        import hizlandirma
        for etiket in (hizlandirma.CUDA_NEW, hizlandirma.CUDA_OLD, hizlandirma.CUDA_BLACKWELL):
            self.assertTrue((KILIT / f"torch-{etiket}.txt").is_file(), etiket)

    def test_voxcpm_ve_pip_kilidi_baslaticilarla_ayni(self):
        vox = _gereksinimler((KILIT / "voxcpm.txt").read_text(encoding="utf-8"))
        self.assertEqual([(a, s) for a, s, _ in vox], [("voxcpm", "2.0.3")])
        self.assertIn('VOXCPM_SURUM="2.0.3"', (ROOT / "macos_ortak.sh").read_text(encoding="utf-8"))
        self.assertIn('set "VOXCPM_SURUM=2.0.3"', (ROOT / "WINDOWS_BASLAT.bat").read_text(encoding="utf-8"))
        adlar = {a for a, _, _ in _gereksinimler((KILIT / "pip.txt").read_text(encoding="utf-8"))}
        self.assertEqual(adlar, {"pip", "setuptools"})

    def test_baslaticilar_kilitsiz_pip_kurulumu_yapmaz(self):
        mac = (ROOT / "macos_ortak.sh").read_text(encoding="utf-8")
        bat = (ROOT / "WINDOWS_BASLAT.bat").read_text(encoding="utf-8")
        for ad, metin in (("macos_ortak.sh", mac), ("WINDOWS_BASLAT.bat", bat)):
            komutlar = [s for s in metin.splitlines()
                        if "pip install" in s and not s.lstrip().upper().startswith(("REM", "#"))]
            self.assertTrue(komutlar, ad)
            for s in komutlar:
                self.assertTrue("--require-hashes" in s or "%KILIT_PIP%" in s, f"{ad}: {s.strip()}")
            self.assertNotIn("latest-release", metin, ad)
            self.assertNotIn("requirements.txt", re.sub(r"(?m)^\s*(REM|#).*$", "", metin), ad)
        kilit_pip = re.search(r'set "KILIT_PIP=([^"]*)"', bat)
        self.assertIsNotNone(kilit_pip)
        self.assertIn("--require-hashes", kilit_pip.group(1))

    def test_kilitler_paketlere_ve_ci_suzgecine_girer(self):
        rel = (ROOT / "macos" / "release_mac.sh").read_text(encoding="utf-8")
        self.assertIn('cp -p kilit/*.txt "$PL/kilit/"', rel)
        iss = (ROOT / "windows" / "SesVer.iss").read_text(encoding="utf-8")
        self.assertIn('Source: "{#SrcRoot}\\kilit\\*.txt"; DestDir: "{app}\\kilit"', iss)
        ci = (ROOT / ".github" / "workflows" / "windows-installer.yml").read_text(encoding="utf-8")
        self.assertIn('- "kilit/**"', ci)


# --------------------------------------------------------------- gerçek pip ile
def _tekerlek(klasor, ad, surum):
    """Saf Python, bağımlılıksız küçük bir tekerlek yazar; (yol, sha256) döner."""
    dist = ad.replace("-", "_")
    dosya = Path(klasor) / f"{dist}-{surum}-py3-none-any.whl"
    di = f"{dist}-{surum}.dist-info"
    icerik = {
        f"{dist}/__init__.py": f"__version__ = {surum!r}\n",
        f"{di}/METADATA": f"Metadata-Version: 2.1\nName: {ad}\nVersion: {surum}\n",
        f"{di}/WHEEL": "Wheel-Version: 1.0\nGenerator: sesver-test\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
    }
    kayit = io.StringIO()
    w = csv.writer(kayit, lineterminator="\n")
    for yol, veri in icerik.items():
        oz = base64.urlsafe_b64encode(hashlib.sha256(veri.encode()).digest()).rstrip(b"=").decode()
        w.writerow([yol, f"sha256={oz}", len(veri.encode())])
    w.writerow([f"{di}/RECORD", "", ""])
    with zipfile.ZipFile(dosya, "w") as z:
        for yol, veri in icerik.items():
            z.writestr(yol, veri)
        z.writestr(f"{di}/RECORD", kayit.getvalue())
    return dosya, hashlib.sha256(dosya.read_bytes()).hexdigest()


def _satir(ad, surum, oz):
    return f"{ad}=={surum} \\\n    --hash=sha256:{oz}\n"


class _PipOrtami(unittest.TestCase):
    """Sahte tekerlekler + python-embed yerine konan sanal ortam (sınıf başına bir kez)."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.tmp = Path(cls._tmp.name)
        cls.tekerlek = cls.tmp / "tekerlekler"
        cls.tekerlek.mkdir()
        cls.oz = {}
        for ad, surum in (("sesver-ornek-pip", "1.0"), ("torch", "2.0+cu130"), ("sesver-ornek-vox", "1.0"),
                          ("sesver-ornek-a", "1.0"), ("sesver-ornek-b", "2.0")):
            cls.oz[ad] = _tekerlek(cls.tekerlek, ad, surum)[1]
        cls.venv = cls.tmp / "venv"
        subprocess.run([sys.executable, "-m", "venv", str(cls.venv)], check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def ortam(self, **ek):
        env = {k: v for k, v in os.environ.items() if not k.startswith(("PIP_", "PYTHON", "VIRTUAL_ENV"))}
        env.update(PIP_NO_INDEX="1", PIP_FIND_LINKS=str(self.tekerlek), PIP_DISABLE_PIP_VERSION_CHECK="1",
                   PIP_NO_CACHE_DIR="1")
        env.update(ek)
        return env

    def proje(self, bozuk=False):
        """Kilitleri sahte paketlerle yazar; bozuk=True ise temel kilitteki bir özet yanlış."""
        proj = Path(tempfile.mkdtemp(dir=self.tmp))
        (proj / "kilit").mkdir()
        k = proj / "kilit"
        (k / "pip.txt").write_text(_satir("sesver-ornek-pip", "1.0", self.oz["sesver-ornek-pip"]))
        (k / "torch-pypi.txt").write_text(_satir("torch", "2.0+cu130", self.oz["torch"]))
        (k / "voxcpm.txt").write_text(_satir("sesver-ornek-vox", "1.0", self.oz["sesver-ornek-vox"]))
        b_oz = "0" * 64 if bozuk else self.oz["sesver-ornek-b"]
        (k / f"macos-arm64-{PY_ETIKET}.txt").write_text(
            _satir("sesver-ornek-a", "1.0", self.oz["sesver-ornek-a"]) + _satir("sesver-ornek-b", "2.0", b_oz))
        return proj

    def kurulu(self):
        out = subprocess.run([str(self.venv / "bin" / "python"), "-m", "pip", "list", "--format=freeze"],
                             capture_output=True, text=True, env=self.ortam()).stdout
        return dict(s.split("==") for s in out.split() if "==" in s)


@unittest.skipUnless(os.name == "posix", "venv/bin yolu")
class GercekPipTests(_PipOrtami):
    def pip(self, *args, cwd):
        return subprocess.run([str(self.venv / "bin" / "python"), "-m", "pip", "install", "--require-hashes",
                               "--only-binary=:all:", *args], cwd=cwd, capture_output=True, text=True,
                              env=self.ortam())

    def test_bozuk_ozet_pip_durur_ve_windows_gunlugu_bunu_yazar(self):
        proj = self.proje(bozuk=True)
        gunluk = proj / "pip_kilit_gunluk.txt"
        r = self.pip("-r", f"kilit/macos-arm64-{PY_ETIKET}.txt", "--log", str(gunluk), cwd=proj)
        self.assertNotEqual(r.returncode, 0)
        # macos_ortak.sh (grep) ve WINDOWS_BASLAT.bat (findstr, --log dosyası) bu metni arar.
        self.assertIn("DO NOT MATCH THE HASHES", r.stdout + r.stderr)
        self.assertIn("DO NOT MATCH THE HASHES", gunluk.read_text(encoding="utf-8", errors="replace"))
        self.assertNotIn("sesver-ornek-a", self.kurulu())  # hiçbir şey kurulmadı

    def test_cuda_kisiti_kilitle_birlikte_calisir(self):
        """Windows eşitlemesi: CUDA torch katmanı kurulur, sürümleri -c ile kısıtlanır, temel
        kilit --require-hashes ile kurulurken torch'a dokunulmaz."""
        proj = self.proje()
        self.assertEqual(self.pip("--no-deps", "-r", "kilit/torch-pypi.txt", cwd=proj).returncode, 0)
        kisit = proj / "kisit.txt"
        kisit.write_text("torch==2.0+cu130\ntorchaudio==2.0+cu130\n")
        r = self.pip("-c", str(kisit), "-r", f"kilit/macos-arm64-{PY_ETIKET}.txt", cwd=proj)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        kurulu = self.kurulu()
        self.assertEqual(kurulu.get("torch"), "2.0+cu130")
        self.assertEqual(kurulu.get("sesver-ornek-b"), "2.0")


HARNESS = r"""#!/bin/bash
cd "$1" || exit 99
SESVER_MOD=app
. ./macos_ortak.sh
osascript() { { printf '%s\n' "$@"; echo "=====PENCERE_SONU====="; } >> "$SAHTE_PENCERE_LOG"; }
curl() { echo "curl $*" >> "$SAHTE_CURL_LOG"; return 22; }
sesver_baslat
"""


@unittest.skipUnless(os.path.exists(BASH) and os.name == "posix", "bash yok")
@unittest.skipUnless(DESTEKLI_PY, "kilit yalnız Python 3.10-3.12 için")
class MacosKilitliKurulumTests(_PipOrtami):
    def baslat(self, proj):
        shutil.copy(ROOT / "macos_ortak.sh", proj / "macos_ortak.sh")
        (proj / "desktop.py").write_text("print('SAHTE DESKTOP CALISTI')\n")
        embed = proj / "python-embed"
        if not embed.exists():
            embed.symlink_to(self.venv, target_is_directory=True)
        harness = proj.parent / f"kosu_{proj.name}.sh"
        harness.write_text(HARNESS)
        self.pencere = proj.parent / f"pencere_{proj.name}.txt"
        env = self.ortam(PATH="/usr/bin:/bin:/usr/sbin:/sbin", HOME=str(self.tmp),
                         SAHTE_PENCERE_LOG=str(self.pencere), SAHTE_CURL_LOG=str(proj.parent / "curl.txt"),
                         SESVER_SISTEM_DILI="tr-TR")
        r = subprocess.run([BASH, str(harness), str(proj)], env=env, stdin=subprocess.DEVNULL,
                           capture_output=True, text=True, timeout=300)
        time.sleep(0.2)
        log = (proj / "sesver_baslatici_log.txt").read_text(encoding="utf-8")
        pencere = self.pencere.read_text(encoding="utf-8") if self.pencere.exists() else ""
        return r, log, pencere

    def test_ozet_uyusmazliginda_durur_isaret_yazilmaz_sonraki_acilis_yeniden_dener(self):
        proj = self.proje(bozuk=True)
        isaret = self.venv / "sesver_kurulum_tamam.txt"
        if isaret.exists():
            isaret.unlink()
        r, log, pencere = self.baslat(proj)
        self.assertEqual(r.returncode, 1, log)
        self.assertFalse(isaret.exists())
        self.assertIn(f"[HATA] Kurulum adımı başarısız oldu: paket kurulumu (kilit/macos-arm64-{PY_ETIKET}.txt)", log)
        self.assertIn("SHA-256 özeti kilit dosyasındakiyle uyuşmuyor", log)
        self.assertIn("İndirilen bir paket doğrulanamadı (SHA-256 özeti tutmuyor)", pencere)
        self.assertNotIn("SAHTE DESKTOP CALISTI", log)

        # Özet düzeltilince (yeni sürüm ya da geçici sorun geçti) aynı ortam kurulumu tamamlar.
        (proj / "kilit" / f"macos-arm64-{PY_ETIKET}.txt").write_text(
            _satir("sesver-ornek-a", "1.0", self.oz["sesver-ornek-a"])
            + _satir("sesver-ornek-b", "2.0", self.oz["sesver-ornek-b"]))
        r, log, _ = self.baslat(proj)
        self.assertEqual(r.returncode, 0, log)
        self.assertRegex(isaret.read_text(), r"^kilit_sha256=[0-9a-f]{64} voxcpm=2\.0\.3\n$")
        self.assertIn("SAHTE DESKTOP CALISTI", log)
        self.assertEqual(self.kurulu().get("sesver-ornek-b"), "2.0")

        # 1.3.0 biçimli işaret: eşitleme çalışır (zaten kurulu olanlar yeniden inmez), işaret yenilenir.
        isaret.write_text("req_sha256=" + "a" * 64 + " voxcpm=2.0.3\n")
        r, log, _ = self.baslat(proj)
        self.assertEqual(r.returncode, 0, log)
        self.assertIn("Paket eşitleme tamamlandı.", log)
        self.assertTrue(isaret.read_text().startswith("kilit_sha256="))

        # Eşitlemede özet bozulursa işaret ESKİ hâliyle kalır.
        isaret.write_text("req_sha256=" + "a" * 64 + " voxcpm=2.0.3\n")
        self.venv_kaldir("sesver-ornek-b")
        (proj / "kilit" / f"macos-arm64-{PY_ETIKET}.txt").write_text(
            _satir("sesver-ornek-a", "1.0", self.oz["sesver-ornek-a"]) + _satir("sesver-ornek-b", "2.0", "1" * 64))
        r, log, _ = self.baslat(proj)
        self.assertEqual(r.returncode, 1, log)
        self.assertIn("paket eşitleme", log)
        self.assertTrue(isaret.read_text().startswith("req_sha256="))

    def venv_kaldir(self, ad):
        subprocess.run([str(self.venv / "bin" / "python"), "-m", "pip", "uninstall", "-y", ad],
                       capture_output=True, env=self.ortam())


if __name__ == "__main__":
    unittest.main()
