# SesVer macOS başlatma mantığı — ORTAK dosya (doğrudan çalıştırılmaz).
# Hem MACOS_BASLAT.command (Terminal penceresiyle) hem SesVer.app (Terminal'siz,
# Dock'ta normal uygulama) bu dosyayı "source" edip sesver_baslat çağırır;
# kurulum/başlatma mantığı yalnız burada tutulur.
#
# Çağırmadan önce:
#   - çalışma dizini SesVer proje kökü olmalı (desktop.py'nin bulunduğu klasör);
#   - SESVER_MOD ayarlanmalı:
#       konsol : Terminal'de çalışıyor; mesajlar ekrana, hatada tuş beklenir.
#       app    : SesVer.app içinden; konsol yok. Çıktı sesver_baslatici_log.txt'ye
#                gider, hatalar ve ilk kurulum bilgisi osascript "display dialog"
#                penceresiyle gösterilir.
#
# Python'u ayrıca kurmanız GEREKMEZ: ilk çalıştırmada uygulamaya özel,
# taşınabilir bir Python (python-build-standalone, ~26 MB) indirilip bu
# klasördeki python-embed/ içine açılır ve paketler doğrudan oraya kurulur
# (ayrı sanal ortam gerekmez). İndirme yapılamazsa (internet yok, GitHub
# erişilemiyor) eski yönteme geri döner: sistemdeki python3.11/3.12/3.10/
# python3 ile .venv sanal ortamı.
#
# Kurulum yarıda kalırsa (internet kesildi, pencere kapandı) bir sonraki
# çalıştırmada kaldığı yerden devam eder: sesver_kurulum_tamam.txt işareti
# (python-embed/ ya da .venv/ içinde) yalnız tüm kurulum adımları başarıyla
# bitince yazılır.
#
# Güncelleme sonrası paket eşitleme: işaret dosyası tek satırdır:
#   kilit_sha256=<kilit/*.txt dosyalarının birlikte SHA-256 özeti> voxcpm=<voxcpm sürümü>
# Her açılışta beklenen satırla karşılaştırılır:
#   - işaret yok                      -> tam ilk kurulum (aşağıdaki akış)
#   - aynı                            -> kurulum adımı tamamen atlanır
#   - farklı ya da eski biçim         -> yalnız eşitleme: kilitli paketler kurulur
#     (pip --require-hashes; sürümü zaten tutan pakete dokunulmaz) ve işaret yeni
#     satırla yazılır. Ortam silinmez, baştan kurulmaz.
# Eşitleme başarısız olursa işaret ESKİ hâliyle kalır (bir sonraki açılışta
# yeniden denenir) ve ilk kurulumdaki hata yolu gösterilir.
#
# Tedarik zinciri: ağdan inen her şey sabit sürüm + sabit SHA-256 ile iner.
#   - Gömülü Python: tek sabit sürüm ve özet (PBS_* aşağıda); "en yeni" sorgusu yok.
#   - pip paketleri: kilit/ klasöründeki dosyalar (tools/kilit_uret.py üretir),
#     hepsi --require-hashes ile kurulur. Özet tutmazsa kurulum durur, işaret yazılmaz.

SESVER_MOD="${SESVER_MOD:-konsol}"
BASLATICI_LOG="sesver_baslatici_log.txt"
# voxcpm kilit/voxcpm.txt'te (--no-deps ile ayrı kurulur); sürüm işarete de yazılır.
# WINDOWS_BASLAT.bat'taki VOXCPM_SURUM ile aynı tutun.
VOXCPM_SURUM="2.0.3"
KILIT_DIR="kilit"
# macOS'ta torch PyPI derlemesi (Apple Silicon, MPS) kilit/torch-pypi.txt'ten gelir.
TORCH_KILIDI="$KILIT_DIR/torch-pypi.txt"
# torch 2.14.1'in macOS tekerleği macosx_14_0_arm64: daha eski macOS'ta kurulamaz.
SESVER_MIN_MACOS=14

# kilit/*.txt dosyalarının (C sırasıyla birleştirilmiş) SHA-256 özeti. Herhangi bir
# kilit değişince özet değişir ve eşitleme çalışır. shasum yoksa $1 ile verilen
# Python'un hashlib'i denenir. Hiçbiri yoksa boş: işaret hiç eşleşmez, her
# açılışta (zararsız) eşitleme denenir.
kilit_ozeti() {
  local oz=""
  oz="$( (LC_ALL=C; cat "$KILIT_DIR"/*.txt) 2>/dev/null | shasum -a 256 2>/dev/null | awk '{print $1}')" || oz=""
  if [ -z "$oz" ] && [ -n "$1" ] && [ -x "$1" ]; then
    oz="$("$1" -c "import glob,hashlib;h=hashlib.sha256()
for f in sorted(glob.glob('$KILIT_DIR/*.txt')): h.update(open(f,'rb').read())
print(h.hexdigest())" 2>/dev/null)" || oz=""
  fi
  printf '%s' "$oz"
}

