"""macOS başlatıcıları: pencere dili (TR/EN) ve Intel Mac uyarısı.

Gerçek pencere açılmaz, hiçbir şey indirilmez: osascript ve curl, PATH'in başına
konan sahte betiklerle değiştirilir (çağrı argümanlarını dosyaya yazarlar). Mimari,
macos_ortak.sh'taki enjekte edilebilir sesver_uname / sesver_proc_translated işlevleri
yeniden tanımlanarak taklit edilir; C başlatıcı sahte osascript yoluyla ayrıca derlenir.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASH = "/bin/bash"  # SesVer.app'in kullandığı kabuk (macOS'ta bash 3.2)

FAKE_OSASCRIPT = """#!/bin/bash
{ printf '%s\\n' "$@"; echo "=====PENCERE_SONU====="; } >> "$SAHTE_PENCERE_LOG"
"""
FAKE_CURL = """#!/bin/bash
echo "curl $*" >> "$SAHTE_CURL_LOG"
exit 22
"""

# macos_ortak.sh'ı yükleyip mimariyi ve Python aramasını taklit eden koşucu.
HARNESS = r"""#!/bin/bash
cd "$1" || exit 99
SESVER_MOD="$2"
. ./macos_ortak.sh
sesver_uname() {
  case "$1" in
    -s) echo "${SAHTE_UNAME_S:-Darwin}" ;;
    -m) echo "$SAHTE_UNAME_M" ;;
  esac
}
sesver_proc_translated() { echo "$SAHTE_TRANSLATED"; }
if [ -n "${SAHTE_APPLE_LANGS:-}" ]; then
  sesver_apple_languages() { printf '%b' "$SAHTE_APPLE_LANGS"; }
  sesver_dil_belirle
