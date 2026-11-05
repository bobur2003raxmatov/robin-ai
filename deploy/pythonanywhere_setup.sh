#!/usr/bin/env bash
# ROBIN → PythonAnywhere (ASGI / FastAPI). PythonAnywhere "Bash console" ichida ishga tushiring:
#
#   git clone https://<GITHUB_TOKEN>@github.com/<login>/<repo>.git ~/robin
#   bash ~/robin/deploy/pythonanywhere_setup.sh
#
# EU hisob (eu.pythonanywhere.com) bo'lsa:  PA_HOST=eu.pythonanywhere.com bash ~/robin/deploy/pythonanywhere_setup.sh
# Qayta ishga tushirish xavfsiz: .env va baza saqlanib qoladi.
set -euo pipefail
cd "$(dirname "$0")/.."
DIR="$(pwd)"
U="$(whoami)"
PA_HOST="${PA_HOST:-www.pythonanywhere.com}"
if [ "$PA_HOST" = "eu.pythonanywhere.com" ]; then DEF_DOMAIN="$U.eu.pythonanywhere.com"; else DEF_DOMAIN="$U.pythonanywhere.com"; fi
DOMAIN="${PA_DOMAIN:-$DEF_DOMAIN}"

echo ">>> 1/4 Python muhiti ($DIR/.venv)"
PY=""
for v in 3.12 3.13 3.11 3.10; do if command -v "python$v" >/dev/null; then PY="python$v"; break; fi; done
[ -n "$PY" ] || { echo "Python 3.10+ topilmadi"; exit 1; }
[ -x .venv/bin/python ] || "$PY" -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements-server.txt pythonanywhere
du -sh "$HOME" 2>/dev/null | awk '{print "    disk: "$1" (free tarif limiti 512M)"}'

echo ">>> 2/4 .env"
if [ ! -f .env ]; then
  cp .env.example .env
  set_env() { if grep -q "^$1=" .env; then sed -i "s#^$1=.*#$1=$2#" .env; else echo "$1=$2" >> .env; fi; }
  set_env SECRET_KEY "$(openssl rand -hex 32)"
  set_env HOST 127.0.0.1
  set_env LOCAL_EXECUTION false
  set_env DEPLOY_WEBHOOK_SECRET "$(openssl rand -hex 24)"
  set_env DEPLOY_RESTART true
  set_env DEPLOY_REQUIREMENTS requirements-server.txt
  set_env DEPLOY_BRANCH main
  set_env PA_USERNAME "$U"
  set_env PA_DOMAIN "$DOMAIN"
  set_env PA_HOST "$PA_HOST"
  set_env PA_API_TOKEN "${API_TOKEN:-}"
  echo "    .env yaratildi"
else
  echo "    .env mavjud — o'zgartirilmadi"
fi
grep -q "^PA_API_TOKEN=." .env || echo "    ⚠️  PA_API_TOKEN bo'sh: Account → API token → Create, keyin .env ga yozing (avto-reload uchun)"

echo ">>> 3/4 git (webhook 'git pull' uchun)"
git config pull.ff only
git config credential.helper store

echo ">>> 4/4 Veb-sayt: https://$DOMAIN"
export API_TOKEN="${API_TOKEN:-$(grep '^PA_API_TOKEN=' .env | cut -d= -f2)}"
if [ -z "$API_TOKEN" ]; then
  echo "    API token yo'q. Account → API token → Create, so'ng skriptni qayta ishga tushiring."; exit 1
fi
CMD="$DIR/.venv/bin/uvicorn --app-dir $DIR --uds \${DOMAIN_SOCKET} backend.main:app"
if .venv/bin/pa website get --domain "$DOMAIN" >/dev/null 2>&1; then
  .venv/bin/pa website reload --domain "$DOMAIN"
else
  .venv/bin/pa website create --domain "$DOMAIN" --command "$CMD"
fi

SECRET="$(grep '^DEPLOY_WEBHOOK_SECRET=' .env | cut -d= -f2)"
cat <<EOF

✅ ROBIN ishga tushdi:  https://$DOMAIN
   Birinchi ro'yxatdan o'tgan foydalanuvchi — admin.

GitHub → repo → Settings → Webhooks → Add webhook:
   Payload URL:   https://$DOMAIN/api/deploy/webhook
   Content type:  application/json
   Secret:        $SECRET
   Events:        Just the push event
Shundan keyin har bir 'git push' → server o'zi yangilanadi.
EOF
