#!/bin/bash
# SesVer başlatıcı — macOS / Linux. Çift tıklayın veya terminalde çalıştırın.
# İlk çalıştırmada ortamı kurar; sonrakilerde doğrudan açar.
# (macOS'ta Terminal penceresi istemiyorsanız aynı klasördeki SesVer.app'i açın.)
#
# Kurulum/başlatma mantığının tamamı macos_ortak.sh içindedir; SesVer.app de
# aynı dosyayı kullanır.
cd "$(dirname "$0")"
chmod +x "$(basename "$0")" 2>/dev/null || true
# İnternetten (ZIP) indirilen klasördeki karantina (indirme) işaretini temizle:
# kullanıcı bu dosyayı Gatekeeper'da "Yine de Aç" ile onaylayıp çalıştırdıysa
# klasöre güvenmiştir. İşaret kalırsa macOS SesVer.app'i her açılışta geçici bir
# konumdan (App Translocation) çalıştırır ve proje dosyalarını göremez.
# YALNIZ bu klasör ($PWD) — başka yol asla. Hata olursa sessizce devam edilir.
if [ "$(uname -s)" = "Darwin" ] && command -v xattr >/dev/null 2>&1; then
  for _f in "$(basename "$0")" SesVer.app desktop.py macos_ortak.sh .; do
    if [ -e "$_f" ] && xattr -p com.apple.quarantine "$_f" >/dev/null 2>&1; then
      echo "İndirme (karantina) işareti temizleniyor: $PWD"
      xattr -dr com.apple.quarantine "$PWD" >/dev/null 2>&1 || true
      break
    fi
  done
  unset _f
fi
if [ ! -f "macos_ortak.sh" ]; then
  echo "[HATA] macos_ortak.sh bulunamadı; SesVer klasörü eksik. Projeyi yeniden indirin."
  read -n 1 -s -r -p "Çıkmak için bir tuşa basın..." || true
  echo
  exit 1
fi
SESVER_MOD=konsol
. ./macos_ortak.sh
sesver_baslat
