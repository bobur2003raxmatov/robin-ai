# 🚀 ROBIN — doimiy hosting va `git push` orqali avto-yangilanish

Sxema: **kompyuter → `git push` → GitHub → webhook → server `/api/deploy/webhook` → `git pull` → `pip install` → restart**

## 1. GitHub repo
```bash
git remote add origin https://github.com/<login>/robin-ai.git
git push -u origin main
```
`.env`, `database/`, `.venv/` git'ga tushmaydi (`.gitignore`).

## 2. Server (Ubuntu VPS) — variant A: systemd
```bash
git clone https://github.com/<login>/robin-ai.git /opt/robin && cd /opt/robin
bash deploy/install.sh          # venv, kutubxonalar, .env, systemd xizmati
nano .env                       # SECRET_KEY, DEPLOY_WEBHOOK_SECRET, HOST=0.0.0.0, DEPLOY_RESTART=true
sudo systemctl restart robin
```
HTTPS uchun Caddy (eng oson): `deploy/Caddyfile` ichidagi domenni almashtiring → `sudo caddy run --config deploy/Caddyfile`.

## 2. Server — variant B: Docker
```bash
git clone https://github.com/<login>/robin-ai.git && cd robin-ai
cp .env.example .env && nano .env
docker compose up -d --build
```
Docker'da `DEPLOY_RESTART=true` — konteyner `restart: always` bilan qayta turadi.

## 3. Webhook
GitHub → repo → **Settings → Webhooks → Add webhook**
- Payload URL: `https://<domen>/api/deploy/webhook`
- Content type: `application/json`
- Secret: serverdagi `DEPLOY_WEBHOOK_SECRET` bilan bir xil
- Events: *Just the push event*

Tekshirish: Admin panel → 🚀 Hosting (oxirgi deploy logi), yoki GitHub webhook sahifasidagi "Recent deliveries".

## Eslatmalar
- Kompyuterni boshqarish (sichqoncha, ekran) serverda emas — desktop agent (`desktop/robin_agent.py`) orqali ishlaydi.
- Claude Code menyusi serverda ishlashi uchun u yerda ham `claude` CLI o'rnatilgan va login qilingan bo'lishi kerak
  (`npm i -g @anthropic-ai/claude-code && claude login`).
