#!/bin/bash
# SesVer macOS yayın hattı — TEK KOMUT.
#
#   macos/release_mac.sh [<sürüm>] [--dry-run]
#
# Sürüm: kökteki VERSION dosyası (HEAD) tek kaynaktır. Argüman isteğe bağlıdır;
# verilirse VERSION ile aynı olmalıdır, değilse çıkış kodu 64.
#
# Üretir:  dist/SesVer.app                (kendi kendine yeterli, "DMG modu")
#          dist/SesVer-<sürüm>-macOS.dmg
#
# Gerçek mod  : anahtarlıkta "Developer ID Application:" kimliği gerekir. App ve DMG
#               imzalanır, Apple'a notarize edilir (notarytool, keychain profili
#               ${SESVER_NOTARY_PROFILE:-sesver-notary}) ve staple edilir.
# --dry-run   : notarize YOK. Developer ID yoksa "Apple Development:" (o da yoksa
#               ad-hoc) ile imzalar; tüm hattı ve doğrulamaları kuru çalıştırır.
#               spctl'in "rejected" demesi bu modda BEKLENENDİR.
# Developer ID yokken --dry-run'sız çalıştırılırsa: KAPI mesajı + çıkış kodu 2
# (hiçbir şey derlenmez, notarytool çağrılmaz).
#
# Payload (uygulamanın içine gömülen proje dosyaları) yalnız "git archive HEAD"
# çıktısından ve bir İZİN LİSTESİYLE toplanır; commit'lenmemiş değişiklikler pakete
# GİRMEZ. voices/seslerim (kişisel ses klonları) hiçbir koşulda pakete girmez:
# HEAD'de ya da payload'da görülürse yapı HATA ile durur.
#
# Ayrıntı: docs/macos-yayin.md
set -euo pipefail

BUNDLE_ID="com.hamaratlabs.sesver"
NOTARY_PROFILE="${SESVER_NOTARY_PROFILE:-sesver-notary}"

kullanim() {
  echo "Kullanım: macos/release_mac.sh [<sürüm>] [--dry-run]   (ör. macos/release_mac.sh --dry-run)" >&2
  echo "  Sürüm kökteki VERSION dosyasından okunur (HEAD'deki hâli); argüman verilirse VERSION ile aynı olmalı." >&2
  exit 64
}

SURUM=""
KURU=0
for a in "$@"; do
  case "$a" in
    --dry-run) KURU=1 ;;
    -h|--help) kullanim ;;
    -*) echo "Bilinmeyen seçenek: $a" >&2; kullanim ;;
    *) [ -z "$SURUM" ] || kullanim; SURUM="$a" ;;
  esac
done

cd "$(dirname "$0")/.."
KOK="$PWD"

# Tek kaynak: VERSION (payload HEAD'den alındığı için HEAD'deki hâli okunur;
# surum.py ve windows/SesVer.iss de aynı dosyayı okur).
DOSYA_SURUM="$(git show HEAD:VERSION 2>/dev/null | tr -d '\r\357\273\277' | tr -d '[:space:]')" || DOSYA_SURUM=""
if [ -z "$DOSYA_SURUM" ]; then
  echo "[HATA] HEAD'de VERSION dosyası yok ya da boş (git show HEAD:VERSION)." >&2
  exit 64
fi
if [ -z "$SURUM" ]; then
  SURUM="$DOSYA_SURUM"
elif [ "$SURUM" != "$DOSYA_SURUM" ]; then
  echo "[HATA] Argümandaki sürüm ($SURUM) VERSION dosyasıyla ($DOSYA_SURUM) uyuşmuyor." >&2
  echo "       VERSION'ı güncelleyip commit'leyin ya da sürüm argümanını vermeyin." >&2
  exit 64
fi
if ! [[ "$SURUM" =~ ^[0-9]+(\.[0-9]+){0,2}$ ]]; then
  echo "[HATA] Sürüm 1.2.0 biçiminde olmalı (CFBundleVersion en çok 3 sayı): $SURUM" >&2
  exit 64
fi

DIST="$KOK/dist"
APP="$DIST/SesVer.app"
DMG="$DIST/SesVer-$SURUM-macOS.dmg"

baslik() { printf '\n==== %s ====\n' "$1"; }
hata() { echo "[HATA] $*" >&2; exit 1; }

# ------------------------------------------------------------- 1. Önkoşullar ---
baslik "1. Önkoşullar"
for c in git xcrun codesign security hdiutil clang strip ditto rsync file plutil shasum tar xattr spctl; do
  command -v "$c" >/dev/null 2>&1 || hata "'$c' bulunamadı (Xcode Komut Satırı Araçları: xcode-select --install)."
