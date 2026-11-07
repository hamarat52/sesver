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


def _iss_mesajlari(dil):
    iss = (ROOT / "windows" / "SesVer.iss").read_text(encoding="utf-8-sig")
    return dict(re.findall(rf"^{dil}\.([A-Za-z0-9]+)=(.*)$", iss, re.M))


# README gizlilik tablosundaki her satırın ("When" sütunundaki ayırt edici parça) kurulumdaki
# özette (Türkçe, İngilizce) karşılığı. README'ye yeni satır eklenip burada karşılığı yoksa test
# kırmızı olur: kurulum metni politikadan geri kalmaz (siberguvenlik 1.2.1 bulgu F).
OZET_KARSILIKLARI = (
    ("Every start", ("GuncellemeAciklama", "her açılışta GitHub"), ("GuncellemeAciklama", "at every start whether")),
    ("First-time setup (Windows installer page", ("GizlilikOzeti", "kurulum"), ("GizlilikOzeti", "setup")),
    ("after an update that changes `requirements.txt`",
     ("GizlilikOzeti", "paketleri değiştiren güncellemeler"), ("GizlilikOzeti", "updates that change its packages")),
    ("once more at start if the installed PyTorch cannot use the card",
     ("GizlilikOzeti", "NVIDIA kartta PyTorch, gerekirse açılışta da"),
     ("GizlilikOzeti", "PyTorch on NVIDIA cards, at startup too if needed")),
    ("First **Generate**", ("GizlilikOzeti", "ilk üretimde indirme"), ("GizlilikOzeti", "downloaded on the first generation")),
    ("check on the first generation of each session",
     ("GizlilikOzeti", "sonraki oturumların ilk üretiminde kısa güncellik denetimi"),
     ("GizlilikOzeti", "a short freshness check on the first generation of later sessions")),
    ("First use of **Otomatik yazıya dök**", ("GizlilikOzeti", "yazıya dökme modeli"),
     ("GizlilikOzeti", "the transcription model")),
    ("Only when you click **Hızlı Mod'u indir**", ("GizlilikOzeti", "sizin başlattığınız indirmeler"),
     ("GizlilikOzeti", "downloads you start yourself")),
    ("Only when you click **Hızlandırmayı etkinleştir**", ("GizlilikOzeti", "sizin başlattığınız indirmeler"),
     ("GizlilikOzeti", "downloads you start yourself")),
    ("Only when you click **Hata raporu gönder**", ("GizlilikOzeti", "Hata raporu otomatik gönderilmez"),
     ("GizlilikOzeti", "Error reports are never sent automatically")),
)


class InstallerSummaryTests(unittest.TestCase):
    """Kurulumdaki kısa gizlilik özeti README Privacy policy tablosuyla çelişmez (SignPath ikisini okur)."""

    def test_every_policy_row_has_a_counterpart_in_both_installer_languages(self):
        policy = _section("Privacy policy")
        table = policy.split("| When |")[1].split("\n\n")[0]
        rows = [r.split("|")[1] for r in table.splitlines()[2:] if r.startswith("|")]
        self.assertGreaterEqual(len(rows), 9)
        tr, en = _iss_mesajlari("turkish"), _iss_mesajlari("english")
        for row in rows:
            with self.subTest(row=row.strip()):
                eslesen = [k for k in OZET_KARSILIKLARI if k[0] in row]
                self.assertTrue(eslesen, "README satırının kurulum özetinde karşılığı tanımlı değil")
                for _parca, (tr_anahtar, tr_metin), (en_anahtar, en_metin) in eslesen:
                    self.assertIn(tr_metin, tr[tr_anahtar])
                    self.assertIn(en_metin, en[en_anahtar])
        for parca, _tr, _en in OZET_KARSILIKLARI:  # karşılık tablosunda README'den kalkmış satır yok
            self.assertTrue(any(parca in r for r in rows), parca)

    def test_only_is_qualified_and_page_stays_short(self):
        tr, en = _iss_mesajlari("turkish"), _iss_mesajlari("english")
        # "yalnız/only" listesi güncelleme denetimini dışarıda bıraktığını açıkça söyler.
        self.assertIn("Aşağıdaki güncelleme denetimi dışında internete yalnız şunlar için bağlanır:", tr["GizlilikOzeti"])
        self.assertIn("Apart from the update check below, it connects to the internet only for:", en["GizlilikOzeti"])
        for d in (tr, en):
            self.assertLessEqual(len(d["GizlilikOzeti"]), 560)  # tam liste README'de; sayfa kısa kalır
            self.assertIn("#privacy-policy", d["GizlilikBaglantisi"])

    def test_the_three_connections_exist_in_code(self):
        """F'de adı geçen üç bağlantının koddaki karşılığı (README tablosunda satırları var)."""
        policy = _section("Privacy policy")
        # 1) Her oturumun ilk üretiminde Hugging Face güncellik denetimi: model tembel yüklenir ve
        #    from_pretrained local_files_only vermez (voxcpm 2.0.3 snapshot_download'a gider).
        app = (ROOT / "app.py").read_text(encoding="utf-8")
        yukle = app.split("_model = VoxCPM.from_pretrained(")[1].split(")")[0]
        self.assertIn("hf_model_id=MODEL_ID", yukle)
        self.assertNotIn("local_files_only", yukle)
        self.assertIn('a short "is the cached model current?" check on the first generation of each session', policy)
        # 2) requirements.txt değişen güncellemeden sonra pip (Windows ve macOS başlatıcıları).
        bat = (ROOT / "WINDOWS_BASLAT.bat").read_text(encoding="utf-8")
        self.assertIn('if not "%SV_ISARET%"=="%SV_BEKLENEN%" goto :esitle', bat)
        self.assertIn('"%PYEXE%" -m pip install -r requirements.txt %SV_KISIT%', bat)
        mac = (ROOT / "macos_ortak.sh").read_text(encoding="utf-8")
        self.assertIn("req_sha256=", mac)
        self.assertIn("after an update that changes `requirements.txt`", policy)
        # 3) NVIDIA kartta PyTorch kartı kullanamazsa açılışta download.pytorch.org.
        duzelt = bat.split('call :durum 6 "Ekran karti dogrulaniyor"')[1].split("\n:gpu_fix_isaretle\n")[0]
        self.assertIn("hizlandirma.py --cuda-dogrula", duzelt)
        self.assertIn("--index-url https://download.pytorch.org/whl/%CUDA_ETIKET%", duzelt)
        self.assertIn("once more at start if the installed PyTorch cannot use the card | `download.pytorch.org`", policy)


if __name__ == "__main__":
    unittest.main()
