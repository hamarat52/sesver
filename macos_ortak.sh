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
#   req_sha256=<requirements.txt'nin SHA-256 özeti> voxcpm=<voxcpm sürümü>
# Her açılışta beklenen satırla karşılaştırılır:
#   - işaret yok                      -> tam ilk kurulum (aşağıdaki akış)
#   - aynı                            -> kurulum adımı tamamen atlanır
#   - farklı ya da eski biçim "tamam" -> yalnız eşitleme: pip install -r
#     requirements.txt (+ voxcpm pini değiştiyse/bilinmiyorsa voxcpm) ve işaret
#     yeni satırla yazılır. Ortam silinmez, baştan kurulmaz.
# Eşitleme başarısız olursa işaret ESKİ hâliyle kalır (bir sonraki açılışta
# yeniden denenir) ve ilk kurulumdaki hata yolu gösterilir.

SESVER_MOD="${SESVER_MOD:-konsol}"
BASLATICI_LOG="sesver_baslatici_log.txt"
# voxcpm requirements.txt'te değil (--no-deps ile ayrı kurulur); pini burada.
# WINDOWS_BASLAT.bat'taki VOXCPM_SURUM ile aynı tutun.
VOXCPM_SURUM="2.0.3"

# requirements.txt'nin SHA-256 özeti (macOS'ta her zaman bulunan shasum).
# shasum yoksa $1 ile verilen Python'un hashlib'i denenir. Hiçbiri yoksa boş:
# işaret hiç eşleşmez, her açılışta (zararsız) eşitleme denenir.
requirements_ozeti() {
  local oz=""
  oz="$(shasum -a 256 requirements.txt 2>/dev/null | awk '{print $1}')" || oz=""
  if [ -z "$oz" ] && [ -n "$1" ] && [ -x "$1" ]; then
    oz="$("$1" -c "import hashlib;print(hashlib.sha256(open('requirements.txt','rb').read()).hexdigest())" 2>/dev/null)" || oz=""
  fi
  printf '%s' "$oz"
}

# Kurulum işaretine yazılan/karşılaştırılan tek satır. $1 = Python yolu (yedek özet için).
kurulum_isareti() {
  printf 'req_sha256=%s voxcpm=%s' "$(requirements_ozeti "$1")" "$VOXCPM_SURUM"
}

# Görsel bilgi/hata penceresi. Yalnız osascript'in kendi "display dialog"
# komutu kullanılır (başka bir uygulamaya "tell" YOK), bu yüzden macOS
# Otomasyon izni istemez. Mesaj argüman olarak verilir: tırnak/özel karakter
# AppleScript koduna karışmaz.
#   $1 = mesaj, $2 = simge (stop | caution | note), $3 = kaç sn sonra kendiliğinden kapansın (ops.)
sesver_dialog() {
  local giving_up=""
  [ -n "$3" ] && giving_up=" giving up after $3"
  osascript \
    -e 'on run argv' \
    -e "display dialog (item 1 of argv) with title \"SesVer\" buttons {\"Tamam\"} default button 1 with icon $2$giving_up" \
    -e 'end run' "$1" >/dev/null 2>&1 || true
}

bekle_ve_cik() {
  # $1 = çıkış kodu, $2 = (app modunda) pencerede gösterilecek mesaj
  if [ "$SESVER_MOD" = "app" ]; then
    sesver_dialog "${2:-SesVer başlatılamadı.}

Ayrıntı: $PWD/$BASLATICI_LOG" stop
  else
    read -n 1 -s -r -p "Çıkmak için bir tuşa basın..." || true
    echo
  fi
  exit "$1"
}

ADIM=""
kurulum_hatasi() {
  echo
  echo "[HATA] Kurulum adımı başarısız oldu: $ADIM"
  echo "Yukarıdaki hata mesajını okuyun. İnternet bağlantınızı kontrol edip"
  echo "SesVer'i (SesVer.app ya da MACOS_BASLAT.command) tekrar açın; kurulum kaldığı yerden devam eder."
  bekle_ve_cik 1 "Kurulum adımı başarısız oldu: $ADIM

İnternet bağlantınızı kontrol edip SesVer'i tekrar açın; kurulum kaldığı yerden devam eder."
}

# --- Gömülü (taşınabilir) Python: python-build-standalone ------------------
# Kaynak: https://github.com/astral-sh/python-build-standalone/releases
# Güncel sürüm etiketi latest-release.json'dan, dosya adı ve SHA-256 özeti
# o sürümün SHA256SUMS dosyasından okunur. Bunlar alınamazsa aşağıdaki
# doğrulanmış sabit sürüm kullanılır.
EMBED_DIR="python-embed"
EMBED_PY="$EMBED_DIR/bin/python3"
PBS_BASE="https://github.com/astral-sh/python-build-standalone/releases/download"
PBS_LATEST_JSON="https://raw.githubusercontent.com/astral-sh/python-build-standalone/latest-release/latest-release.json"
PBS_PY_SERIES="3\\.11"
PBS_FALLBACK_TAG="20261013"
PBS_FALLBACK_VER="3.11.17"
PBS_FALLBACK_SHA_AARCH64="d81d757a9785850393cd695a9a686c765a6370fbdc83738589ef2ecd3e5c44b3"
PBS_FALLBACK_SHA_X86_64="3acde87324867dab4e63329be3010130c75bfc4a3709db00866862d750a3bba3"

