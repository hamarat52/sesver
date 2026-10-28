#!/bin/bash
# SesVer.app başlatma betiği (Platypus tarzı; Python dondurulmaz).
# Doğrudan çalıştırılmaz: Finder/Dock/"open" ile açıldığında paketin yerel
# başlatıcısı (Contents/MacOS/SesVer, kaynağı macos/sesver_app_launcher.c) bu
# betiği /bin/bash alt süreci olarak çalıştırır ve SESVER_APP_EXE'yi verir.
# Kurulum/başlatma mantığı macos_ortak.sh'tadır (MACOS_BASLAT.command ile ortak).
#
# İki dağıtım modu (ayrıntı: docs/macos-yayin.md):
#
#   DMG modu : Contents/Resources/payload/.sesver_payload_version VARSA. Paket kendi
#              kendine yeterlidir (macos/release_mac.sh üretir). Payload, sürüm
#              damgası değiştiğinde SESVER_HOME'a eşitlenir (varsayılan:
#              ~/Library/Application Support/SesVer) ve SesVer orada çalışır:
#              python-embed, outputs, voices/seslerim, ayarlar.json orada kalır.
#              İmzalı paket hiç değiştirilmez; macOS paketi geçici bir konumdan
#              (App Translocation) açsa da çalışır. Eşitleme hiçbir dosyayı SİLMEZ
#              ve kullanıcı verisini asla ezmez.
#   ZIP modu : payload YOKSA (repodaki / GitHub ZIP'indeki SesVer.app). Paket proje
#              klasörünün içinde durur:
#              $0 = <proje kökü>/SesVer.app/Contents/Resources/sesver_app.sh,
#              ../../.. = <proje kökü>.
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

RES_DIR="$(cd "$(dirname "$0")" 2>/dev/null && pwd)" || exit 1
PAYLOAD_DIR="$RES_DIR/payload"
DAMGA=".sesver_payload_version"
unset SESVER_GUNLUK_EKLE

# Çalışma dizinindeki macos_ortak.sh'ı yükleyip sesver_baslat'ı çağırır.
ortak_yukle_ve_baslat() {
  # Dosya var ama okunamıyorsa (ör. macOS gizlilik izni reddedildi) sessizce
  # kapanmak yerine nedenini göster.
  if ! . ./macos_ortak.sh || ! declare -F sesver_baslat >/dev/null; then
    sesver_app_hata "SesVer, proje dosyalarını okuyamadı: $PWD/macos_ortak.sh

Sistem Ayarları > Gizlilik ve Güvenlik > Dosyalar ve Klasörler > SesVer altında ilgili klasörü (ör. Masaüstü Klasörü) açın ve SesVer'i tekrar başlatın."
  fi
  sesver_baslat
}