# Kurulum işaretine yazılan/karşılaştırılan tek satır. $1 = Python yolu (yedek özet için).
kurulum_isareti() {
  printf 'kilit_sha256=%s voxcpm=%s' "$(kilit_ozeti "$1")" "$VOXCPM_SURUM"
}

# $1 = Python. Bu Python sürümü için temel kilit dosyasının yolu; desteklenmeyen
# sürümde (3.10-3.12 dışı) ya da dosya yoksa boş döner ve 1 ile biter.
kilit_dosyasi() {
  local v
  v="$("$1" -c 'import sys;print("%d%d" % sys.version_info[:2])' 2>/dev/null)" || v=""
  case "$v" in
    310|311|312) ;;
    *) return 1 ;;
  esac
  [ -f "$KILIT_DIR/macos-arm64-py$v.txt" ] || return 1
  printf '%s' "$KILIT_DIR/macos-arm64-py$v.txt"
}

# Kilitli pip kurulumu. $1 = kilit dosyası, kalan = ek pip argümanları (ör. --no-deps).
#   --require-hashes          : her paket kilitteki SHA-256 ile doğrulanır
#   --only-binary=:all:       : kurulumda kaynak derleme yok ...
#   --no-binary=proxy-tools   : ... tek istisna proxy-tools (PyPI'de yalnız kaynak paketi var)
#   --no-build-isolation      : o paket hash'li kurulan setuptools ile derlenir; izole
#                               derleme ortamı pip'te hash denetimsiz indirilirdi.
# Çıktı ekrana/günlüğe akar; özet uyuşmazlığı ayrıca HASH_HATASI=1 ile işaretlenir.
HASH_HATASI=0
kilitli_kur() {
  local dosya="$1" cikti kod
  shift
  cikti="$(mktemp -t sesver_pip 2>/dev/null || echo ".sesver_pip_cikti.txt")"
  "$RUN_PY" -m pip install --require-hashes --only-binary=:all: --no-binary=proxy-tools \
    --no-build-isolation --disable-pip-version-check "$@" -r "$dosya" 2>&1 | tee "$cikti"
  kod=${PIPESTATUS[0]}
  if [ "$kod" -ne 0 ] && grep -qiE "DO NOT MATCH THE HASHES|Hashes are required|hash mismatch" "$cikti" 2>/dev/null; then
    HASH_HATASI=1
  fi
  rm -f "$cikti" 2>/dev/null || true
  return "$kod"
}

# Dört kilitli adım (ilk kurulum ve eşitleme aynı sırayı kullanır). $1/$2 = adım
# adının TR/EN eki ("kurulumu"/"installing"), $3 = temel kilit dosyası.
# Hata olursa ADIM başarısız adımı gösterir ve 1 döner (işaret yazılmaz).
paketleri_kur() {
  # pip + setuptools: --no-deps; setuptools proxy-tools derlemesi için gerekir.
  adim "pip $1 ($KILIT_DIR/pip.txt)" "pip $2"
  kilitli_kur "$KILIT_DIR/pip.txt" --no-deps || return 1
  adim "PyTorch $1 ($TORCH_KILIDI)" "PyTorch $2"
  kilitli_kur "$TORCH_KILIDI" --no-deps || return 1
  # --no-deps: voxcpm'in gereksiz ağır bağımlılıkları (funasr, matplotlib,
  # modelscope, datasets, spaces, argbind; hiçbiri kodda kullanılmıyor) kurulmaz.
  adim "voxcpm $1 ($KILIT_DIR/voxcpm.txt)" "voxcpm $2"
  kilitli_kur "$KILIT_DIR/voxcpm.txt" --no-deps || return 1
  adim "paket $1 ($3)" "packages $2 ($3)"
  kilitli_kur "$3" || return 1
}

# macOS ana sürümü (ör. 15). Enjekte edilebilir: testler yeniden tanımlar.
sesver_macos_surumu() { /usr/bin/sw_vers -productVersion 2>/dev/null || true; }