# Başarılıysa 0 döner ve python-embed/bin/python3 çalışır durumdadır;
# başarısızsa yarım kalan dosyaları temizleyip 1 döner (script durmaz,
# eski yönteme geçilir). Not: "if/elif" koşulunda çağrıldığı için içeride
# set -e etkisizdir; her adım bu yüzden açıkça denetlenir.
gomulu_python_kur() {
  local arch triple fb_sha tag sums line asset sha tmp got
  case "$(uname -s)" in
    Darwin) ;;
    *) echo "[BİLGİ] Gömülü Python yalnız macOS için hazır; sistem Python'u kullanılacak."; return 1 ;;
  esac
  arch="$(uname -m)"
  case "$arch" in
    arm64|aarch64) triple="aarch64-apple-darwin"; fb_sha="$PBS_FALLBACK_SHA_AARCH64" ;;
    x86_64)        triple="x86_64-apple-darwin";  fb_sha="$PBS_FALLBACK_SHA_X86_64" ;;
    *) echo "[UYARI] Tanınmayan işlemci mimarisi: $arch"; return 1 ;;
  esac
  echo "Uygulamaya özel Python indiriliyor (yalnız ilk sefer, ~26 MB; mimari: $arch)..."

  tag="$(curl -fsSL --connect-timeout 15 --max-time 30 "$PBS_LATEST_JSON" 2>/dev/null \
         | sed -n 's/.*"tag"[[:space:]]*:[[:space:]]*"\([0-9][0-9]*\)".*/\1/p' | head -n 1)" || tag=""
  asset=""; sha=""
  if [ -n "$tag" ]; then
    sums="$(curl -fsSL --connect-timeout 15 --max-time 60 "$PBS_BASE/$tag/SHA256SUMS" 2>/dev/null)" || sums=""
    line="$(printf '%s\n' "$sums" \
            | grep -E "^[0-9a-f]{64}  cpython-${PBS_PY_SERIES}\.[0-9]+\+${tag}-${triple}-install_only\.tar\.gz$" \
            | head -n 1)" || line=""
    if [ -n "$line" ]; then
      sha="${line%% *}"
      asset="${line##* }"
    fi
  fi
  if [ -z "$asset" ]; then
    echo "[BİLGİ] Güncel sürüm bilgisi alınamadı; doğrulanmış sabit sürüm kullanılıyor ($PBS_FALLBACK_VER)."
    tag="$PBS_FALLBACK_TAG"
    asset="cpython-${PBS_FALLBACK_VER}+${PBS_FALLBACK_TAG}-${triple}-install_only.tar.gz"
    sha="$fb_sha"
  fi

  tmp="$EMBED_DIR.indiriliyor"
  rm -rf "$tmp" "$EMBED_DIR"
  mkdir -p "$tmp" || return 1
  echo "İndiriliyor: $asset"
  if ! curl -fL --connect-timeout 15 --retry 3 --progress-bar -o "$tmp/python.tar.gz" "$PBS_BASE/$tag/$asset"; then
    echo "[UYARI] Python indirilemedi."
    rm -rf "$tmp"; return 1
  fi
  got="$(shasum -a 256 "$tmp/python.tar.gz" 2>/dev/null | awk '{print $1}')" || got=""
  if [ "$got" != "$sha" ]; then
    echo "[UYARI] İndirilen dosyanın SHA-256 özeti tutmuyor (bozuk ya da eksik indirme)."
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
    exec >"$BASLATICI_LOG" 2>&1
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
  if [ -x "$EMBED_PY" ] && "$EMBED_PY" --version >/dev/null 2>&1; then
    RUN_PY="$EMBED_PY"
  elif [ -x ".venv/bin/python" ] && [ -f ".venv/sesver_kurulum_tamam.txt" ]; then
    RUN_PY="./.venv/bin/python"
  else
    if [ "$SESVER_MOD" = "app" ]; then
      # Bilgi penceresi arka planda: kurulum onu beklemeden sürer.
      sesver_dialog "SesVer ilk kez kuruluyor (Python ve paketler indiriliyor, yalnız bir kere).

Bu işlem internet hızınıza göre birkaç dakika ile yarım saat arası sürebilir. Kurulum bitince SesVer penceresi kendiliğinden açılır.

İlerleme: $PWD/$BASLATICI_LOG" note 120 &
    fi
    if gomulu_python_kur; then
      RUN_PY="$EMBED_PY"
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
      bekle_ve_cik 1 "Python bulunamadı ve uygulamaya özel Python indirilemedi.

