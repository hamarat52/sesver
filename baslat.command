#!/bin/bash
# SesVer başlatıcı — macOS / Linux. Çift tıklayın veya terminalde çalıştırın.
# İlk çalıştırmada ortamı kurar; sonrakilerde doğrudan açar.
set -e
cd "$(dirname "$0")"

PY=""
for cand in python3.11 python3.12 python3.10 python3; do
  if command -v "$cand" >/dev/null 2>&1; then PY="$cand"; break; fi
done
if [ -z "$PY" ]; then
  echo "Python bulunamadı. Lütfen Python 3.10–3.12 kurun: https://www.python.org/downloads/"
  read -n 1 -s -r -p "Çıkmak için bir tuşa basın..."
  exit 1
fi

if [ ! -d ".venv" ]; then
  echo "İlk kurulum yapılıyor (bu sadece bir kere çalışır)..."
  "$PY" -m venv .venv
  ./.venv/bin/python -m pip install --upgrade pip --quiet
  # --no-deps: voxcpm'in gereksiz ağır bağımlılıklarını (funasr, matplotlib,
  # modelscope, datasets, spaces, argbind — hiçbiri kodda kullanılmıyor)
  # atlayıp yalnız requirements.txt'teki gerçekten gerekli paketleri kurar.
  ./.venv/bin/pip install --no-deps voxcpm==2.0.3
  ./.venv/bin/pip install -r requirements.txt
  echo "Kurulum tamamlandı."
fi

echo "SesVer başlatılıyor... Tarayıcınızda http://127.0.0.1:7860 açılacak."
echo "Durdurmak için bu pencerede Ctrl+C kullanın."
./.venv/bin/python app.py
