# 🐍 ROBIN → PythonAnywhere

Sxema: **kompyuter `git push` → GitHub → webhook → `https://<login>.pythonanywhere.com/api/deploy/webhook` → `git pull` → (kerak bo'lsa `pip install`) → PythonAnywhere API orqali sayt qayta yuklanadi.**

## 1. GitHub
1. github.com → **New repository** → nom: `robin-ai`, **Private**, README qo'shmang.
2. Kompyuterda (Claude bajaradi): `git remote add origin … && git push -u origin main`.
3. Server repo'ni o'qishi uchun token: GitHub → Settings → Developer settings → **Fine-grained tokens** →
   faqat `robin-ai` repo, **Contents: Read-only** → Generate. Tokenni nusxalang.

## 2. PythonAnywhere
1. pythonanywhere.com da hisob oching (yoki kiring).
2. **Account → API token → Create a new API token.**
3. Agar **Web** bo'limida eski sayt bo'lsa (free tarifda 1 ta sayt), uni o'chiring.
4. **Consoles → Bash** ni oching va yozing (`<TOKEN>`, `<login>` ni almashtiring):
   ```bash
   git clone https://<TOKEN>@github.com/<login>/robin-ai.git ~/robin
   bash ~/robin/deploy/pythonanywhere_setup.sh
   ```
   EU hisob bo'lsa: `PA_HOST=eu.pythonanywhere.com bash ~/robin/deploy/pythonanywhere_setup.sh`
5. Skript oxirida chiqqan **Webhook URL va Secret** ni GitHub → repo → Settings → Webhooks ga kiriting.
6. `https://<login>.pythonanywhere.com` ni oching → ro'yxatdan o'ting (birinchi foydalanuvchi = admin)
   → Brain sahifasida AI kalitlarini kiriting.

## Cheklovlar (bepul tarif)
- Faqat ruxsat etilgan saytlarga chiqish: Gemini, Groq, Mistral, OpenRouter, OpenAI, Anthropic, Telegram,
  Binance, Cloudflare — ro'yxatda bor ✅. Edge TTS ovozi proxy sabab ishlamasligi mumkin → brauzer ovozi ishlatiladi.
- Disk 512 MB, CPU kuniga cheklangan, sayt 3 oyda bir "Extend" tugmasi bilan uzaytiriladi.
- ASGI (FastAPI) hosting PythonAnywhere'da **beta**; WebSocket (jonli bildirishnoma) ishlamasligi mumkin —
  sahifalar baribir ishlaydi.
- Kompyuterni boshqarish (sichqoncha, ekran) va 🤖 Claude menyusi serverda emas, **shu kompyuterdagi** ROBIN'da ishlaydi.
- Telegram bot tokenini faqat **bitta** joyda (server yoki kompyuter) yoqing.

Pullik tarif ($5/oy dan): cheklovsiz internet, ko'proq disk/CPU, o'z domeningiz.
