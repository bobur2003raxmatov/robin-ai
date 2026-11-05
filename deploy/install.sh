#!/usr/bin/env bash
# ROBIN — Linux server o'rnatuvchisi (Ubuntu/Debian). Repo papkasida ishga tushiring: bash deploy/install.sh
set -euo pipefail
cd "$(dirname "$0")/.."
DIR="$(pwd)"
USER_NAME="${SUDO_USER:-$USER}"

sudo apt-get update -y
sudo apt-get install -y python3 python3-venv python3-pip git ffmpeg

python3 -m venv .venv
.venv/bin/pip install -U pip
# Server uchun: desktop (pyautogui, pywebview) kutubxonalari shart emas, xato bersa o'tkazib yuboriladi
grep -vE '^(pyautogui|pynput|pywebview|playwright)' requirements.txt > /tmp/robin-req.txt
.venv/bin/pip install -r /tmp/robin-req.txt

if [ ! -f .env ]; then
  cp .env.example .env
  sed -i "s/^SECRET_KEY=.*/SECRET_KEY=$(openssl rand -hex 32)/" .env
  sed -i "s/^HOST=.*/HOST=0.0.0.0/" .env
  sed -i "s/^DEPLOY_WEBHOOK_SECRET=.*/DEPLOY_WEBHOOK_SECRET=$(openssl rand -hex 24)/" .env
  sed -i "s/^DEPLOY_RESTART=.*/DEPLOY_RESTART=true/" .env
  sed -i "s/^LOCAL_EXECUTION=.*/LOCAL_EXECUTION=false/" .env
  echo ">>> .env yaratildi. Webhook secret: $(grep ^DEPLOY_WEBHOOK_SECRET .env | cut -d= -f2)"
fi

sed -e "s#__DIR__#$DIR#g" -e "s#__USER__#$USER_NAME#g" deploy/robin.service | sudo tee /etc/systemd/system/robin.service >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable --now robin
echo ">>> ROBIN ishga tushdi: http://<server-ip>:8000  (holat: sudo systemctl status robin)"