# 0 (doğru): macOS değil ya da macOS >= SESVER_MIN_MACOS.
macos_surumu_yeterli() {
  local ana
  [ "$(sesver_uname -s)" = "Darwin" ] || return 0
  ana="$(sesver_macos_surumu | cut -d. -f1)"
  case "$ana" in ''|*[!0-9]*) return 0 ;; esac
  [ "$ana" -ge "$SESVER_MIN_MACOS" ]
}

eski_macos_ve_cik() {
  echo "[HATA] SesVer macOS $SESVER_MIN_MACOS (Sonoma) ya da daha yenisini gerektirir; bu Mac: macOS $(sesver_macos_surumu). Kurulum başlatılmadı."
  bekle_ve_cik 1 "$(sesver_metin \
"SesVer macOS $SESVER_MIN_MACOS (Sonoma) ya da daha yenisini gerektirir. Bu Mac'te macOS $(sesver_macos_surumu) var. macOS'u güncelleyip SesVer'i tekrar açın." \
"SesVer requires macOS $SESVER_MIN_MACOS (Sonoma) or later. This Mac runs macOS $(sesver_macos_surumu). Update macOS and open SesVer again.")"
}

# $1 = Python komutu. Kilit yalnız 3.10-3.12 için var; hash'siz kuruluma düşülmez.
desteklenmeyen_python_ve_cik() {
  local surum
  surum="$("$1" --version 2>&1)" || surum="$1"
  echo "[HATA] $surum için SesVer paket kilidi yok (desteklenen: Python 3.10, 3.11, 3.12). Kurulum başlatılmadı."
  bekle_ve_cik 1 "$(sesver_metin \
"Bu Python sürümü ($surum) desteklenmiyor. SesVer'in kendi Python'u indirilemediği için sistemdeki Python denendi; SesVer Python 3.10, 3.11 ya da 3.12 ile kurulur.

İnternet bağlantınızı kontrol edip SesVer'i tekrar açın ya da Python 3.11 kurun: https://www.python.org/downloads/" \
"This Python version ($surum) is not supported. SesVer's own Python could not be downloaded, so the system Python was tried; SesVer installs with Python 3.10, 3.11 or 3.12.

Check your internet connection and open SesVer again, or install Python 3.11: https://www.python.org/downloads/")"
}

# --- Pencere dili (TR/EN) --------------------------------------------------
# Kullanıcıya görünen pencereler sistem dili "tr" ile başlıyorsa Türkçe, değilse
# İngilizcedir (terminal/günlük satırları Türkçe kalır). Kaynak sırası:
# SESVER_SISTEM_DILI (yalnız test; ör. en-US) → macOS AppleLanguages ilk öğesi →
# LC_ALL / LANG. sesver_apple_languages testlerde yeniden tanımlanabilir.
sesver_apple_languages() { /usr/bin/defaults read -g AppleLanguages 2>/dev/null || true; }

sesver_dil_belirle() {
  local d="${SESVER_SISTEM_DILI:-}"
  if [ -z "$d" ]; then
    # Çıktı: "(", '    "en-US",', ... ")" — ilk öğe.
    d="$(sesver_apple_languages | tr -d ' "(),' | sed -n '/./{p;q;}')"
  fi
  [ -z "$d" ] && d="${LC_ALL:-${LANG:-}}"
  case "$d" in
    tr|tr[-_.]*|TR|TR[-_.]*) SESVER_PENCERE_DILI=tr ;;
    *) SESVER_PENCERE_DILI=en ;;
  esac
}
sesver_dil_belirle

# $1 = Türkçe metin, $2 = İngilizce metin; pencere diline uygun olanı yazar.
sesver_metin() {
  if [ "$SESVER_PENCERE_DILI" = "tr" ]; then printf '%s' "$1"; else printf '%s' "$2"; fi
}

# Görsel bilgi/hata penceresi. Yalnız osascript'in kendi "display dialog"
# komutu kullanılır (başka bir uygulamaya "tell" YOK), bu yüzden macOS
# Otomasyon izni istemez. Mesaj argüman olarak verilir: tırnak/özel karakter
# AppleScript koduna karışmaz.
#   $1 = mesaj, $2 = simge (stop | caution | note), $3 = kaç sn sonra kendiliğinden kapansın (ops.)
sesver_dialog() {
  local giving_up="" ok
  [ -n "$3" ] && giving_up=" giving up after $3"
  ok="$(sesver_metin "Tamam" "OK")"
  osascript \
    -e 'on run argv' \
    -e "display dialog (item 1 of argv) with title \"SesVer\" buttons {\"$ok\"} default button 1 with icon $2$giving_up" \
    -e 'end run' "$1" >/dev/null 2>&1 || true
}

