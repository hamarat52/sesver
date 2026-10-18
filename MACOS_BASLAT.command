#!/bin/bash
# SesVer başlatıcı — macOS / Linux. Çift tıklayın veya terminalde çalıştırın.
# İlk çalıştırmada ortamı kurar; sonrakilerde doğrudan açar.
# (macOS'ta Terminal penceresi istemiyorsanız aynı klasördeki SesVer.app'i açın.)
#
# Kurulum/başlatma mantığının tamamı macos_ortak.sh içindedir; SesVer.app de
# aynı dosyayı kullanır.
cd "$(dirname "$0")"
chmod +x "$(basename "$0")" 2>/dev/null || true
if [ ! -f "macos_ortak.sh" ]; then
  echo "[HATA] macos_ortak.sh bulunamadı; SesVer klasörü eksik. Projeyi yeniden indirin."
  read -n 1 -s -r -p "Çıkmak için bir tuşa basın..." || true
  echo
  exit 1
fi
SESVER_MOD=konsol
. ./macos_ortak.sh
sesver_baslat