done
NOTARYTOOL="$(xcrun --find notarytool 2>/dev/null)" || hata "notarytool bulunamadı (Xcode 13+ gerekir)."
STAPLER="$(xcrun --find stapler 2>/dev/null)" || hata "stapler bulunamadı (Xcode gerekir)."
echo "notarytool: $NOTARYTOOL"
echo "stapler   : $STAPLER"
echo "clang     : $(clang --version | head -n 1)"
git rev-parse --verify -q HEAD >/dev/null || hata "Git deposu/HEAD bulunamadı."
GIT_SHA="$(git rev-parse --short HEAD)"
echo "HEAD      : $GIT_SHA ($(git rev-parse --abbrev-ref HEAD))"
if [ -n "$(git status --porcelain)" ]; then
  echo "[UYARI] Çalışma ağacı temiz değil. Payload HEAD'den ($GIT_SHA) alınır;"
  echo "        commit'lenmemiş değişiklikler pakete GİRMEZ:"
  git status --short | sed 's/^/        /'
fi

# --------------------------------------------------------- 2. Kimlik seçimi ---
baslik "2. İmza kimliği"
KIMLIKLER="$(security find-identity -v -p codesigning 2>/dev/null || true)"
# Satır biçimi:   1) <SHA1> "<Ad>"
kimlik_bul() { # $1 = ad öneki -> "SHA1<TAB>Ad" (ilk eşleşme)
  printf '%s\n' "$KIMLIKLER" \
    | sed -n "s/^ *[0-9][0-9]*) \([0-9A-F]\{40\}\) \"\($1[^\"]*\)\".*/\1	\2/p" | head -n 1
}
SIG_HASH=""; SIG_AD=""; MOD=""
if [ -n "$(kimlik_bul 'Developer ID Application: ')" ]; then
  IFS=$'\t' read -r SIG_HASH SIG_AD <<<"$(kimlik_bul 'Developer ID Application: ')"
  MOD="gercek"
  [ "$KURU" = 1 ] && MOD="kuru-devid"
elif [ "$KURU" = 1 ]; then
  if [ -n "$(kimlik_bul 'Apple Development: ')" ]; then
    IFS=$'\t' read -r SIG_HASH SIG_AD <<<"$(kimlik_bul 'Apple Development: ')"
    MOD="kuru"
  else
    SIG_HASH="-"; SIG_AD="ad-hoc (-)"; MOD="kuru-adhoc"
  fi
else
  # Bilgi amaçlı: mevcut Apple Development sertifikasının OU (takım) alanı.
  team_ipucu() {
    local ad ou
    ad="$(kimlik_bul 'Apple Development: ' | cut -f2)"
    [ -n "$ad" ] || return 0
    ou="$(security find-certificate -a -p -c "$ad" 2>/dev/null \
          | openssl x509 -noout -subject -nameopt multiline 2>/dev/null \
          | sed -n 's/^ *organizationalUnitName *= *//p' | head -n 1)" || ou=""
    [ -n "$ou" ] && echo "(Bilgi: Apple Development sertifikasının takım alanı (OU) = $ou. Developer ID"
    [ -n "$ou" ] && echo " sertifikası aynı takımda olmalı; Team ID'yi yine de Xcode'da doğrulayın.)"
    return 0
  }
  cat <<KAPI

==================================================================== KAPI ====
Developer ID Application sertifikası bu Mac'in anahtarlığında YOK.
Gerçek (notarize edilmiş) yayın yapılamaz; hiçbir şey derlenmedi, Apple'a
hiçbir şey gönderilmedi. Kuru çalıştırma için: macos/release_mac.sh $SURUM --dry-run

Bulunan imza kimlikleri:
$(printf '%s\n' "$KIMLIKLER" | sed 's/^/  /')
$(team_ipucu)

Yapılacaklar (bir kez, Yusuf kendisi):
  1) Xcode -> Settings -> Accounts -> Apple ID'nizi seçin (Team: Muhammed Yusuf
     Hamarat) -> Manage Certificates... -> sol alttaki "+" -> "Developer ID Application".
     (Ücretli Apple Developer Program üyeliği ve Account Holder rolü gerekir.)
  2) Team ID'nizi öğrenin: Xcode -> Settings -> Accounts'ta takımın yanında görünür
     (ya da developer.apple.com -> Account -> Membership details). Not: sertifika
     adındaki parantez içi kod (ör. G74FR6X39U) kişisel kimliktir, Team ID
     OLMAYABİLİR — tahmin etmeyin.
  3) appleid.apple.com -> Giriş ve Güvenlik -> Uygulamaya özel parolalar'dan bir
     parola oluşturun (SesVer notarize gibi bir ad verin).
  4) Terminal'de (parolayı komut sizden isteyince kendiniz girin):
       xcrun notarytool store-credentials $NOTARY_PROFILE --apple-id <apple-id> --team-id <TEAM_ID>
  5) Tek komut:
       macos/release_mac.sh $SURUM
