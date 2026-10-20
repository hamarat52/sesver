#!/bin/bash
# SesVer.app başlatma betiği (Platypus tarzı; Python dondurulmaz).
# Doğrudan çalıştırılmaz: Finder/Dock/"open" ile açıldığında paketin yerel
# başlatıcısı (Contents/MacOS/SesVer, kaynağı macos/sesver_app_launcher.c) bu
# betiği /bin/bash alt süreci olarak çalıştırır ve SESVER_APP_EXE'yi verir.
# Kurulum/başlatma mantığı proje kökündeki macos_ortak.sh'tadır
# (MACOS_BASLAT.command ile ortak).
#
# Yol: $0 = <proje kökü>/SesVer.app/Contents/Resources/sesver_app.sh
#      ../../.. = <proje kökü>
SESVER_APP_EXE="${SESVER_APP_EXE:-$(cd "$(dirname "$0")/../MacOS" 2>/dev/null && pwd)/SesVer}"
export SESVER_APP_EXE

sesver_app_hata() {
  osascript \
    -e 'on run argv' \
    -e 'display dialog (item 1 of argv) with title "SesVer" buttons {"Tamam"} default button 1 with icon stop' \
    -e 'end run' \
    "$1" >/dev/null 2>&1
  exit 1
}

cd "$(dirname "$0")/../../.." 2>/dev/null || exit 1
if [ ! -f "macos_ortak.sh" ] || [ ! -f "desktop.py" ]; then
  # Uygulama proje klasörünün dışına (ör. Uygulamalar'a) taşınmış olabilir.
  sesver_app_hata "SesVer.app, SesVer proje klasörünün içinde durmalı (desktop.py ve macos_ortak.sh ile aynı klasörde). Şu an bulunduğu yer: $PWD

Uygulamayı taşımak yerine Dock'a sabitleyin ya da Finder'da sağ tık > Takma Ad Yap ile kısayol oluşturun."
fi
SESVER_MOD=app
# Dosya var ama okunamıyorsa (ör. macOS gizlilik izni reddedildi) sessizce
# kapanmak yerine nedenini göster.
if ! . ./macos_ortak.sh || ! declare -F sesver_baslat >/dev/null; then
  sesver_app_hata "SesVer, proje dosyalarını okuyamadı: $PWD/macos_ortak.sh

Sistem Ayarları > Gizlilik ve Güvenlik > Dosyalar ve Klasörler > SesVer altında ilgili klasörü (ör. Masaüstü Klasörü) açın ve SesVer'i tekrar başlatın."
fi
sesver_baslat
