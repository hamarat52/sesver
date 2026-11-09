#!/bin/bash
# macos_ortak.sh kurulum/eşitleme senaryoları (elle çalıştırma kısayolu).
# 1.3.1'den beri paketler kilit/ dosyalarından pip --require-hashes ile kurulduğu için
# senaryolar sahte pip yerine GERÇEK pip ve ağsız sahte tekerleklerle tests/test_kilit.py
# içinde koşar: ilk kurulum, SHA-256 uyuşmazlığında durma ve işaretin yazılmaması,
# sonraki açılışta yeniden deneme, 1.3.0 biçimli işaretten eşitleme, eşitleme hatasında
# işaretin eski hâliyle kalması, CUDA kısıtının (-c) kilitle birlikte çalışması.
# Kullanım: bash tests/macos_senaryolari.sh   (projenin .venv'i ya da PATH'teki python3 ile)
set -u
KOK="$(cd "$(dirname "$0")/.." && pwd)"
PY="$KOK/.venv/bin/python"
[ -x "$PY" ] || PY="python3"
cd "$KOK" && exec "$PY" -m pytest -q tests/test_kilit.py -k "Macos or GercekPip"