==============================================================================
KAPI
  exit 2
fi
echo "Mod    : $MOD"
echo "Kimlik : $SIG_AD"
[ "$SIG_HASH" != "-" ] && echo "SHA-1  : $SIG_HASH"
TEAM_OU=""
if [ "$SIG_HASH" != "-" ]; then
  TEAM_OU="$(security find-certificate -a -Z -p -c "$SIG_AD" 2>/dev/null \
             | openssl x509 -noout -subject -nameopt multiline 2>/dev/null \
             | sed -n 's/^ *organizationalUnitName *= *//p' | head -n 1)" || TEAM_OU=""
  echo "Team ID (sertifika OU): ${TEAM_OU:-okunamadı}"
fi

# ------------------------------------------------------------- 3. Payload ---
baslik "3. Payload (git archive HEAD + izin listesi)"
IS="$DIST/.build"
rm -rf "$APP" "$IS" "$DMG"
mkdir -p "$IS/kaynak" "$IS/payload"
if git ls-tree -r --name-only HEAD | grep -q '^voices/seslerim/'; then
  hata "HEAD'de voices/seslerim/ var (kişisel ses klonları). Yayın durduruldu; bu dosyalar commit'ten çıkarılmalı."
fi
git archive --format=tar HEAD | tar -xf - -C "$IS/kaynak"
SRC="$IS/kaynak"
PL="$IS/payload"
# İzin listesi. Kökteki *.py (alt klasörler HARİÇ), tekil dosyalar, locales/*.json,
# voices/hazir/**. Başka hiçbir şey payload'a girmez.
( cd "$SRC"
  for f in *.py; do [ -f "$f" ] && cp -p "$f" "$PL/"; done
  for f in VERSION requirements.txt voice_design_map.json macos_ortak.sh LICENSE README.md AI_KURULUM.md; do
    [ -f "$f" ] || { echo "[HATA] Payload için gerekli dosya HEAD'de yok: $f" >&2; exit 1; }
    cp -p "$f" "$PL/"
  done
  mkdir -p "$PL/locales"
  cp -p locales/*.json "$PL/locales/"
  [ -d voices/hazir ] || { echo "[HATA] voices/hazir HEAD'de yok." >&2; exit 1; }
  mkdir -p "$PL/voices"
  ditto voices/hazir "$PL/voices/hazir"
)
for f in desktop.py app.py macos_ortak.sh requirements.txt; do
  [ -f "$PL/$f" ] || hata "Payload eksik: $f"
done
printf '%s (%s)\n' "$SURUM" "$GIT_SHA" >"$PL/.sesver_payload_version"
# Yasak içerik denetimi (ikinci kat): kişisel sesler, Python ortamları, çıktılar, ayarlar.
YASAK="$(cd "$PL" && find . \( -path './voices/seslerim' -o -path './voices/seslerim/*' \
          -o -name '__pycache__' -o -name '.venv' -o -name 'python-embed*' -o -name 'outputs' \
          -o -name 'ayarlar.json*' -o -name '*.pyc' -o -name 'sesver_log.txt' \
          -o -name 'sesver_baslatici_log.txt' -o -name '.DS_Store' -o -iname '*yusuf*' -o -iname '*akif*' \) -print)"
[ -z "$YASAK" ] || hata "Payload'da yasak içerik bulundu:
$YASAK"
echo "Damga  : $(cat "$PL/.sesver_payload_version")"
echo "Dosya  : $(find "$PL" -type f | wc -l | tr -d ' ') dosya, $(du -sh "$PL" | cut -f1)"
echo "Üst düzey: $(cd "$PL" && ls -A | tr '\n' ' ')"

# --------------------------------------------------------- 4. Paket kurulumu ---
baslik "4. dist/SesVer.app"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
clang -Os -Wall -Wextra -Werror \
  -arch arm64 -arch x86_64 -mmacosx-version-min=11.0 \
  -framework CoreFoundation \
  -o "$APP/Contents/MacOS/SesVer" "$SRC/macos/sesver_app_launcher.c"
strip -x "$APP/Contents/MacOS/SesVer"
cp "$SRC/SesVer.app/Contents/Info.plist" "$APP/Contents/Info.plist"
plutil -replace CFBundleShortVersionString -string "$SURUM" "$APP/Contents/Info.plist"
plutil -replace CFBundleVersion -string "$SURUM" "$APP/Contents/Info.plist"
plutil -replace CFBundleIdentifier -string "$BUNDLE_ID" "$APP/Contents/Info.plist"
# DMG modunda proje Masaüstü/Belgeler/İndirilenler'de değil; bu izin metinleri gereksiz.
for k in NSDesktopFolderUsageDescription NSDocumentsFolderUsageDescription NSDownloadsFolderUsageDescription; do
  plutil -remove "$k" "$APP/Contents/Info.plist" 2>/dev/null || true
done
plutil -lint "$APP/Contents/Info.plist" >/dev/null
cp "$SRC/SesVer.app/Contents/Resources/SesVer.icns" "$APP/Contents/Resources/"
cp "$SRC/SesVer.app/Contents/Resources/sesver_app.sh" "$APP/Contents/Resources/"
ditto "$PL" "$APP/Contents/Resources/payload"
chmod -R u+rwX,go+rX,go-w "$APP"
# codesign, Finder bilgisi/kaynak çatalı gibi genişletilmiş öznitelikleri reddeder.
xattr -cr "$APP"
echo "Sürüm  : $(plutil -extract CFBundleShortVersionString raw "$APP/Contents/Info.plist") / $(plutil -extract CFBundleVersion raw "$APP/Contents/Info.plist")"
file "$APP/Contents/MacOS/SesVer"

# ----------------------------------------------------------------- 5. İmza ---
baslik "5. İmza ($SIG_AD)"
ENT="$SRC/macos/SesVer.entitlements"
[ -f "$ENT" ] || hata "macos/SesVer.entitlements HEAD'de yok."
plutil -lint "$ENT" >/dev/null
IMZA_OPS=(--force --options runtime --sign "$SIG_HASH")
[ "$SIG_HASH" != "-" ] && IMZA_OPS+=(--timestamp)
# Paketteki TÜM Mach-O dosyaları (file ile), en derindekinden başlayarak (içten dışa).
MACHO=()
while IFS= read -r f; do MACHO+=("$f"); done < <(
  find "$APP" -type f -print0 \
    | while IFS= read -r -d '' f; do
        if file -b "$f" | grep -q 'Mach-O'; then
          printf '%s\t%s\n' "$(printf '%s' "$f" | tr -cd '/' | wc -c | tr -d ' ')" "$f"
        fi
      done | sort -t $'\t' -k1,1nr | cut -f2-)
[ "${#MACHO[@]}" -gt 0 ] || hata "Pakette Mach-O bulunamadı."
for f in "${MACHO[@]}"; do
  echo "İmzalanıyor (Mach-O): ${f#"$DIST/"}"
  codesign "${IMZA_OPS[@]}" "$f"
done
echo "İmzalanıyor (paket) : SesVer.app  [entitlements: macos/SesVer.entitlements]"
codesign "${IMZA_OPS[@]}" --identifier "$BUNDLE_ID" --entitlements "$ENT" "$APP"

# Notarize yardımcısı (yalnız gerçek mod). $1 = gönderilecek dosya
notarize() {
  local dosya="$1" cikti id durum
  echo "notarytool submit: ${dosya#"$DIST/"} (profil: $NOTARY_PROFILE) ..."
  set +e
  cikti="$(xcrun notarytool submit "$dosya" --keychain-profile "$NOTARY_PROFILE" --wait 2>&1)"
  local kod=$?
  set -e
  printf '%s\n' "$cikti"
  id="$(printf '%s\n' "$cikti" | sed -n 's/^ *id: *\([0-9a-fA-F-]\{36\}\).*/\1/p' | tail -n 1)"
  durum="$(printf '%s\n' "$cikti" | sed -n 's/^ *status: *//p' | tail -n 1)"
  if [ "$kod" -ne 0 ] || [ "$durum" != "Accepted" ]; then
    echo "[HATA] Notarize başarısız (durum: ${durum:-bilinmiyor})."
    if [ -n "$id" ]; then
      echo "---- notarytool log $id ----"
      xcrun notarytool log "$id" --keychain-profile "$NOTARY_PROFILE" || true
    fi
    exit 1
  fi
}

