# ROBIN AI — loyiha xotirasi (Claude Code uchun)

Bu fayl Claude Code har safar ishga tushganda avtomatik o'qiladi (terminalda ham, Admin panel → 🤖 Claude menyusida ham).
Egasi: Operator DuselUp. Javoblar **o'zbek tilida**. Ortiqcha savol bermasdan, kerakli ishni oxirigacha bajar.

## Loyiha
- **Backend:** FastAPI (`backend/main.py`), SQLAlchemy async + SQLite (`database/robin.db`), Python `.venv`.
  - `backend/ai/` — ko'p-provayderli "miya" (Anthropic, OpenAI, Gemini, Groq, Mistral, OpenRouter, Cloudflare…);
    kalitlar har bir foydalanuvchi uchun DB'da shifrlangan (`settings_store`, key `api_keys`).
  - `backend/agents/` — executor (chat, tools, autopilot), `tools.py` — ROBIN asboblari.
  - `backend/api/` — REST: `admin.py` (Admin panel), `claude.py` (🤖 Claude menyusi), `client.py` (Mijoz paneli),
    `deploy.py` (git push webhook), `chat.py`, `robin.py`, `trading.py`, `voice.py`, `notes.py`…
  - `backend/integrations/claude_code.py` — Claude Code CLI ko'prigi (faqat panel ikonkasi yoqilganda ishlaydi).
  - `backend/security/services.py` — har bir foydalanuvchiga ochiq xizmatlar, limitlar, `admin_config.json`
    (shu jumladan `client_panel`, `client_commands`).
- **Frontend:** vanilla JS, build yo'q.
  - `frontend/pages/index.html` + `frontend/src/app.js` — asosiy dashboard (admin uchun to'liq).
  - `frontend/pages/panel.html` + `frontend/src/panel.js` + `panel.css` — **Mijoz paneli** (`/panel`),
    oddiy foydalanuvchilar kirganda avtomatik shu yerga yo'naltiriladi.
- `desktop/` — desktop agent va widget; `mobile/` — PWA manifest (native mobil ilova — keyingi bosqich).
- `notes/` — Markdown qaydlar, dashboard Notes sahifasida ko'rinadi.

## Qoidalar
1. O'zgarishdan keyin testlar: `.venv\Scripts\python.exe -m pytest -q` (hammasi o'tishi shart).
2. Foydalanuvchining ishlab turgan serveri **:8000** portda — uni to'xtatma. Sinash uchun boshqa port (masalan 8011)
   va alohida `DATABASE_URL` ishlat.
3. Har bir ish oxirida `notes/01_Qilingan_ishlar.md` ga sanali bo'lim qo'sh; foydalanish o'zgargan bo'lsa
   `notes/02_Foydalanish_yoriqnomasi.md` ni yangila.
4. Sirlarni (API kalitlar, `.env`, tokenlar) hech qachon log/javob/commit'ga chiqarma.
5. Mijoz paneli funksiyalari oddiy foydalanuvchiga xizmat siyosatini (`require_service`) hurmat qilishi kerak.

## Keyingi bosqichlar
- Mobil ilova (notes/04_Mobil_ilova_eslatma.md).
- Doimiy hosting: `git push` → GitHub webhook → `/api/deploy/webhook` (qarang `deploy/README.md`).