bekle_ve_cik() {
  # $1 = çıkış kodu, $2 = (app modunda) pencerede gösterilecek mesaj (pencere dilinde)
  if [ "$SESVER_MOD" = "app" ]; then
    sesver_dialog "${2:-$(sesver_metin "SesVer başlatılamadı." "SesVer could not be started.")}

$(sesver_metin "Ayrıntı" "Details"): $PWD/$BASLATICI_LOG" stop
  else
    read -n 1 -s -r -p "Çıkmak için bir tuşa basın..." || true
    echo
  fi
  exit "$1"
}

# Kurulum adımı: ADIM günlükte (Türkçe), ADIM_PENCERE hata penceresinde görünür.
ADIM=""
ADIM_PENCERE=""
adim() { ADIM="$1"; ADIM_PENCERE="$(sesver_metin "$1" "$2")"; }
kurulum_hatasi() {
  trap - ERR
  echo
  echo "[HATA] Kurulum adımı başarısız oldu: $ADIM"
  if [ "$HASH_HATASI" = "1" ]; then
    echo "İndirilen bir paketin SHA-256 özeti kilit dosyasındakiyle uyuşmuyor (bozuk indirme ya da"
    echo "değiştirilmiş paket). Güvenlik için kurulum durduruldu; hiçbir şey çalıştırılmadı."
    echo "Bir süre sonra SesVer'i tekrar açın; kurulum yeniden denenir."
    bekle_ve_cik 1 "$(sesver_metin "Kurulum adımı başarısız oldu: $ADIM_PENCERE

İndirilen bir paket doğrulanamadı (SHA-256 özeti tutmuyor). Güvenlik için kurulum durduruldu. Bir süre sonra SesVer'i tekrar açın; kurulum yeniden denenir." \
"A setup step failed: $ADIM_PENCERE

A downloaded package could not be verified (SHA-256 mismatch). Setup was stopped for your safety. Open SesVer again later; setup will be retried.")"
  fi
  echo "Yukarıdaki hata mesajını okuyun. İnternet bağlantınızı kontrol edip"
  echo "SesVer'i (SesVer.app ya da MACOS_BASLAT.command) tekrar açın; kurulum kaldığı yerden devam eder."
  echo "Sorun sürerse sesver_log.txt dosyasını hermes.agent.hamarat@gmail.com adresine gönderin."
  bekle_ve_cik 1 "$(sesver_metin "Kurulum adımı başarısız oldu: $ADIM_PENCERE

İnternet bağlantınızı kontrol edip SesVer'i tekrar açın; kurulum kaldığı yerden devam eder." \
"A setup step failed: $ADIM_PENCERE

Check your internet connection and open SesVer again; setup will continue where it left off.")"
}

# --- Intel Mac denetimi ----------------------------------------------------
# PyTorch 2.5+ (requirements.txt: torch>=2.5.0) PyPI'de macOS için yalnız arm64
# tekerleği yayınlıyor; Intel Mac'te pip adımı anlamsız bir hatayla düşer. Bu
# yüzden kurulum başlamadan, hiçbir şey indirilmeden açık bir uyarı gösterilir.
# Rosetta altında (Apple Silicon'da x86_64 olarak) çalışıyorsa uyarılmaz: makine
# arm64'tür ve arm64 Python kullanılır (bkz. sesver_mimari).
# Enjekte edilebilir: testler bu iki işlevi source ettikten sonra yeniden tanımlar.
sesver_uname() { uname "$@"; }
sesver_proc_translated() { sysctl -n sysctl.proc_translated 2>/dev/null || true; }

# Gömülü Python için gerçek makine mimarisi (Rosetta altında arm64).
sesver_mimari() {
  local m
  m="$(sesver_uname -m)"
  if [ "$m" = "x86_64" ] && [ "$(sesver_proc_translated)" = "1" ]; then m="arm64"; fi
  printf '%s' "$m"
}

# 0 (doğru): desteklenmeyen Intel Mac. Linux x86_64 etkilenmez (orada torch tekerleği var).
sesver_intel_mac_mi() {
  [ "$(sesver_uname -s)" = "Darwin" ] || return 1
  [ "$(sesver_uname -m)" = "x86_64" ] || return 1
  [ "$(sesver_proc_translated)" = "1" ] && return 1
  return 0
}

