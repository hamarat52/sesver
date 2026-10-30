#!/bin/bash
# macos_ortak.sh kurulum/eşitleme senaryoları — geçici sahte dizinde, pip stub'lı.
# Ağ, gerçek pip ve gerçek desktop.py KULLANILMAZ. Kullanım: bash tests/macos_senaryolari.sh
set -u
KOK="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/sesver-senaryo.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT
HATA=0

kur_sahte_dizin() {  # $1 = dizin
  mkdir -p "$1/python-embed/bin"
  cp "$KOK/macos_ortak.sh" "$KOK/requirements.txt" "$1/"
  # Sahte python3: her çağrıyı cagrilar.log'a yazar; PIP_HATA=1 ise "-r" kurulumu başarısız olur.
  cat > "$1/python-embed/bin/python3" <<'STUB'
#!/bin/bash
echo "$*" >> "$(dirname "$0")/../../cagrilar.log"
if [ "$1" = "--version" ]; then echo "Python 3.11.99 (sahte)"; exit 0; fi
if [ "${PIP_HATA:-0}" = "1" ] && [ "$1 $2 $3" = "-m pip install" ] && [ "${4:-}" = "-r" ]; then
  echo "ERROR: sahte pip hatası (ağ yok)" >&2; exit 1
fi
exit 0
STUB
  chmod +x "$1/python-embed/bin/python3"
}

calistir() {  # $1 = dizin; çıkış kodunu döndürür
  ( cd "$1" && SESVER_MOD=konsol bash -c 'source ./macos_ortak.sh; sesver_baslat' </dev/null >cikti.log 2>&1 )
}

beklenen_isaret() { printf 'req_sha256=%s voxcpm=2.0.3' "$(shasum -a 256 "$1/requirements.txt" | awk '{print $1}')"; }

dogrula() {  # $1 = açıklama, $2 = koşul (bash ifadesi)
  if eval "$2"; then echo "  [OK]   $1"; else echo "  [HATA] $1"; HATA=1; fi
}

ozet() {  # $1 = dizin
  echo "  çağrılar:"; sed 's/^/    | /' "$1/cagrilar.log"
  echo "  işaret: $(cat "$1/python-embed/sesver_kurulum_tamam.txt" 2>/dev/null || echo '(yok)')"
}

echo "== (a) işaret yok -> tam kurulum"
D="$TMP/a"; kur_sahte_dizin "$D"
calistir "$D"; kod=$?
ozet "$D"
dogrula "çıkış 0" "[ $kod -eq 0 ]"
dogrula "pip güncelleme çalıştı" "grep -qx -- '-m pip install --upgrade pip --quiet' '$D/cagrilar.log'"
dogrula "voxcpm --no-deps kuruldu" "grep -qx -- '-m pip install --no-deps voxcpm==2.0.3' '$D/cagrilar.log'"
dogrula "requirements kuruldu" "grep -qx -- '-m pip install -r requirements.txt' '$D/cagrilar.log'"
dogrula "yeni biçim işaret yazıldı" "[ \"\$(cat '$D/python-embed/sesver_kurulum_tamam.txt')\" = \"\$(beklenen_isaret '$D')\" ]"
dogrula "desktop.py açıldı" "tail -n 1 '$D/cagrilar.log' | grep -qx desktop.py"

echo "== (b) eski 'tamam' işareti -> yalnız senkron (tam kurulum YOK)"
D="$TMP/b"; kur_sahte_dizin "$D"; echo tamam > "$D/python-embed/sesver_kurulum_tamam.txt"
calistir "$D"; kod=$?
ozet "$D"
dogrula "çıkış 0" "[ $kod -eq 0 ]"
dogrula "pip güncelleme (tam kurulum) YOK" "! grep -q -- '--upgrade pip' '$D/cagrilar.log'"
dogrula "'İlk kurulum' mesajı YOK" "! grep -q 'İlk kurulum' '$D/cikti.log'"
dogrula "voxcpm pini bilinmiyordu -> voxcpm eşitlendi" "grep -qx -- '-m pip install --no-deps voxcpm==2.0.3' '$D/cagrilar.log'"
dogrula "requirements eşitlendi" "grep -qx -- '-m pip install -r requirements.txt' '$D/cagrilar.log'"
dogrula "işaret yeni biçime geçti" "[ \"\$(cat '$D/python-embed/sesver_kurulum_tamam.txt')\" = \"\$(beklenen_isaret '$D')\" ]"

echo "== (c) özet aynı -> atla (yalnız --version + desktop.py)"
D="$TMP/c"; kur_sahte_dizin "$D"; beklenen_isaret "$D" > "$D/python-embed/sesver_kurulum_tamam.txt"
calistir "$D"; kod=$?
ozet "$D"
dogrula "çıkış 0" "[ $kod -eq 0 ]"
dogrula "hiç pip çağrısı yok" "! grep -q -- '-m pip' '$D/cagrilar.log'"
dogrula "desktop.py açıldı" "tail -n 1 '$D/cagrilar.log' | grep -qx desktop.py"

echo "== (d) requirements.txt değişti -> yalnız senkron (voxcpm pini aynı -> voxcpm yok)"
D="$TMP/d"; kur_sahte_dizin "$D"; beklenen_isaret "$D" > "$D/python-embed/sesver_kurulum_tamam.txt"
echo "yeni-paket==1.0" >> "$D/requirements.txt"
calistir "$D"; kod=$?
ozet "$D"
dogrula "çıkış 0" "[ $kod -eq 0 ]"
dogrula "pip güncelleme (tam kurulum) YOK" "! grep -q -- '--upgrade pip' '$D/cagrilar.log'"
dogrula "voxcpm yeniden kurulmadı" "! grep -q voxcpm '$D/cagrilar.log'"
dogrula "requirements eşitlendi (tek pip çağrısı)" "[ \"\$(grep -c -- '-m pip' '$D/cagrilar.log')\" = 1 ] && grep -qx -- '-m pip install -r requirements.txt' '$D/cagrilar.log'"
dogrula "işaret yeni özete güncellendi" "[ \"\$(cat '$D/python-embed/sesver_kurulum_tamam.txt')\" = \"\$(beklenen_isaret '$D')\" ]"

echo "== (e) senkron başarısız -> işaret ESKİ hâliyle kalır, hata yolu, uygulama açılmaz"
D="$TMP/e"; kur_sahte_dizin "$D"; echo tamam > "$D/python-embed/sesver_kurulum_tamam.txt"
( cd "$D" && PIP_HATA=1 SESVER_MOD=konsol bash -c 'source ./macos_ortak.sh; sesver_baslat' </dev/null >cikti.log 2>&1 ); kod=$?
ozet "$D"
echo "  çıktı (son 4 satır):"; tail -n 4 "$D/cikti.log" | sed 's/^/    | /'
dogrula "çıkış 1" "[ $kod -eq 1 ]"
dogrula "işaret hâlâ 'tamam'" "[ \"\$(cat '$D/python-embed/sesver_kurulum_tamam.txt')\" = tamam ]"
dogrula "hata mesajı adımı söylüyor" "grep -q 'Kurulum adımı başarısız oldu: requirements.txt eşitleme' '$D/cikti.log'"
dogrula "desktop.py açılmadı" "! grep -qx desktop.py '$D/cagrilar.log'"

echo
if [ $HATA -eq 0 ]; then echo "TÜM SENARYOLAR GEÇTİ"; else echo "BAŞARISIZ SENARYO VAR"; fi
exit $HATA