# ---------------------------------------------------------------- DMG modu ---
if [ -f "$PAYLOAD_DIR/$DAMGA" ]; then
  SESVER_HOME="${SESVER_HOME:-$HOME/Library/Application Support/SesVer}"
  export SESVER_HOME
  if ! mkdir -p "$SESVER_HOME" 2>/dev/null || ! cd "$SESVER_HOME" 2>/dev/null; then
    sesver_app_hata "SesVer çalışma klasörü oluşturulamadı: $SESVER_HOME"
  fi
  GUNLUK="$SESVER_HOME/sesver_baslatici_log.txt"
  # Günlük her açılışta yeniden başlar; macos_ortak.sh (SESVER_GUNLUK_EKLE=1)
  # kendi çıktısını bunun arkasına ekler.
  if ! { echo "SesVer.app (DMG modu) $(date '+%Y-%m-%d %H:%M:%S')"
         echo "Paket : $(cd "$RES_DIR/../.." && pwd)"
         echo "Ev    : $SESVER_HOME"; } >"$GUNLUK" 2>/dev/null; then
    GUNLUK=/dev/null
  fi

  yeni="$(cat "$PAYLOAD_DIR/$DAMGA" 2>/dev/null)"
  eski="$(cat "$SESVER_HOME/$DAMGA" 2>/dev/null)" || eski=""
  if [ "$yeni" != "$eski" ] || [ ! -f "$SESVER_HOME/desktop.py" ] || [ ! -f "$SESVER_HOME/macos_ortak.sh" ]; then
    echo "Eşitleme: payload [$yeni] -> ev [${eski:-yok}]" >>"$GUNLUK"
    # --delete YOK: hiçbir dosya silinmez. Kullanıcı verisi ve kurulumlar ayrıca
    # dışlanır (payload'da zaten bulunmazlar; bu ikinci kat korumadır). Damga en
    # son yazılır: eşitleme yarıda kalırsa bir sonraki açılışta yeniden denenir.
    if ! /usr/bin/rsync -a \
        --exclude '/voices/seslerim' \
        --exclude '/outputs' \
        --exclude '/python-embed' \
        --exclude '/python-embed.indiriliyor' \
        --exclude '/.venv' \
        --exclude '/ayarlar.json' \
        --exclude '/ayarlar.json.yaz' \
        --exclude '/sesver_log.txt' \
        --exclude '/sesver_baslatici_log.txt' \
        --exclude '*.log' \
        --exclude "/$DAMGA" \
        "$PAYLOAD_DIR/" "$SESVER_HOME/" >>"$GUNLUK" 2>&1; then
      sesver_app_hata "SesVer dosyaları çalışma klasörüne kopyalanamadı.

Klasör: $SESVER_HOME
Ayrıntı: $GUNLUK"
    fi
    if ! cp "$PAYLOAD_DIR/$DAMGA" "$SESVER_HOME/$DAMGA" 2>>"$GUNLUK"; then
      sesver_app_hata "SesVer sürüm damgası yazılamadı: $SESVER_HOME/$DAMGA"
    fi
    echo "Eşitleme tamam." >>"$GUNLUK"
  else
    echo "Eşitleme gerekmedi (sürüm aynı: $yeni)." >>"$GUNLUK"
  fi
  if [ ! -f "macos_ortak.sh" ] || [ ! -f "desktop.py" ]; then
    sesver_app_hata "SesVer dosyaları çalışma klasöründe bulunamadı: $SESVER_HOME

Ayrıntı: $GUNLUK"
  fi
  SESVER_MOD=app
  SESVER_GUNLUK_EKLE=1
  ortak_yukle_ve_baslat
  exit $?
fi

# ---------------------------------------------------------------- ZIP modu ---
cd "$RES_DIR/../../.." 2>/dev/null || exit 1
if [ ! -f "macos_ortak.sh" ] || [ ! -f "desktop.py" ]; then
  case "$RES_DIR" in
    */AppTranslocation/*)
      # Karantinalı (internetten indirilmiş) paket: macOS onu salt-okunur geçici
      # bir kopyadan çalıştırıyor; yanındaki proje dosyaları görünmüyor.
      sesver_app_hata "macOS, SesVer'i güvenlik nedeniyle geçici bir konumdan açtı (internetten indirilen uygulamalar ilk açılışta böyle açılır). Bu yüzden SesVer yanındaki proje dosyalarını göremiyor.

Çözüm: İlk açılışı SesVer klasöründeki MACOS_BASLAT.command ile yapın (çift tıklayın; macOS engellerse Sistem Ayarları > Gizlilik ve Güvenlik > \"Yine de Aç\"). Bu açılış klasörün indirme işaretini temizler; sonraki açılışlarda SesVer.app doğrudan çalışır.

Geçici konum: $RES_DIR"
      ;;
  esac
  # Uygulama proje klasörünün dışına (ör. Uygulamalar'a) taşınmış olabilir.
  sesver_app_hata "SesVer.app, SesVer proje klasörünün içinde durmalı (desktop.py ve macos_ortak.sh ile aynı klasörde). Şu an bulunduğu yer: $PWD

Uygulamayı taşımak yerine Dock'a sabitleyin ya da Finder'da sağ tık > Takma Ad Yap ile kısayol oluşturun."
fi
SESVER_MOD=app
ortak_yukle_ve_baslat
