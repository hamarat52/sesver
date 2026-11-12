"""CI iş akışı (.github/workflows/windows-installer.yml) statik denetimleri.

Bulgu 5: her ``uses:`` 40 karakterlik commit SHA'sına sabit ve yanında sürüm yorumu var;
yazma yetkisi (contents: write) yalnız release job'unda ve o job kod checkout etmez.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "windows-installer.yml"

PINNED = re.compile(r"^\s*(?:-\s+)?uses:\s+([A-Za-z0-9_.-]+/[A-Za-z0-9_./-]+)@([0-9a-f]{40})\s+#\s+v\d+(?:\.\d+){1,2}\s*$")


def _workflow():
    import yaml  # PyYAML (huggingface-hub/transformers bağımlılığı olarak ortamda)
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


class PinnedActionsTests(unittest.TestCase):
    def test_every_uses_line_is_pinned_to_commit_sha_with_version_comment(self):
        lines = [ln for ln in WORKFLOW.read_text(encoding="utf-8").splitlines()
                 if re.match(r"^\s*(?:-\s+)?uses:", ln)]
        self.assertGreaterEqual(len(lines), 5)
        for ln in lines:
            self.assertRegex(ln, PINNED, ln.strip())

    def test_yaml_is_valid_and_parsed_steps_match(self):
        data = _workflow()
        self.assertIsInstance(data, dict)
        uses = [step["uses"] for job in data["jobs"].values() for step in job.get("steps", []) if "uses" in step]
        text_count = len(re.findall(r"(?m)^\s*(?:-\s+)?uses:", WORKFLOW.read_text(encoding="utf-8")))
        self.assertEqual(len(uses), text_count)
        for ref in uses:
            self.assertRegex(ref, r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")  # YAML yorumu değere girmez

    def test_build_checks_product_name_and_version_of_exe(self):
        """SignPath ön koşulu CI'da gerçek .exe üzerinde doğrulanır (bu Mac'te derlenemez).

        1.2.1 CI (koşu 42358133201): Inno değerleri boşluk yer tutucularının üstüne yazar
        ('SesVer' + 54 boşluk). Denetim gevşetilmez: değerler imzadan önce kaynakta kırpılır,
        sonra büyük/küçük harf duyarlı tam eşitlik aranır.
        """
        data = _workflow()
        step = next(s for s in data["jobs"]["build"]["steps"] if s.get("name") == "Kurulum programını derle")
        run = step["run"]
        self.assertNotIn("continue-on-error", step)
        self.assertIn('& $env:ISCC "/DAppVersion=$env:APP_VERSION" "windows\\SesVer.iss"', run)
        sira = [run.index(p) for p in (
            '& $env:ISCC',
            "& $py.Source tools\\pe_surum_bilgisi.py --kirp $exe",
            'if ($LASTEXITCODE -ne 0) { throw "Sürüm bilgisi kırpılamadı',
            "$vi = [System.Diagnostics.FileVersionInfo]::GetVersionInfo($f.FullName)",
            "if ($v -cne $beklenen[$k]) { throw",
            "Write-Host \"Dosya özellikleri BAŞARILI:",
            "Get-FileHash -Algorithm SHA256 $exe",
            '"INSTALLER=$($f.FullName)"',
        )]
        self.assertEqual(sira, sorted(sira), "kırpma → denetim → BAŞARILI → SHA256 → INSTALLER sırası")
        for parca in ("ProductName    = 'SesVer'", "ProductVersion = $env:APP_VERSION",
                      "FileVersion    = $env:APP_VERSION", "CompanyName    = 'HamaratLabs'",
                      "LegalCopyright = 'Muhammed Yusuf Hamarat - Founder of HamaratLabs'",
                      "if ($f.Length -ne $boy) { throw", "$_.Source -notlike '*\\WindowsApps\\*'"):
            self.assertIn(parca, run)
        self.assertNotIn(".Trim()) -ne", run)  # boşluk okurken yutulmaz, kaynakta giderilir
        # Beklenen telif metni .iss'tekiyle aynı.
        iss = (ROOT / "windows" / "SesVer.iss").read_text(encoding="utf-8")
        self.assertIn("VersionInfoCopyright=Muhammed Yusuf Hamarat - Founder of HamaratLabs\n", iss)

    def test_error_path_step_proves_masked_log_and_update_option(self):
        """Siberguvenlik 1.2.1 şartı: hata yolu CI'da koşulur; tutmazsa build job'u (ve release) düşer."""
        data = _workflow()
        steps = data["jobs"]["build"]["steps"]
        names = [s.get("name", "") for s in steps]
        idx = next(i for i, n in enumerate(names) if n.startswith("Hata yolu testi"))
        self.assertGreater(idx, next(i for i, n in enumerate(names) if n.startswith("Duman testi")))
        self.assertLess(idx, names.index("Release dosyalarını hazırla (iki asset + SHA256 + notlar)"))
        step = steps[idx]
        self.assertNotIn("continue-on-error", step)
        self.assertNotIn("if", step)
        run = step["run"]
        for parca in ("$ErrorActionPreference = 'Stop'",
                      "'/ORTAMKUR','/GUNCELLEMEDENETIMI=0'",
                      "if ($p.ExitCode -ne 30)",
                      "if (-not (Test-Path $paylas)) { throw 'kurulum_log_paylas.txt oluşmadı' }",
                      "if ($hamMetin.IndexOf($ev, [StringComparison]::OrdinalIgnoreCase) -lt 0) { throw",
                      "foreach ($iz in @($ev, $ev.Replace('\\', '/'), $kisa, \"\\Users\\$env:USERNAME\", $env:USERNAME))",
                      "if ($a.guncelleme_kontrolu -isnot [bool] -or $a.guncelleme_kontrolu) { throw",
                      "if ((Get-FileHash $ayar).Hash -ne $once) { throw",
                      "'/GUNCELLEMEDENETIMI=1'"):
            self.assertIn(parca, run)
        # PM'in CI günlüğünde arayacağı satır (birebir).
        self.assertIn("Write-Host 'Hata yolu testi BAŞARILI: ilk kurulum hatası (çıkış kodu 30) kurulum_log_paylas.txt "
                      "üretti, ev klasörü yolu ve kullanıcı adı içermiyor; /GUNCELLEMEDENETIMI=0 ayarlar.json "
                      "guncelleme_kontrolu=false yazdı, diğer ayar korundu, parametresiz yeniden kurulum seçimi ezmedi.'",
                      run)
        self.assertEqual(run.count("BAŞARILI"), 1)
        self.assertTrue(run.rstrip().endswith("seçimi ezmedi.'"))  # BAŞARILI yalnız tüm denetimlerden sonra
        self.assertEqual(data["jobs"]["release"]["needs"], "build")

    def test_write_token_only_in_release_job_without_checkout(self):
        data = _workflow()
        self.assertEqual(data["permissions"], {"contents": "read"})
        writers = [name for name, job in data["jobs"].items()
                   if (job.get("permissions") or {}).get("contents") == "write"]
        self.assertEqual(writers, ["release"])
        release_uses = [s.get("uses", "") for s in data["jobs"]["release"]["steps"]]
        self.assertFalse([u for u in release_uses if u.startswith("actions/checkout@")])

    def test_uninstall_keep_step_proves_keep_reinstall_and_default_delete(self):
        """1.4.1: "sakla" ile kaldırma, aynı yere yeniden kurulum ve varsayılan (sessiz) silme her push'ta
        build job'unda koşulur; bir denetim tutmazsa job (ve release) düşer."""
        data = _workflow()
        steps = data["jobs"]["build"]["steps"]
        names = [s.get("name", "") for s in steps]
        idx = next(i for i, n in enumerate(names) if n.startswith("Kaldırma testi"))
        self.assertGreater(idx, next(i for i, n in enumerate(names) if n.startswith("Duman testi")))
        self.assertLess(idx, names.index("Release dosyalarını hazırla (iki asset + SHA256 + notlar)"))
        step = steps[idx]
        self.assertNotIn("continue-on-error", step)
        self.assertNotIn("if", step)
        run = step["run"]
        for parca in ("$ErrorActionPreference = 'Stop'",
                      "Kaldir 'sakla' @('/BILESENLERISAKLA')",
                      "'Kaldirma: indirilen bilesenler saklandi'",
                      "if (Compare-Object $once $sonra) {",
                      "Kur 'sakla-2'",
                      "Kaldir 'varsayilan' @()",
                      "'Kaldirma: indirilen bilesenler siliniyor'",
                      "if (Test-Path $pe) { throw 'Varsayılan sessiz kaldırmada python-embed silinmedi' }",
                      "'voices\\seslerim\\kisisel.txt','outputs\\uretim.wav'"):
            self.assertIn(parca, run)
        self.assertEqual(run.count("BAŞARILI"), 1)
        self.assertTrue(run.rstrip().endswith("kullanıcı verisi her durumda korundu.'"))
        # Duman testindeki varsayılan kaldırma python-embed'in (artık son adımda) silinmesini bekler.
        duman = next(s for s in steps if s.get("name", "").startswith("Duman testi"))["run"]
        self.assertIn("(Test-Path (Join-Path $app 'python-embed'))); $i++) { Start-Sleep -Seconds 1 }", duman)

    def test_full_launch_measures_that_packages_are_not_downloaded_again(self):
        """Gerçek ortamla (torch dahil): üstüne yeniden kurulum ve "sakla" ile kaldırıp yeniden kurulum
        sırasında indirme yok (günlük + dosya + ağ baytı); başarısızlık job'u kırmızı yapar."""
        data = _workflow()
        run = data["jobs"]["full-launch"]["steps"][-2]["run"]
        for parca in ("function Test-TekrarIndirmeYok(",
                      "'^\\s*(Downloading|Collecting|Installing collected) |Indiriliyor: cpython|Ilk kurulum yapiliyor|esitleniyor'",
                      "if ($mb -gt 500) { throw",
                      "if ($sonra.TorchZaman -ne $once.TorchZaman) { throw",
                      "if ($sonra.Isaret -ne $once.Isaret) { throw",
                      "Test-TekrarIndirmeYok 'yeniden' $o3 $rx3 $bas3",
                      "'/BILESENLERISAKLA', \"/LOG=$kl\"",
                      "Test-TekrarIndirmeYok 'sakla-yeniden' $o5 $rx5 $bas5",
                      "$u5 = Test-Acilis 'sakla sonrası açılış'",
                      "throw 'Varsayılan sessiz kaldırmada python-embed silinmedi'"):
            self.assertIn(parca, run)
        # Ölçüm, ölçülen kurulumdan SONRA yapılır.
        self.assertLess(run.index("$g2 = Kur-OrtamKur 'yeniden' 15"), run.index("Test-TekrarIndirmeYok 'yeniden'"))
        self.assertLess(run.index("$g5 = Kur-OrtamKur 'sakla-yeniden' 15"),
                        run.index("Test-TekrarIndirmeYok 'sakla-yeniden'"))
        self.assertNotIn("continue-on-error", data["jobs"]["full-launch"]["steps"][-2])


if __name__ == "__main__":
    unittest.main()
