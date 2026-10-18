#!/usr/bin/env python3
"""Her konsept icin gercek .icns (macOS) ve .ico (Windows) dosyalari uretir."""
import os
import shutil
import subprocess

from PIL import Image

ROOT = "/Users/hamaratbey/Desktop/Projeler/sesver/assets/app_icon"
SLUGS = ["concept1_soundwave", "concept2_microphone", "concept3_speech_wave", "concept4_letter_s"]

# iconutil icin gerekli standart boyutlar (ad, piksel)
ICNS_SIZES = [
    ("icon_16x16", 16),
    ("icon_16x16@2x", 32),
    ("icon_32x32", 32),
    ("icon_32x32@2x", 64),
    ("icon_128x128", 128),
    ("icon_128x128@2x", 256),
    ("icon_256x256", 256),
    ("icon_256x256@2x", 512),
    ("icon_512x512", 512),
    ("icon_512x512@2x", 1024),
]

ICO_SIZES = [16, 32, 48, 64, 128, 256]


def make_icns(src_png, out_icns):
    iconset_dir = out_icns.replace(".icns", ".iconset")
    if os.path.exists(iconset_dir):
        shutil.rmtree(iconset_dir)
    os.makedirs(iconset_dir)
    base = Image.open(src_png).convert("RGBA")
    for name, px in ICNS_SIZES:
        resized = base.resize((px, px), Image.LANCZOS)
        resized.save(os.path.join(iconset_dir, f"{name}.png"))
    result = subprocess.run(
        ["iconutil", "-c", "icns", iconset_dir, "-o", out_icns],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"iconutil hata: {result.stderr}")
    shutil.rmtree(iconset_dir)
    return out_icns


def make_ico(src_png, out_ico):
    base = Image.open(src_png).convert("RGBA")
    base.save(out_ico, format="ICO", sizes=[(s, s) for s in ICO_SIZES])
    return out_ico


def main():
    for slug in SLUGS:
        d = os.path.join(ROOT, slug)
        src = os.path.join(d, "icon_1024.png")
        icns_path = os.path.join(d, "SesVer.icns")
        ico_path = os.path.join(d, "SesVer.ico")
        make_icns(src, icns_path)
        make_ico(src, ico_path)
        icns_size = os.path.getsize(icns_path)
        ico_size = os.path.getsize(ico_path)
        print(f"[OK] {slug}: {icns_path} ({icns_size} bytes), {ico_path} ({ico_size} bytes)")


if __name__ == "__main__":
    main()
