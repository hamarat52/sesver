"""SignPath Foundation ön koşulları: README'deki "Code signing policy" ve "Privacy policy".

Kaynak: https://signpath.org/terms ("Conditions for the website / repository", 2026-11-03 ve
2026-11-07'de okundu). Gizlilik politikasındaki sunucu listesi koddaki gerçek dış bağlantılarla
karşılaştırılır: çalışma zamanı kodunda README'de yazmayan bir sunucuya bağlantı eklenirse ya
da README koddan kalkmış bir bağlantıyı sayarsa test kırmızı olur.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = (ROOT / "README.md").read_text(encoding="utf-8")

SIGNPATH_SENTENCE = ("Free code signing provided by [SignPath.io](https://about.signpath.io), "
                     "certificate by [SignPath Foundation](https://signpath.org)")

# SesVer'in kendisinin (ya da başlatıcının) bağlandığı sunucuları içerebilen dosyalar.
RUNTIME_FILES = ("app.py", "desktop.py", "guncelleme.py", "hizlandirma.py", "hata_raporu.py", "audio_prep.py",
                 "voice_designer.py", "voice_library.py", "i18n.py", "engines/ema.py", "WINDOWS_BASLAT.bat",
                 "macos_ortak.sh", "windows/SesVer.iss")
# Kodda geçen ama SesVer'in bağlanmadığı adresler: kullanıcıya gösterilen metin, yorum, SVG ad alanı.
NOT_CONNECTIONS = {"127.0.0.1", "www.python.org", "developer.microsoft.com", "docs.nvidia.com", "www.w3.org"}


def _section(title):
    m = re.search(rf"^## {re.escape(title)}\n(.*?)(?=^## |\Z)", README, re.M | re.S)
    assert m, f"README'de '## {title}' yok"
    return m.group(1)


def _code_hosts():
    hosts = {}
    for rel in RUNTIME_FILES:
        text = (ROOT / rel).read_text(encoding="utf-8-sig")
        for host in re.findall(r"https?://([A-Za-z0-9.-]+)", text):
            hosts.setdefault(host, set()).add(rel)
    return hosts


class CodeSigningPolicyTests(unittest.TestCase):
    def test_required_items(self):
        sec = _section("Code signing policy")
        self.assertIn(SIGNPATH_SENTENCE, sec)  # birebir zorunlu cümle
        self.assertIn("Committers and reviewers: [Muhammed Yusuf Hamarat](https://github.com/hamarat52)", sec)
        self.assertIn("Approvers: [Muhammed Yusuf Hamarat](https://github.com/hamarat52)", sec)
        self.assertIn("[Privacy policy](#privacy-policy)", sec)
        self.assertIn('**"SignPath Foundation"** as the publisher', sec)  # yayıncı adı dürüstçe
        self.assertIn("**not signed**", sec)  # kabul edilene kadar imzasız
        self.assertIn("[Code signing policy](#code-signing-policy)", README.split("## Code signing policy")[0])

    def test_unsigned_warnings_kept(self):
        self.assertIn("kurulum programı kod imzasız olduğu için bu uyarı çıkar", README)
        wf = (ROOT / ".github" / "workflows" / "windows-installer.yml").read_text(encoding="utf-8")
        self.assertIn("(kurulum programı kod imzasızdır)", wf)

    def test_release_notes_link_to_policy(self):
        wf = (ROOT / ".github" / "workflows" / "windows-installer.yml").read_text(encoding="utf-8")
        notes = wf.split("$notlar = @(")[1].split("\n          )\n")[0]
        self.assertIn("Code signing policy", notes)
        self.assertIn("https://github.com/$env:REPO#code-signing-policy", notes)

    def test_no_em_dash_in_new_sections(self):
        for title in ("Code signing policy", "Privacy policy"):
            self.assertNotIn("\u2014", _section(title))

    def test_application_stage_is_clear_before_the_required_sentence(self):
        # Siberguvenlik 1.2.1 bulgu E: zorunlu cümle birebir kalır, bağlamı ondan önce gelir.
        sec = _section("Code signing policy")
        bag = sec.index("_Application stage:_")
        self.assertLess(bag, sec.index(SIGNPATH_SENTENCE))
        self.assertIn("takes effect only after the application is accepted", sec[bag:sec.index(SIGNPATH_SENTENCE)])
        self.assertIn("not signed", sec[bag:sec.index(SIGNPATH_SENTENCE)])


class PrivacyPolicyTests(unittest.TestCase):
    def test_every_runtime_host_is_listed(self):
        policy = _section("Privacy policy")
        missing = {h: sorted(f) for h, f in _code_hosts().items()
                   if h not in NOT_CONNECTIONS and f"`{h}`" not in policy}
        self.assertEqual(missing, {})

    def test_every_listed_host_exists_in_code_or_is_a_download_mirror(self):
        policy = _section("Privacy policy")
        table = policy.split("| When |")[1].split("\n\n")[0]
        servers = " ".join(row.split("|")[2] for row in table.splitlines()[2:] if row.startswith("|"))
        listed = set(re.findall(r"`([a-z0-9-]+(?:\.[a-z0-9-]+)+)`", servers))
        self.assertGreaterEqual(len(listed), 6)
        code = _code_hosts()
        # files.pythonhosted.org: pip'in PyPI dosya sunucusu (kodda adres olarak geçmez, pip seçer).
        self.assertEqual(sorted(h for h in listed if h not in code and h != "files.pythonhosted.org"), [])

    def test_situations_and_controls_match_code(self):
        policy = _section("Privacy policy")
        guncelleme = (ROOT / "guncelleme.py").read_text(encoding="utf-8")
        self.assertIn('API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"', guncelleme)
        self.assertIn('ORTAM_DEGISKENI = "SESVER_GUNCELLEME_KONTROLU"', guncelleme)
        self.assertIn("SESVER_GUNCELLEME_KONTROLU=0", policy)
        self.assertIn("Açılışta güncellemeleri denetle", policy)
        app = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn('MODEL_ID = "openbmb/VoxCPM2"', app)
        self.assertIn("`openbmb/VoxCPM2`", policy)
        self.assertIn('WhisperModel("small"', app)
        self.assertIn('os.environ["GRADIO_ANALYTICS_ENABLED"] = "False"', app)
        self.assertIn('os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"', app)
        ema = (ROOT / "engines" / "ema.py").read_text(encoding="utf-8")
        self.assertIn('HF_REPO = "canberkkkkkk/ema-lightning"', ema)
        self.assertIn("`canberkkkkkk/ema-lightning`", policy)
        hr = (ROOT / "hata_raporu.py").read_text(encoding="utf-8")
        self.assertIn('DESTEK_EPOSTA = "hermes.agent.hamarat@gmail.com"', hr)
        self.assertIn("addressed to hermes.agent.hamarat@gmail.com", policy)
        self.assertNotIn("will not transfer any information", policy)  # kalıp cümle SesVer için yanlış olur
        for link in ("https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement",
                     "https://policies.python.org/pypi.org/Privacy-Notice/", "https://huggingface.co/privacy"):
            self.assertIn(link, policy)

    def test_download_cdns_and_installer_option_are_described(self):
        # Bulgu D: indirmeler sağlayıcıların CDN adreslerine yönlenir (2026-11-07 curl -I ile görüldü:
        # GitHub release → release-assets.githubusercontent.com, HF LFS → *.cdn.hf.co).
        policy = _section("Privacy policy")
        for parca in ("download CDNs", "`release-assets.githubusercontent.com`", "`*.cdn.hf.co`", "CloudFront"):
            self.assertIn(parca, policy)
        # Kurulumdaki gizlilik sayfası ve kapatma yolu (Yusuf'un kararı, SignPath koşulu).
        self.assertIn('"Gizlilik ve güncelleme denetimi" (Privacy and update check) page', policy)
        self.assertIn("`/GUNCELLEMEDENETIMI=0`", policy)
        iss = (ROOT / "windows" / "SesVer.iss").read_text(encoding="utf-8-sig")
        self.assertIn("turkish.GizlilikSayfaBaslik=Gizlilik ve güncelleme denetimi\n", iss)
        self.assertIn("english.GizlilikSayfaBaslik=Privacy and update check\n", iss)
        self.assertIn("{param:GUNCELLEMEDENETIMI|}", iss)


if __name__ == "__main__":
    unittest.main()
