#!/bin/bash
# SesVer.app/Contents/MacOS/SesVer yerel başlatıcısını derler (universal: arm64 + x86_64)
# ve paketi ad-hoc imzalar. Yalnız macos/sesver_app_launcher.c değiştiğinde gerekir;
# derlenmiş ikili repoda durur, son kullanıcının Xcode'a ihtiyacı yoktur.
# Gereken: Xcode Komut Satırı Araçları (xcode-select --install).
set -euo pipefail
cd "$(dirname "$0")/.."
APP="SesVer.app"
OUT="$APP/Contents/MacOS/SesVer"
clang -Os -Wall -Wextra -Werror \
  -arch arm64 -arch x86_64 -mmacosx-version-min=11.0 \
  -o "$OUT" macos/sesver_app_launcher.c
strip -x "$OUT"
# TCC (Masaüstü vb. klasör izni) izni bu imzaya bağlanır; derleme sonrası ilk
# açılışta macOS izni bir kez daha sorabilir.
codesign --force --sign - --identifier com.hamaratlabs.sesver "$APP"
codesign --verify --strict --verbose=2 "$APP"
file "$OUT"
