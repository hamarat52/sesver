"""Her kilit varyantının kendi hedef platformunda çözüldüğünü ve özetlerin indeksle tuttuğunu sınar.

pip install --dry-run --require-hashes --only-binary=:all: --platform/--python-version ile
(tekerlek indirilmez; PEP 658 üst verisi ve indeksin bildirdiği SHA-256 kullanılır).
proxy-tools yalnız kaynak paketi olduğundan çapraz platform denetiminden çıkarılır; onun
özeti PyPI JSON'daki sha256 ile ayrıca karşılaştırılır. Son olarak bir özet bilerek bozulur:
pip'in bu kipte de reddettiği gösterilir (kontrol deneyi).

Kullanım (geliştirici, ağ gerekir; pip 26+):  python tools/kilit_dogrula.py
"""
import json
import re
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
KILIT = KOK / "kilit"
PLATFORM = {"macos-arm64": "macosx_14_0_arm64", "windows-x64": "win_amd64"}
PYTHONLAR = ("3.10", "3.11", "3.12")
TORCH_KATMANLARI = {"pypi": ("macos-arm64", "windows-x64"), "cu126": ("windows-x64",),
                    "cu128": ("windows-x64",), "cu130": ("windows-x64",)}


def blok_cikar(metin, ad):
    cikti, atla = [], False
    for satir in metin.splitlines(keepends=True):
        if satir[:1] not in (" ", "\t", "#", "-", "\n") and satir.strip():
            atla = satir.lower().startswith(ad + "==")
        elif satir[:1] not in (" ", "\t"):
            atla = False
        if not atla:
            cikti.append(satir)
    return "".join(cikti)


def kuru_kurulum(dosya, platform, py, no_deps):
    with tempfile.TemporaryDirectory() as hedef:
        komut = [sys.executable, "-m", "pip", "install", "--dry-run", "--ignore-installed", "--quiet",
                 "--disable-pip-version-check", "--no-cache-dir", "--require-hashes", "--only-binary=:all:",
                 "--platform", platform, "--python-version", py, "--implementation", "cp",
                 "--target", hedef, "--report", str(Path(hedef) / "rapor.json"), "-r", str(dosya)]
        if no_deps:
            komut.append("--no-deps")
        r = subprocess.run(komut, capture_output=True, text=True)
        rapor = Path(hedef) / "rapor.json"
        paketler = []
        if r.returncode == 0 and rapor.exists():
            veri = json.loads(rapor.read_text(encoding="utf-8"))
            paketler = [(p["metadata"]["name"], p["metadata"]["version"],
                         (p["download_info"].get("archive_info") or {}).get("hashes", {}).get("sha256", ""))
                        for p in veri["install"]]
        return r.returncode, paketler, (r.stdout + r.stderr).strip()


def main():
    tmp = Path(tempfile.mkdtemp())
    print(f"pip: {subprocess.run([sys.executable, '-m', 'pip', '--version'], capture_output=True, text=True).stdout.strip()}")
    hata = 0
    for ad, platform in PLATFORM.items():
        for py in PYTHONLAR:
            dosya = KILIT / f"{ad}-py{py.replace('.', '')}.txt"
            suzulmus = tmp / dosya.name
            suzulmus.write_text(blok_cikar(dosya.read_text(encoding="utf-8"), "proxy-tools"), encoding="utf-8")
            # --no-deps: proxy-tools (yalnız kaynak paketi) çapraz platformda denetlenemediği için
            # bağımlılık çözümü burada yapılmaz; kapalılık uv pip compile ve gerçek kurulumla sınanır.
            kod, paketler, cikti = kuru_kurulum(suzulmus, platform, py, no_deps=True)
            ozetli = sum(1 for _, _, h in paketler if h)
            print(f"[{'OK' if kod == 0 else 'HATA'}] {dosya.name:28} {platform:18} cp{py}: "
                  f"{len(paketler)} paket çözüldü, {ozetli} tanesinin indeks özeti kilitte")
            if kod != 0:
                hata = 1
                print("   ", cikti[-600:])
    for katman, hedefler in TORCH_KATMANLARI.items():
        dosya = KILIT / f"torch-{katman}.txt"
        for ad in hedefler:
            for py in PYTHONLAR:
                kod, paketler, cikti = kuru_kurulum(dosya, PLATFORM[ad], py, no_deps=True)
                print(f"[{'OK' if kod == 0 else 'HATA'}] {dosya.name:28} {PLATFORM[ad]:18} cp{py}: "
                      + ", ".join(f"{n}=={v}" for n, v, _ in paketler))
                if kod != 0:
                    hata = 1
                    print("   ", cikti[-600:])
    for dosya in ("pip.txt", "voxcpm.txt"):
        for ad, platform in PLATFORM.items():
            kod, paketler, cikti = kuru_kurulum(KILIT / dosya, platform, "3.11", no_deps=True)
            print(f"[{'OK' if kod == 0 else 'HATA'}] {dosya:28} {platform:18} cp3.11: "
                  + ", ".join(f"{n}=={v}" for n, v, _ in paketler))
            hata |= kod != 0
    # proxy-tools: tek kaynak paketi; kilitteki özet PyPI'nin bildirdiğiyle aynı mı?
    with urllib.request.urlopen("https://pypi.org/pypi/proxy-tools/0.1.0/json", timeout=30) as r:
        pypi = {f["digests"]["sha256"] for f in json.load(r)["urls"]}
    for dosya in sorted(KILIT.glob("*-py3*.txt")):
        blok = re.search(r"^proxy-tools==0\.1\.0((?:\s*\\\n\s*--hash=sha256:[0-9a-f]{64})+)", dosya.read_text(), re.M)
        kilit = set(re.findall(r"[0-9a-f]{64}", blok.group(1))) if blok else set()
        tamam = bool(kilit) and kilit <= pypi
        hata |= not tamam
        print(f"[{'OK' if tamam else 'HATA'}] {dosya.name:28} proxy-tools 0.1.0 özeti PyPI ile aynı")
    # Kontrol deneyi: bir özet bozulunca pip reddetmeli.
    bozuk = tmp / "bozuk.txt"
    metin = (KILIT / "torch-cu130.txt").read_text(encoding="utf-8")
    bozuk.write_text(re.sub(r"(--hash=sha256:)[0-9a-f]{64}", r"\g<1>" + "0" * 64, metin), encoding="utf-8")
    kod, _, cikti = kuru_kurulum(bozuk, "win_amd64", "3.11", no_deps=True)
    reddetti = kod != 0 and ("HASHES" in cikti.upper() or "hash" in cikti)
    print(f"[{'OK' if reddetti else 'HATA'}] kontrol: tüm özetleri bozulmuş torch-cu130 reddedildi -> "
          + (cikti.splitlines()[0][:160] if cikti else ""))
    hata |= not reddetti
    print("SONUÇ:", "HEPSİ GEÇTİ" if not hata else "HATA VAR")
    return 1 if hata else 0


if __name__ == "__main__":
    sys.exit(main())
