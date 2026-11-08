"""kilit/ klasöründeki kurulum kilitlerini üretir (uv pip compile --generate-hashes).

Başlatıcılar (macos_ortak.sh, WINDOWS_BASLAT.bat) requirements.txt'yi doğrudan kurmaz;
her şey ``pip install --require-hashes`` ile bu kilitlerden kurulur. Kurulum sırası:

  1. kilit/pip.txt                 pip + setuptools (--no-deps). setuptools, tek kaynak
                                   paket proxy-tools'un --no-build-isolation ile hash'li
                                   ortamda derlenmesi için gerekir (izole derleme ortamı
                                   pip'te hash denetimsiz indirilir).
  2. kilit/torch-<katman>.txt      torch + torchaudio (--no-deps). pypi: macOS ve Windows
                                   CPU; cu126/cu128/cu130: Windows NVIDIA (download.pytorch.org).
  3. kilit/voxcpm.txt              voxcpm (--no-deps; ağır eğitim bağımlılıkları istenmez).
  4. kilit/<platform>-py3XX.txt    geri kalan her şey, torch/torchaudio HARİÇ.

Kullanım (geliştirici, ağ gerekir; uv kurulu olmalı):
    python tools/kilit_uret.py

Sürüm değiştirmek için requirements.txt ve aşağıdaki sabitler birlikte güncellenir.
Bu araç uygulamaya paketlenmez.
"""
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
KILIT = KOK / "kilit"
KOMUT = "python tools/kilit_uret.py"

PIP = "26.3"
SETUPTOOLS = "84.2.1"
VOXCPM = "2.0.3"
TORCH = "2.14.1"
TORCHAUDIO = "2.11.0"
# download.pytorch.org/whl/cu128'de Windows için en yeni torch 2.11.0 (2026-11-08).
TORCH_KATMANLARI = {
    "pypi": (None, TORCH, TORCHAUDIO),
    "cu126": ("https://download.pytorch.org/whl/cu126", TORCH, TORCHAUDIO),
    "cu128": ("https://download.pytorch.org/whl/cu128", "2.11.0", "2.11.0"),
    "cu130": ("https://download.pytorch.org/whl/cu130", TORCH, TORCHAUDIO),
}
PLATFORMLAR = {"macos-arm64": "aarch64-apple-darwin", "windows-x64": "x86_64-pc-windows-msvc"}
PYTHONLAR = ("3.10", "3.11", "3.12")
# torch 2.14.1 macOS tekerleği macosx_14_0_arm64: SesVer macOS 14 (Sonoma) ve sonrasını ister.
MAC_ORTAM = {"MACOSX_DEPLOYMENT_TARGET": "14.0"}
TORCH_PAKETLERI = ("torch", "torchaudio")


def uv(*args, ortam=None):
    komut = ["uv", "pip", "compile", "--quiet", "--generate-hashes",
             "--custom-compile-command", KOMUT, *args]
    print("+", " ".join(komut), flush=True)
    subprocess.run(komut, check=True, cwd=KOK, env=dict(os.environ, **(ortam or {})))


def bloklari_cikar(metin, adlar):
    """uv çıktısından adı verilen paketlerin bloklarını (satır + girintili devamı) çıkarır."""
    cikti, atla = [], False
    for satir in metin.splitlines(keepends=True):
        if satir[:1] not in (" ", "\t", "#", "\n", "-") and satir.strip():
            ad = re.split(r"[=<>!~ ;\\\[]", satir.strip(), maxsplit=1)[0].lower()
            atla = ad in adlar
        elif satir[:1] not in (" ", "\t"):
            atla = False
        if not atla:
            cikti.append(satir)
    return "".join(cikti)


def main():
    KILIT.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        girdi = tmp / "pip.in"
        girdi.write_text(f"pip=={PIP}\nsetuptools=={SETUPTOOLS}\n", encoding="utf-8")
        uv(str(girdi), "--no-deps", "--no-annotate", "--universal", "--python-version", "3.10",
           "-o", str(KILIT / "pip.txt"))
        girdi = tmp / "voxcpm.in"
        girdi.write_text(f"voxcpm=={VOXCPM}\n", encoding="utf-8")
        uv(str(girdi), "--no-deps", "--no-annotate", "--universal", "--python-version", "3.10",
           "-o", str(KILIT / "voxcpm.txt"))
        for katman, (indeks, torch_v, audio_v) in TORCH_KATMANLARI.items():
            yerel = "" if indeks is None else f"+{katman}"
            girdi = tmp / f"torch-{katman}.in"
            girdi.write_text(f"torch=={torch_v}{yerel}\ntorchaudio=={audio_v}{yerel}\n",
                             encoding="utf-8")
            ek = [] if indeks is None else ["--index-url", indeks, "--emit-index-url"]
            uv(str(girdi), "--no-deps", "--no-annotate", "--universal", "--python-version", "3.10", *ek,
               "-o", str(KILIT / f"torch-{katman}.txt"))
        kisit = KOK / "tools" / "kilit_kisit.txt"
        kisit.write_text(f"setuptools=={SETUPTOOLS}\n", encoding="utf-8", newline="\n")
        for ad, hedef in PLATFORMLAR.items():
            for py in PYTHONLAR:
                ara = tmp / f"{ad}-{py}.txt"
                uv("requirements.txt", "-c", "tools/kilit_kisit.txt", "--python-platform", hedef,
                   "--python-version", py, "-o", str(ara),
                   ortam=MAC_ORTAM if ad.startswith("macos") else None)
                metin = bloklari_cikar(ara.read_text(encoding="utf-8"), TORCH_PAKETLERI)
                hedef_dosya = KILIT / f"{ad}-py{py.replace('.', '')}.txt"
                hedef_dosya.write_text(
                    "# torch ve torchaudio bu dosyada YOK: kilit/torch-<katman>.txt (önce kurulur).\n"
                    + metin, encoding="utf-8", newline="\n")
    print("Kilitler yazıldı:", ", ".join(sorted(p.name for p in KILIT.glob("*.txt"))))
    return 0


if __name__ == "__main__":
    os.environ.setdefault("UV_CACHE_DIR", str(Path(tempfile.gettempdir()) / "sesver-uv-cache"))
    sys.exit(main())