fi
# Sistem Python'u bulunmasın (aksi hâlde gerçek bir venv/pip kurulumu başlardı).
command() { if [ "$1" = "-v" ]; then return 1; fi; builtin command "$@"; }
# app modu PATH'in başına /opt/homebrew/bin vb. ekler; oradaki gerçek bir curl/osascript
# çağrılmasın diye işlev olarak da sabitlenir (işlevler PATH'ten önce gelir).
curl() { "$SAHTE_BIN/curl" "$@"; }
osascript() { "$SAHTE_BIN/osascript" "$@"; }
sesver_baslat
"""


def _write_exec(path, text):
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)


@unittest.skipUnless(os.path.exists(BASH), "bash yok")
class MacosOrtakTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.proj = self.tmp / "proje"
        self.proj.mkdir()
        shutil.copy(ROOT / "macos_ortak.sh", self.proj / "macos_ortak.sh")
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        _write_exec(bin_dir / "osascript", FAKE_OSASCRIPT)
        _write_exec(bin_dir / "curl", FAKE_CURL)
        self.harness = self.tmp / "kosu.sh"
        _write_exec(self.harness, HARNESS)
        self.dialog_log = self.tmp / "pencereler.txt"
        self.curl_log = self.tmp / "curl.txt"
        self.env = {
            "PATH": f"{bin_dir}:/usr/bin:/bin:/usr/sbin:/sbin",
            "SAHTE_BIN": str(bin_dir),
            "HOME": str(self.tmp),
            "SAHTE_PENCERE_LOG": str(self.dialog_log),
            "SAHTE_CURL_LOG": str(self.curl_log),
        }

    def run_launcher(self, mode, arch, translated="0", lang="en-US", **extra):
        env = dict(self.env, SAHTE_UNAME_M=arch, SAHTE_TRANSLATED=translated, **extra)
        if lang is not None:
            env["SESVER_SISTEM_DILI"] = lang
        proc = subprocess.run([BASH, str(self.harness), str(self.proj), mode], env=env,
                              stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
        return proc

    def dialogs(self, wait_for=None):
        # "İlk kez kuruluyor" penceresi arka planda açılır; kısa bir süre beklenir.
        deadline = time.monotonic() + 5
        while True:
            text = self.dialog_log.read_text(encoding="utf-8") if self.dialog_log.exists() else ""
            if wait_for is None or wait_for in text or time.monotonic() > deadline:
                return text
            time.sleep(0.05)

    def curl_calls(self):
        return self.curl_log.read_text(encoding="utf-8") if self.curl_log.exists() else ""

    def launcher_log(self):
        path = self.proj / "sesver_baslatici_log.txt"
        return path.read_text(encoding="utf-8") if path.exists() else ""

    # --- Intel Mac --------------------------------------------------------
    def test_intel_mac_warns_and_exits_without_download_en(self):
        proc = self.run_launcher("app", "x86_64", "0", "en-US")
        self.assertEqual(proc.returncode, 1)
        text = self.dialogs()
        self.assertIn("SesVer requires Apple Silicon (M1 or later); this Mac has an Intel processor. "
                      "Because PyTorch no longer publishes packages for Intel Macs, SesVer cannot be "
                      "installed on this computer.", text)
        self.assertIn('buttons {"OK"}', text)
        self.assertNotIn("first time", text)
        self.assertEqual(self.curl_calls(), "", "Intel Mac'te hiçbir şey indirilmemeli")
        self.assertFalse((self.proj / "python-embed").exists())
        self.assertFalse((self.proj / "python-embed.indiriliyor").exists())
        self.assertIn("[HATA] Intel işlemcili Mac", self.launcher_log())

    def test_intel_mac_warning_tr_and_console_mode(self):
        proc = self.run_launcher("konsol", "x86_64", "", "tr-TR")
        self.assertEqual(proc.returncode, 1)
        text = self.dialogs()
        self.assertIn("SesVer Apple Silicon (M1 ve sonrası) gerektirir; bu Mac'te Intel işlemci var. "
                      "PyTorch artık Intel Mac için paket yayınlamadığı için SesVer bu bilgisayarda "
                      "kurulamaz.", text)
        self.assertIn('buttons {"Tamam"}', text)
        self.assertEqual(self.curl_calls(), "")
        self.assertIn("[HATA] Intel işlemcili Mac", proc.stdout)

    def test_rosetta_on_apple_silicon_is_not_blocked_and_uses_arm64(self):
        proc = self.run_launcher("app", "x86_64", "1", "en-US")
        self.assertEqual(proc.returncode, 1)  # sahte curl indirmeyi başarısız kılar
        self.assertNotIn("Apple Silicon", self.dialogs())
        self.assertIn("aarch64-apple-darwin", self.curl_calls())
        self.assertNotIn("x86_64-apple-darwin", self.curl_calls())

    def test_linux_x86_64_is_not_treated_as_intel_mac(self):
        proc = self.run_launcher("konsol", "x86_64", "", "en-US", SAHTE_UNAME_S="Linux")
        self.assertEqual(proc.returncode, 1)  # Python bulunamadı (sahte ortam)
        self.assertNotIn("Apple Silicon", self.dialogs())
        self.assertIn("Gömülü Python yalnız macOS için hazır", proc.stdout)

    def test_intel_mac_with_finished_install_keeps_running(self):
        venv_bin = self.proj / ".venv" / "bin"
        venv_bin.mkdir(parents=True)
        _write_exec(venv_bin / "python", '#!/bin/bash\necho "sahte python $*"\nexit 0\n')
        (self.proj / ".venv" / "sesver_kurulum_tamam.txt").write_text("tamam\n", encoding="utf-8")
        proc = self.run_launcher("app", "x86_64", "0", "en-US")
        self.assertEqual(proc.returncode, 0)
        self.assertNotIn("Apple Silicon", self.dialogs())
        self.assertIn("sahte python desktop.py", self.launcher_log())

    # --- arm64: normal akış + İngilizce pencereler -------------------------
    def test_arm64_normal_flow_dialogs_in_english(self):
        proc = self.run_launcher("app", "arm64", "0", "en-US")
        self.assertEqual(proc.returncode, 1)  # sahte curl + Python yok → beklenen hata
        self.assertIn("aarch64-apple-darwin", self.curl_calls())
        text = self.dialogs(wait_for="first time")
        self.assertIn("SesVer is being set up for the first time (downloading Python and packages, only once).",
                      text)
        self.assertIn("Progress: ", text)
        self.assertIn("Python was not found and SesVer's own Python could not be downloaded.", text)
        self.assertIn("Details: ", text)
        self.assertNotIn("Tamam", text)
        self.assertNotIn("kuruluyor", text)
        self.assertNotIn("Apple Silicon", text)

    def test_arm64_dialogs_in_turkish(self):
        proc = self.run_launcher("app", "arm64", "0", "tr-TR")
        self.assertEqual(proc.returncode, 1)
        text = self.dialogs(wait_for="ilk kez kuruluyor")
        self.assertIn("SesVer ilk kez kuruluyor", text)
        self.assertIn("Python bulunamadı ve uygulamaya özel Python indirilemedi.", text)
        self.assertIn("Ayrıntı: ", text)
        self.assertIn('buttons {"Tamam"}', text)
        self.assertNotIn('buttons {"OK"}', text)

    def test_window_language_from_apple_languages(self):
        # SESVER_SISTEM_DILI yok: AppleLanguages'ın ilk öğesi belirler.
        cases = {'(\\n    "tr-TR",\\n    "en-US"\\n)\\n': "Tamam",
                 '(\\n    "en-GB",\\n    "tr-TR"\\n)\\n': "OK",
                 '(\\n    "de-DE"\\n)\\n': "OK",
                 '(\\n    tr\\n)\\n': "Tamam"}
        for langs, button in cases.items():
            with self.subTest(langs=langs):
                if self.dialog_log.exists():
                    self.dialog_log.unlink()
                self.run_launcher("app", "x86_64", "0", None, SAHTE_APPLE_LANGS=langs)
                self.assertIn(f'buttons {{"{button}"}}', self.dialogs())


@unittest.skipUnless(os.path.exists(BASH), "bash yok")
class SesverAppScriptTests(unittest.TestCase):
    """SesVer.app/Contents/Resources/sesver_app.sh: macos_ortak.sh'tan önceki pencereler."""

    def run_app(self, lang, dmg_home=None):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        res = base / "klasor" / "SesVer.app" / "Contents" / "Resources"
        res.mkdir(parents=True)
        shutil.copy(ROOT / "SesVer.app" / "Contents" / "Resources" / "sesver_app.sh", res / "sesver_app.sh")
        bin_dir = base / "bin"
        bin_dir.mkdir()
        _write_exec(bin_dir / "osascript", FAKE_OSASCRIPT)
        log = base / "pencereler.txt"
        env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(base), "SAHTE_PENCERE_LOG": str(log),
               "SESVER_SISTEM_DILI": lang}
        if dmg_home is not None:
            (res / "payload").mkdir()
            (res / "payload" / ".sesver_payload_version").write_text("1.2.0\n", encoding="utf-8")
            blocker = base / "dosya"
            blocker.write_text("klasör değil\n", encoding="utf-8")
            env["SESVER_HOME"] = str(blocker / dmg_home)
        proc = subprocess.run([BASH, str(res / "sesver_app.sh")], env=env, stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, timeout=30)
        return proc.returncode, log.read_text(encoding="utf-8") if log.exists() else ""

    def test_zip_mode_outside_project_folder_en_and_tr(self):
        code, text = self.run_app("en-US")
        self.assertEqual(code, 1)
        self.assertIn("SesVer.app must stay inside the SesVer project folder", text)
        self.assertIn('buttons {"OK"}', text)
        code, text = self.run_app("tr-TR")
        self.assertEqual(code, 1)
        self.assertIn("SesVer.app, SesVer proje klasörünün içinde durmalı", text)
        self.assertIn('buttons {"Tamam"}', text)

    def test_dmg_mode_working_folder_error_en(self):
        code, text = self.run_app("en", dmg_home="SesVer")
        self.assertEqual(code, 1)
        self.assertIn("SesVer could not create its working folder:", text)