if [ "$MOD" = "gercek" ]; then
  baslik "6a. App notarize + staple"
  ditto -c -k --keepParent "$APP" "$IS/SesVer-notarize.zip"
  notarize "$IS/SesVer-notarize.zip"
  xcrun stapler staple "$APP"
fi

# ------------------------------------------------------------------- 6. DMG ---
baslik "6. DMG"
mkdir -p "$IS/dmg"
ditto "$APP" "$IS/dmg/SesVer.app"
ln -s /Applications "$IS/dmg/Applications"
hdiutil create -volname SesVer -srcfolder "$IS/dmg" -format UDZO -ov "$DMG"
DMG_OPS=(--force --sign "$SIG_HASH")
[ "$SIG_HASH" != "-" ] && DMG_OPS+=(--timestamp)
codesign "${DMG_OPS[@]}" "$DMG"
echo "İmzalandı (DMG): ${DMG#"$KOK/"}"
if [ "$MOD" = "gercek" ]; then
  baslik "6b. DMG notarize + staple"
  notarize "$DMG"
  xcrun stapler staple "$DMG"
fi

# ------------------------------------------------------------ 7. Doğrulama ---
baslik "7. Doğrulama"
echo "\$ codesign --verify --deep --strict --verbose=2 dist/SesVer.app"
codesign --verify --deep --strict --verbose=2 "$APP" 2>&1
echo
echo "\$ codesign -dv --verbose=4 dist/SesVer.app"
codesign -dv --verbose=4 "$APP" 2>&1 | grep -E '^(Executable=|Identifier=|Format=|CodeDirectory |Authority=|Timestamp=|Signed Time=|TeamIdentifier=|Runtime Version=|Sealed Resources )' || true
echo
echo "Paketteki her Mach-O:"
for f in "${MACHO[@]}"; do
  echo "\$ codesign -dv ${f#"$DIST/"}"
  codesign -dv --verbose=4 "$f" 2>&1 | grep -E '^(Identifier=|CodeDirectory |Authority=|TeamIdentifier=|Timestamp=)' | sed 's/^/    /'