İnternet bağlantınızı kontrol edip SesVer'i tekrar açın ya da Python 3.10–3.12 kurun: https://www.python.org/downloads/"
    fi
    echo "Kullanılan Python komutu: $PY ($("$PY" --version 2>&1))"
    "$PY" -c "import sys; sys.exit(0 if (3,10) <= sys.version_info[:2] <= (3,12) else 1)" \
      || echo "[UYARI] Önerilen sürüm Python 3.10–3.12; kurulum başarısız olabilir."
    RUN_PY="./.venv/bin/python"
    MARKER=".venv/sesver_kurulum_tamam.txt"
  fi

  if [ ! -x "$RUN_PY" ] || [ ! -f "$MARKER" ]; then
    echo "İlk kurulum yapılıyor (bu sadece bir kere çalışır)..."
    trap kurulum_hatasi ERR
    if [ ! -x "$RUN_PY" ]; then
      ADIM="sanal ortam oluşturma: $PY -m venv .venv"
      "$PY" -m venv .venv
    fi
    ADIM="pip güncelleme"
    "$RUN_PY" -m pip install --upgrade pip --quiet
    # --no-deps: voxcpm'in gereksiz ağır bağımlılıklarını (funasr, matplotlib,
    # modelscope, datasets, spaces, argbind — hiçbiri kodda kullanılmıyor)
    # atlayıp yalnız requirements.txt'teki gerçekten gerekli paketleri kurar.
    ADIM="voxcpm kurulumu"
    "$RUN_PY" -m pip install --no-deps "voxcpm==$VOXCPM_SURUM"
    ADIM="requirements.txt kurulumu"
    "$RUN_PY" -m pip install -r requirements.txt
    printf '%s\n' "$(kurulum_isareti "$RUN_PY")" > "$MARKER"
    trap - ERR
    echo "Kurulum tamamlandı."
  else
    # Kurulum daha önce bitmiş. SesVer güncellendiyse (requirements.txt ya da
    # voxcpm pini değiştiyse, ya da işaret eski "tamam" biçimindeyse) yalnız
    # eksik/değişen paketler kurulur; ortam baştan kurulmaz.
    local isaret_simdi isaret_beklenen
    isaret_simdi="$(head -n 1 "$MARKER" 2>/dev/null | tr -d '\r')" || isaret_simdi=""
    isaret_beklenen="$(kurulum_isareti "$RUN_PY")"
    if [ "$isaret_simdi" != "$isaret_beklenen" ]; then
      echo "SesVer güncellenmiş: paketler eşitleniyor (yalnız eksik/değişen paketler kurulur)..."
      if [ "$SESVER_MOD" = "app" ]; then
        sesver_dialog "SesVer güncellendi; gerekli paketler denetleniyor. Genelde kısa sürer; yeni paket varsa internet hızınıza göre uzayabilir. Bitince SesVer kendiliğinden açılır.

İlerleme: $PWD/$BASLATICI_LOG" note 20 &
      fi
      trap kurulum_hatasi ERR
      case " $isaret_simdi " in
        *" voxcpm=$VOXCPM_SURUM "*) ;;
        *)
          ADIM="voxcpm eşitleme"
          "$RUN_PY" -m pip install --no-deps "voxcpm==$VOXCPM_SURUM"
          ;;
      esac
      ADIM="requirements.txt eşitleme"
      # --upgrade YOK: gereksinimi zaten karşılayan paketlere (ör. kurulu torch) dokunulmaz.
      "$RUN_PY" -m pip install -r requirements.txt
      printf '%s\n' "$isaret_beklenen" > "$MARKER"
      trap - ERR
      echo "Paket eşitleme tamamlandı."
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
      # Bilinen bir engel (ör. Windows Akıllı Uygulama Denetimi; bkz. AI_KURULUM.md #13)
      # log'da görünüyorsa genel ileti yerine adım adım rehber gösterilir.
      local rehber
      rehber="$("$RUN_PY" hata_rehberi.py sesver_log.txt 2>/dev/null)" || rehber=""
      if [ -n "$rehber" ]; then
        echo "$rehber"
        sesver_dialog "SesVer başlatılamadı.

$rehber

Ayrıntı: $PWD/sesver_log.txt" stop
      else
        sesver_dialog "SesVer beklenmedik şekilde kapandı (çıkış kodu $kod).

Ayrıntı: $PWD/sesver_log.txt" stop
      fi
    fi
    exit "$kod"
  fi
  echo "SesVer açılıyor, birkaç saniye sürebilir. Bir pencere açılmazsa tarayıcınızda http://127.0.0.1:${GRADIO_SERVER_PORT:-7860} adresini deneyin (port doluysa aşağıda yazılan adresi)."
  echo "Durdurmak için bu pencerede Ctrl+C kullanın."
  "$RUN_PY" desktop.py
}
