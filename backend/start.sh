#!/bin/sh
# AYAZ backend container başlangıcı: migrasyon → (opsiyonel) demo seed → servis.
#
# Bu script, Dockerfile CMD'si olarak çalışır. Render free tier'da Pre-Deploy
# Command olmadığı için migrasyonlar burada (servis başlarken) uygulanır.
# Tüm adımlar idempotenttir; tekrar tekrar çalışması güvenlidir.
#
# Neden render.yaml'daki dockerCommand yerine script: Render dockerCommand
# string'ini "&&" içeren tek bir komut adı gibi yorumlayıp "not found"
# (exit 127) veriyordu. Bir shell script bu sorunu kökten çözer.
set -e

echo "[start] alembic upgrade head..."
alembic upgrade head

echo "[start] demo seed (SEED_DEMO=${SEED_DEMO:-unset})..."
python -m scripts.seed_if_enabled

echo "[start] uvicorn başlatılıyor (port ${PORT:-8000})..."
exec uvicorn ayaz.main:app --host 0.0.0.0 --port "${PORT:-8000}"
