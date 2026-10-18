#!/bin/bash
# SesVer başlatıcı — macOS / Linux. Çift tıklayın veya terminalde çalıştırın.
# İlk çalıştırmada ortamı kurar; sonrakilerde doğrudan açar.
# Kurulum yarıda kalırsa (internet kesildi, pencere kapandı) bir sonraki
# çalıştırmada kaldığı yerden devam eder: .venv/sesver_kurulum_tamam.txt
# yalnız tüm kurulum adımları başarıyla bitince yazılır.
set -e
cd "$(dirname "$0")"
echo "[SesVer başlatıcı çalışıyor]"

bekle_ve_cik() {
  read -n 1 -s -r -p "Çıkmak için bir tuşa basın..." || true
  echo
  exit "$1"
}

ADIM=""
kurulum_hatasi() {
  echo
  echo "[HATA] Kurulum adımı başarısız oldu: $ADIM"
  echo "Yukarıdaki hata mesajını okuyun. İnternet bağlantınızı kontrol edip"
  echo "MACOS_BASLAT.command dosyasını tekrar çalıştırın; kurulum kaldığı yerden devam eder."
  bekle_ve_cik 1
}

PY=""
for cand in python3.11 python3.12 python3.10 python3; do
  if command -v "$cand" >/dev/null 2>&1 && "$cand" --version >/dev/null 2>&1; then PY="$cand"; break; fi
done
if [ -z "$PY" ]; then
  echo "Python bulunamadı. Lütfen Python 3.10–3.12 kurun: https://www.python.org/downloads/"
  bekle_ve_cik 1
fi
echo "Kullanılan Python komutu: $PY ($("$PY" --version 2>&1))"
"$PY" -c "import sys; sys.exit(0 if (3,10) <= sys.version_info[:2] <= (3,12) else 1)" \
  || echo "[UYARI] Önerilen sürüm Python 3.10–3.12; kurulum başarısız olabilir."

if [ ! -x ".venv/bin/python" ] || [ ! -f ".venv/sesver_kurulum_tamam.txt" ]; then
  echo "İlk kurulum yapılıyor (bu sadece bir kere çalışır)..."
  trap kurulum_hatasi ERR
  if [ ! -x ".venv/bin/python" ]; then
    ADIM="sanal ortam oluşturma: $PY -m venv .venv"
    "$PY" -m venv .venv
  fi
  ADIM="pip güncelleme"
  ./.venv/bin/python -m pip install --upgrade pip --quiet
  # --no-deps: voxcpm'in gereksiz ağır bağımlılıklarını (funasr, matplotlib,
  # modelscope, datasets, spaces, argbind — hiçbiri kodda kullanılmıyor)
  # atlayıp yalnız requirements.txt'teki gerçekten gerekli paketleri kurar.
  ADIM="voxcpm kurulumu"
  ./.venv/bin/python -m pip install --no-deps voxcpm==2.0.3
  ADIM="requirements.txt kurulumu"
  ./.venv/bin/python -m pip install -r requirements.txt
  echo tamam > .venv/sesver_kurulum_tamam.txt
  trap - ERR
  echo "Kurulum tamamlandı."
fi

echo "SesVer başlatılıyor... Tarayıcınızda http://127.0.0.1:${GRADIO_SERVER_PORT:-7860} adresini açın."
echo "Durdurmak için bu pencerede Ctrl+C kullanın."
./.venv/bin/python app.py