intel_mac_uyarisi_ve_cik() {
  echo "[HATA] Intel işlemcili Mac: SesVer Apple Silicon (M1 ve sonrası) gerektirir; kurulum başlatılmadı, hiçbir şey indirilmedi."
  # Terminal modunda da pencere gösterilir: ilk kurulum çoğu kullanıcı için buradan başlar.
  sesver_dialog "$(sesver_metin \
"SesVer Apple Silicon (M1 ve sonrası) gerektirir; bu Mac'te Intel işlemci var. PyTorch artık Intel Mac için paket yayınlamadığı için SesVer bu bilgisayarda kurulamaz." \
"SesVer requires Apple Silicon (M1 or later); this Mac has an Intel processor. Because PyTorch no longer publishes packages for Intel Macs, SesVer cannot be installed on this computer.")" stop
  exit 1
}

# --- Gömülü (taşınabilir) Python: python-build-standalone ------------------
# Kaynak: https://github.com/astral-sh/python-build-standalone/releases
# TEK yol: aşağıdaki sabit sürüm ve sabit SHA-256 (yayın sırasında bilinçli
# güncellenir). "En yeni sürüm" sorgusu ve aynı kaynaktan gelen SHA256SUMS yok:
# kaynak sürüm sonradan değiştirilse bile özet tutmaz, kurulum durur.
# 3.11.18+20261026: özetler bu dosyalar indirilip shasum -a 256 ile doğrulandı
# (2026-11-08) ve sürümün SHA256SUMS listesiyle aynı.
EMBED_DIR="python-embed"
EMBED_PY="$EMBED_DIR/bin/python3"
PBS_BASE="https://github.com/astral-sh/python-build-standalone/releases/download"
PBS_TAG="20261026"
PBS_VER="3.11.18"
PBS_SHA_AARCH64="cba3455e18516fbe8668cff2820c9b6a53447c552d612443c2b2fb60d390a908"
PBS_SHA_X86_64="a85474bcc78a98ca6b0070d8d615b0494b912b960239e6f18cc12d648f2dc270"

# Başarılıysa 0 döner ve python-embed/bin/python3 çalışır durumdadır;
# başarısızsa yarım kalan dosyaları temizleyip 1 döner (script durmaz,
# eski yönteme geçilir). Özet tutmazsa PBS_SHA_HATASI=1 olur ve sistem
# Python'una geçilmez (sesver_baslat açık mesajla durur). Not: "if/elif"
# koşulunda çağrıldığı için içeride set -e etkisizdir; her adım açıkça denetlenir.
PBS_SHA_HATASI=0
gomulu_python_kur() {
  local arch triple sha asset tmp got
  case "$(sesver_uname -s)" in
    Darwin) ;;
    *) echo "[BİLGİ] Gömülü Python yalnız macOS için hazır; sistem Python'u kullanılacak."; return 1 ;;
  esac
  arch="$(sesver_mimari)"
  case "$arch" in
    arm64|aarch64) triple="aarch64-apple-darwin"; sha="$PBS_SHA_AARCH64" ;;
    x86_64)        triple="x86_64-apple-darwin";  sha="$PBS_SHA_X86_64" ;;
    *) echo "[UYARI] Tanınmayan işlemci mimarisi: $arch"; return 1 ;;
  esac
  echo "Uygulamaya özel Python indiriliyor (yalnız ilk sefer, ~26 MB; mimari: $arch)..."
  asset="cpython-${PBS_VER}+${PBS_TAG}-${triple}-install_only.tar.gz"

  tmp="$EMBED_DIR.indiriliyor"
  rm -rf "$tmp" "$EMBED_DIR"
  mkdir -p "$tmp" || return 1
  echo "İndiriliyor: $asset (Python $PBS_VER, sürüm $PBS_TAG)"
  if ! curl -fL --connect-timeout 15 --retry 3 --progress-bar -o "$tmp/python.tar.gz" "$PBS_BASE/$PBS_TAG/$asset"; then
    echo "[UYARI] Python indirilemedi."
    rm -rf "$tmp"; return 1
  fi
  got="$(shasum -a 256 "$tmp/python.tar.gz" 2>/dev/null | awk '{print $1}')" || got=""
  if [ "$got" != "$sha" ]; then
    echo "[HATA] İndirilen Python dosyasının SHA-256 özeti beklenenle aynı değil."
    echo "  beklenen: $sha"
    echo "  indirilen: ${got:-hesaplanamadı}"
    PBS_SHA_HATASI=1
    rm -rf "$tmp"; return 1
  fi
  if ! tar -xzf "$tmp/python.tar.gz" -C "$tmp"; then
    echo "[UYARI] Python arşivi açılamadı."
    rm -rf "$tmp"; return 1
  fi
  if ! "$tmp/python/bin/python3" -c "import sys, ssl, ensurepip" >/dev/null 2>&1; then
    echo "[UYARI] İndirilen Python çalıştırılamadı."
    rm -rf "$tmp"; return 1
  fi
  # Yalnız tamamen doğrulanmış kopya python-embed/ adına taşınır; böylece
  # python-embed/bin/python3 varsa her zaman çalışır durumdadır.
  if ! mv "$tmp/python" "$EMBED_DIR"; then
    rm -rf "$tmp" "$EMBED_DIR"; return 1
  fi
  rm -rf "$tmp"
  # Klasörü git'in dışında tut (kök .gitignore'a dokunmadan).
  printf '*\n' > "$EMBED_DIR/.gitignore" || true
  echo "Uygulamaya özel Python hazır: $("$EMBED_PY" --version 2>&1)"
  return 0
}