done
echo
echo "\$ codesign -d --entitlements - --xml dist/SesVer.app   (':-' biçiminin güncel karşılığı)"
codesign -d --entitlements - --xml "$APP" 2>&1 || true
echo
echo "\$ hdiutil verify ${DMG#"$KOK/"}"
hdiutil verify "$DMG" 2>&1 | tail -n 3
echo
echo "\$ codesign --verify --strict --verbose=2 ${DMG#"$KOK/"}"
codesign --verify --strict --verbose=2 "$DMG" 2>&1
codesign -dv "$DMG" 2>&1 | grep -E '^(Authority|TeamIdentifier|Timestamp)=' || true
echo
SPCTL_HATA=0
echo "\$ spctl -a -vv dist/SesVer.app"
spctl -a -vv "$APP" 2>&1 || SPCTL_HATA=1
echo "\$ spctl -a -t open --context context:primary-signature -vv ${DMG#"$KOK/"}"
spctl -a -t open --context context:primary-signature -vv "$DMG" 2>&1 || SPCTL_HATA=1
if [ "$MOD" = "gercek" ]; then
  echo
  echo "\$ xcrun stapler validate (app + DMG)"
  xcrun stapler validate "$APP"
  xcrun stapler validate "$DMG"
  [ "$SPCTL_HATA" = 0 ] || hata "Gatekeeper (spctl) notarize edilmiş paketi reddetti."
elif [ "$SPCTL_HATA" = 1 ]; then
  echo "[BİLGİ] spctl 'rejected': Developer ID + notarize olmadığı için BEKLENEN (kuru çalıştırma)."
fi

# --------------------------------------------------------------- 8. Özet ---
baslik "8. Özet"
APP_AGAC_SHA="$(cd "$APP" && find . -type f -print0 | LC_ALL=C sort -z | xargs -0 shasum -a 256 | shasum -a 256 | cut -d' ' -f1)"
echo "Mod        : $MOD   Kimlik: $SIG_AD"
echo "App        : ${APP#"$KOK/"}  $(du -sh "$APP" | cut -f1)"
echo "App SHA256 : $APP_AGAC_SHA  (dosya ağacı: sıralı 'shasum -a 256' listesinin özeti)"
echo "DMG        : ${DMG#"$KOK/"}  $(du -h "$DMG" | cut -f1) ($(stat -f %z "$DMG") bayt)"
echo "DMG SHA256 : $(shasum -a 256 "$DMG" | cut -d' ' -f1)"
rm -rf "$IS"
if [ "$MOD" != "gercek" ]; then
  echo
  echo "KURU ÇALIŞTIRMA: notarize yapılmadı. Bu DMG kullanıcılara DAĞITILMAZ."
fi