@unittest.skipUnless(sys.platform == "darwin" and shutil.which("clang"), "yalnız macOS + clang")
class LauncherBinaryTests(unittest.TestCase):
    """macos/sesver_app_launcher.c: sahte osascript yoluyla derlenip pencere metni okunur."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        base = Path(cls._tmp.name)
        cls.log = base / "pencereler.txt"
        fake = base / "osascript"
        _write_exec(fake, FAKE_OSASCRIPT)
        macos_dir = base / "SesVer.app" / "Contents" / "MacOS"
        macos_dir.mkdir(parents=True)
        cls.exe = macos_dir / "SesVer"  # Resources/sesver_app.sh YOK → "betik açılamadı" penceresi
        subprocess.run(["clang", "-Os", "-Wall", "-Wextra", "-Werror", "-framework", "CoreFoundation",
                        f'-DSESVER_OSASCRIPT="{fake}"', "-o", str(cls.exe),
                        str(ROOT / "macos" / "sesver_app_launcher.c")], check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def run_exe(self, lang):
        if self.log.exists():
            self.log.unlink()
        env = {"PATH": "/usr/bin:/bin", "SAHTE_PENCERE_LOG": str(self.log)}
        if lang is not None:
            env["SESVER_SISTEM_DILI"] = lang
        proc = subprocess.run([str(self.exe)], env=env, capture_output=True, text=True, timeout=30)
        return proc.returncode, self.log.read_text(encoding="utf-8")

    def test_dialog_language(self):
        code, text = self.run_exe("en-US")
        self.assertEqual(code, 1)
        self.assertIn("The SesVer launcher script could not be opened (No such file or directory).", text)
        self.assertIn("Location: ", text)
        self.assertIn('buttons {"OK"}', text)
        code, text = self.run_exe("tr-TR")
        self.assertEqual(code, 1)
        self.assertIn("SesVer başlatıcı betiği açılamadı", text)
        self.assertIn('buttons {"Tamam"}', text)

    def test_dialog_language_from_system_preferences(self):
        # SESVER_SISTEM_DILI yok: CFLocaleCopyPreferredLanguages (AppleLanguages) belirler.
        out = subprocess.run(["/usr/bin/defaults", "read", "-g", "AppleLanguages"],
                             capture_output=True, text=True).stdout
        first = next((x.strip().strip('"') for x in out.strip().strip("()").replace(",", "\n").splitlines()
                      if x.strip()), "")
        _, text = self.run_exe(None)
        self.assertIn('buttons {"Tamam"}' if first.lower().startswith("tr") else 'buttons {"OK"}', text)


if __name__ == "__main__":
    unittest.main()