sesver_baslat() {
  set -e
  # Sistemde kurulu başka bir Python'un ayarları bu ortamı bozmasın
  # (WINDOWS_BASLAT.bat ile aynı izolasyon):
  export PYTHONNOUSERSITE=1
  unset PYTHONHOME
  unset PYTHONPATH

  if [ "$SESVER_MOD" = "app" ]; then
    # Finder/Dock'tan açılan uygulamalar kısa bir PATH ve boş dil ayarıyla
    # başlar; sistem Python'unun (eski yöntem) bulunabilmesi için yaygın
    # kurulum yerleri eklenir. Konsol yok: tüm çıktı günlük dosyasına.
    export PATH="/Library/Frameworks/Python.framework/Versions/Current/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
    export LANG="${LANG:-en_US.UTF-8}"
    # SESVER_GUNLUK_EKLE=1: SesVer.app DMG modunda günlüğü kendisi başlatıp
    # payload eşitleme satırlarını yazmıştır; onların arkasına eklenir.
    if [ "${SESVER_GUNLUK_EKLE:-0}" = "1" ]; then
      exec >>"$BASLATICI_LOG" 2>&1
    else
      exec >"$BASLATICI_LOG" 2>&1
    fi
    echo "SesVer.app başlatıcı günlüğü $(date '+%Y-%m-%d %H:%M:%S') | $PWD"
  fi
  echo "[SesVer başlatıcı çalışıyor]"

  # --- Hangi Python kullanılacak? -------------------------------------------
  # 1) python-embed/ varsa onu kullan (izole, uygulamaya özel; venv gerekmez).
  # 2) Daha önce eski yöntemle TAMAMLANMIŞ bir .venv kurulumu varsa onu kullan
  #    (~2 GB paketi baştan indirmemek için).
  # 3) Yoksa uygulamaya özel Python'u indir.
  # 4) O da olmazsa eski yöntem: sistem Python'u + .venv.
  RUN_PY=""
  MARKER=""
  PY=""
  # Intel Mac: kurulum başlamadan (hiçbir şey indirilmeden) uyar ve çık. Daha önce
  # TAMAMLANMIŞ bir kurulum varsa dokunulmaz (çalışıyorsa çalışmaya devam etsin).
  if ! { [ -x "$EMBED_PY" ] && [ -f "$EMBED_DIR/sesver_kurulum_tamam.txt" ]; } \
     && ! { [ -x ".venv/bin/python" ] && [ -f ".venv/sesver_kurulum_tamam.txt" ]; } \
     && sesver_intel_mac_mi; then
    intel_mac_uyarisi_ve_cik
  fi
  if [ -x "$EMBED_PY" ] && "$EMBED_PY" --version >/dev/null 2>&1; then
    RUN_PY="$EMBED_PY"
  elif [ -x ".venv/bin/python" ] && [ -f ".venv/sesver_kurulum_tamam.txt" ]; then
    RUN_PY="./.venv/bin/python"
  else
    # İlk kurulum: hiçbir şey indirilmeden önce macOS sürümü denetlenir.
    macos_surumu_yeterli || eski_macos_ve_cik
    if [ "$SESVER_MOD" = "app" ]; then
      # Bilgi penceresi arka planda: kurulum onu beklemeden sürer.
      sesver_dialog "$(sesver_metin "SesVer ilk kez kuruluyor (Python ve paketler indiriliyor, yalnız bir kere).

Bu işlem internet hızınıza göre birkaç dakika ile yarım saat arası sürebilir. Kurulum bitince SesVer penceresi kendiliğinden açılır.

İlerleme: $PWD/$BASLATICI_LOG" \
"SesVer is being set up for the first time (downloading Python and packages, only once).

Depending on your internet speed this can take from a few minutes to half an hour. The SesVer window opens by itself when setup is finished.

Progress: $PWD/$BASLATICI_LOG")" note 120 &
    fi
    if gomulu_python_kur; then
      RUN_PY="$EMBED_PY"
    elif [ "$PBS_SHA_HATASI" = "1" ]; then
      # Özet tutmadı: sistem Python'una sessizce geçilmez, açık mesajla durulur.
      HASH_HATASI=1
      adim "Python indirme ($PBS_VER, SHA-256 doğrulaması)" "downloading Python ($PBS_VER, SHA-256 check)"
      kurulum_hatasi
    else
      echo "[BİLGİ] Sistemde kurulu Python aranıyor (eski yöntem)..."
    fi
  fi

  if [ "$RUN_PY" = "$EMBED_PY" ]; then
    MARKER="$EMBED_DIR/sesver_kurulum_tamam.txt"
    echo "Kullanılan Python: uygulamaya özel ($("$EMBED_PY" --version 2>&1))"
  elif [ "$RUN_PY" = "./.venv/bin/python" ]; then
    MARKER=".venv/sesver_kurulum_tamam.txt"
    echo "Kullanılan Python: mevcut .venv ($("$RUN_PY" --version 2>&1))"
  else
    for cand in python3.11 python3.12 python3.10 python3; do
      if command -v "$cand" >/dev/null 2>&1 && "$cand" --version >/dev/null 2>&1; then PY="$cand"; break; fi
    done
    if [ -z "$PY" ]; then
      echo "Python bulunamadı ve uygulamaya özel Python indirilemedi."
      echo "İnternet bağlantınızı kontrol edip SesVer'i tekrar açın"
      echo "ya da Python 3.10–3.12 kurun: https://www.python.org/downloads/"
      bekle_ve_cik 1 "$(sesver_metin "Python bulunamadı ve uygulamaya özel Python indirilemedi.

İnternet bağlantınızı kontrol edip SesVer'i tekrar açın ya da Python 3.10–3.12 kurun: https://www.python.org/downloads/" \
"Python was not found and SesVer's own Python could not be downloaded.

Check your internet connection and open SesVer again, or install Python 3.10–3.12: https://www.python.org/downloads/")"
    fi
    echo "Kullanılan Python komutu: $PY ($("$PY" --version 2>&1))"
    # Kilit yalnız Python 3.10-3.12 için var: başka sürümde hash'siz kuruluma
    # düşülmez, sanal ortam oluşturulmadan açık bir mesajla durulur.
    if ! "$PY" -c "import sys; sys.exit(0 if (3,10) <= sys.version_info[:2] <= (3,12) else 1)"; then
      desteklenmeyen_python_ve_cik "$PY"
    fi
    RUN_PY="./.venv/bin/python"
    MARKER=".venv/sesver_kurulum_tamam.txt"
  fi

  # Kilit dosyası: Python sürümüne göre seçilir (gömülü Python 3.11; .venv 3.10-3.12).
  local temel_kilit=""
  if [ -x "$RUN_PY" ]; then
    temel_kilit="$(kilit_dosyasi "$RUN_PY")" || temel_kilit=""
  elif [ -n "$PY" ]; then
    temel_kilit="$(kilit_dosyasi "$PY")" || temel_kilit=""
  fi

  if [ ! -x "$RUN_PY" ] || [ ! -f "$MARKER" ]; then
    echo "İlk kurulum yapılıyor (bu sadece bir kere çalışır)..."
    [ -n "$temel_kilit" ] || desteklenmeyen_python_ve_cik "${RUN_PY:-$PY}"
    macos_surumu_yeterli || eski_macos_ve_cik
    trap kurulum_hatasi ERR
    if [ ! -x "$RUN_PY" ]; then
      adim "sanal ortam oluşturma: $PY -m venv .venv" "creating the virtual environment: $PY -m venv .venv"
      "$PY" -m venv .venv
    fi
    paketleri_kur "kurulumu" "installing" "$temel_kilit" || kurulum_hatasi
    printf '%s\n' "$(kurulum_isareti "$RUN_PY")" > "$MARKER"
    trap - ERR
    echo "Kurulum tamamlandı."
  else
    # Kurulum daha önce bitmiş. SesVer güncellendiyse (bir kilit dosyası ya da
    # voxcpm sürümü değiştiyse, ya da işaret eski biçimdeyse) kilitli paketler
    # eşitlenir: sürümü zaten tutan pakete dokunulmaz, ortam baştan kurulmaz.
    local isaret_simdi isaret_beklenen
    isaret_simdi="$(head -n 1 "$MARKER" 2>/dev/null | tr -d '\r')" || isaret_simdi=""
    isaret_beklenen="$(kurulum_isareti "$RUN_PY")"
    if [ "$isaret_simdi" != "$isaret_beklenen" ]; then
      if [ -z "$temel_kilit" ] || ! macos_surumu_yeterli; then
        # Çalışan eski kurulum bozulmasın: hiçbir şey indirilmez/kurulmaz, işaret
        # değişmez, SesVer mevcut paketlerle açılır.
        echo "[UYARI] Bu ortam için paket kilidi yok (Python: $("$RUN_PY" --version 2>&1), macOS: $(sesver_macos_surumu))."
        echo "[UYARI] Paket eşitlemesi atlandı; SesVer mevcut paketlerle açılıyor. Güncel paketler için"
        echo "        SesVer'i README'deki yoldan yeniden kurun (macOS 14+ ve SesVer'in kendi Python'u)."
      else
        echo "SesVer güncellenmiş: paketler eşitleniyor (yalnız eksik/değişen paketler kurulur)..."
        if [ "$SESVER_MOD" = "app" ]; then
          sesver_dialog "$(sesver_metin "SesVer güncellendi; gerekli paketler denetleniyor. Genelde kısa sürer; yeni paket varsa internet hızınıza göre uzayabilir. Bitince SesVer kendiliğinden açılır.

İlerleme: $PWD/$BASLATICI_LOG" \
"SesVer was updated; checking the required packages. This is usually quick; if there are new packages it may take longer depending on your connection. SesVer opens by itself when done.

Progress: $PWD/$BASLATICI_LOG")" note 20 &
        fi
        trap kurulum_hatasi ERR
        paketleri_kur "eşitleme" "updating" "$temel_kilit" || kurulum_hatasi
        printf '%s\n' "$isaret_beklenen" > "$MARKER"
        trap - ERR
        echo "Paket eşitleme tamamlandı."
      fi
    fi
  fi

  if [ "$SESVER_MOD" = "app" ]; then
    echo "SesVer açılıyor: $RUN_PY desktop.py"
    # Uygulama ayrıntıları desktop.py tarafından sesver_log.txt'ye yazılır.
    # Pencere kapatılınca desktop.py 0 ile çıkar; başka bir kodla biterse
    # (ör. içe aktarma hatası) kullanıcı bunu bir pencerede görür.
    set +e
    # CFProcessPath: CoreFoundation ana bundle'ı bu yoldan belirler; böylece
    # pencere süreci LaunchServices/Dock'ta "Python" değil SesVer.app olarak
    # görünür (Dock'a sabitlenen ikonla eşleşir). Python ikilisi değişmez.
    CFProcessPath="$SESVER_APP_EXE" "$RUN_PY" desktop.py
    local kod=$?
    if [ "$kod" -ne 0 ]; then
      echo "[HATA] desktop.py $kod koduyla bitti."
      echo "Sorun sürerse sesver_log.txt dosyasını hermes.agent.hamarat@gmail.com adresine gönderin."
      # Bilinen bir engel (ör. Windows Akıllı Uygulama Denetimi; bkz. AI_KURULUM.md #13)
      # log'da görünüyorsa genel ileti yerine adım adım rehber gösterilir.
      local rehber
      rehber="$("$RUN_PY" hata_rehberi.py sesver_log.txt 2>/dev/null)" || rehber=""
      if [ -n "$rehber" ]; then
        echo "$rehber"
        sesver_dialog "$(sesver_metin "SesVer başlatılamadı." "SesVer could not be started.")

$rehber

$(sesver_metin "Ayrıntı" "Details"): $PWD/sesver_log.txt" stop
      else
        sesver_dialog "$(sesver_metin "SesVer beklenmedik şekilde kapandı (çıkış kodu $kod)." \
"SesVer quit unexpectedly (exit code $kod).")

$(sesver_metin "Ayrıntı" "Details"): $PWD/sesver_log.txt" stop
      fi
    fi
    exit "$kod"
  fi
  echo "SesVer açılıyor, birkaç saniye sürebilir. Bir pencere açılmazsa tarayıcınızda http://127.0.0.1:${GRADIO_SERVER_PORT:-7860} adresini deneyin (port doluysa aşağıda yazılan adresi)."
  echo "Durdurmak için bu pencerede Ctrl+C kullanın."
  "$RUN_PY" desktop.py
}
