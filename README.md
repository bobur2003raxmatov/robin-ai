# 🤖 ROBIN — shaxsiy operatsion AI tizimi

ROBIN — shaxsiy raqamli hamroh, kompyuter boshqaruvchisi va mustaqil AI agent.
U buyruqni ovoz yoki matn orqali qabul qiladi, uning ma'nosini tushunadi, reja tuzadi, kompyuter va internet bilan
ishlab bajaradi, natijani tekshiradi va sizga topshiradi. Trading Expert moduli ham ichida bor.

## Tezkor ishga tushirish (Windows)

1. `.env` faylini oching va kamida bitta AI kalitini kiriting: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` yoki `GEMINI_API_KEY`.
   Kalitlarni keyinroq **Dashboard → Brain** bo'limidan ham kiritish mumkin (ular shifrlangan holda saqlanadi).
2. `start_robin.bat` faylini ikki marta bosing. Brauzerda http://127.0.0.1:8000 ochiladi.
3. Ro'yxatdan o'ting. **Birinchi ro'yxatdan o'tgan foydalanuvchi avtomatik admin bo'ladi.**
4. Laptop chetida 3D ikonka chiqishi uchun `start_widget.bat` ni ishga tushiring.

Qo'lda ishga tushirish: `.venv\Scripts\python -m backend.main` · Testlar: `.venv\Scripts\python -m pytest`
· Brauzer testi (Edge/Chrome): `.venv\Scripts\python tests\ui_smoke.py`

**Ishlash holati:** Settings sahifasining yuqorisida umumiy holat foizda ko'rsatiladi. U yerda har bir komponentning
foizi, 24 soatlik ko'rsatkichlar va CPU / RAM / AI muvaffaqiyatining live diagrammasi bor (har 2 soniyada yangilanadi).

## Imkoniyatlar

| Bo'lim | Nima qiladi |
|---|---|
| **Multi-Brain** | 10 ta AI: Claude, ChatGPT, Gemini, Groq, OpenRouter (:free), Mistral, Cerebras, GitHub Models, Cloudflare Workers AI, Hugging Face. Provayderlar va modellar orasida avtomatik zaxira, modellarni o'zi topish, mutaxassis agentlar, Ensemble, Self-Review |
| **Agentlar** | assistant, developer, analyst (Excel Expert), researcher, translator, designer, manager, security, trader |
| **Kompyuter boshqaruvi** | 60 ta asbob: fayllar (qidirish, o'qish, yozish, saralash, qaytariladigan o'chirish), ilovalar, oynalar, sichqoncha/klaviatura, skrinshot + Computer Vision (`screen_read`, `click_text`), terminal, Python sandbox, bufer, media |
| **Excel Expert** | `excel_analyze` bo'sh qiymatlar, dublikatlar, manfiy qiymatlar, outlierlar, miqdor×narx≠jami holatlari va formula xatolarini topadi. `excel_report` diagrammali hisobot yaratadi |
| **Autopilot** | Vazifalar navbati, parallel bajarish, Task Planner, Active/Queue/Completed/Failed, Approval Center, Agent Monitor, Resource Monitor, Activity Log |
| **Commands** | ＋ → qo'lda qo'shish, **aqlli qo'shish** (harakatlaringizni kuzatib o'rganadi) yoki so'z bilan ta'riflash. Har bir buyruq nomi bilan saqlanadi, ovozli ibora yoki jadval (`daily 09:00`) orqali ishga tushadi |
| **Memory 360** | Qisqa muddatli xotira (suhbat), uzoq muddatli xotira (faktlar, afzalliklar, loyihalar, qarorlar — bir-biriga bog'langan), Knowledge Center (PDF, Word, Excel bo'yicha semantik qidiruv) |
| **Self-Learning** | 👍/👎 va ✏️ tuzatishlardan qoida chiqaradi. Admin ruxsat bersa, o'z sozlamalarini o'zi moslaydi. Self-Repair esa xatolarni tahlil qilib, tuzatish taklif qiladi |
| **Ovoz** | O'zbekcha neyron ovoz (uz-UZ-SardorNeural / MadinaNeural). Raqam, sana va foizlar so'z bilan o'qiladi, 150+ so'zli talaffuz lug'ati va shaxsiy lug'at bor, kirill→lotin, aralash matn o'z tilidagi ovozda o'qiladi. Tezlik, ohang va balandlik sozlanadi, javob bo'laklab o'qiladi, kesh bor. Live suhbat (gapni bo'lish, aks-sado filtri), uyg'otish so'zi "robin", Whisper/Gemini STT, sukutni aniqlash |
| **Admin paneli** | Foydalanuvchilar (yaratish, parolni tiklash, sessiyani yakunlash, bloklash), **har bir foydalanuvchi uchun 19 ta xizmatni yoqish/o'chirish** va kunlik limitlar, statistika, audit, ro'yxatdan o'tishni yopish, login himoyasi |
| **3D Avatar** | Robot tanasi va yuzi, Lip Sync, Eye Tracking, holatlar (tinglash, o'ylash, gapirish, ishlash, xursand, ogohlantirish), desktop vidjet |
| **Daily Manager** | "Ertaga soat 10:00 ga uchrashuv belgilab qo'y" kabi buyruqlar, eslatmalar, takrorlanish, uchrashuvdan 15 daqiqa oldin ogohlantirish, .ics eksport |
| **Telegram** | Matn, ovozli xabar (ovozli javob bilan), ✅/❌ tasdiqlash tugmalari, `/stop`, `/tasks` |
| **Trading Expert** | Barcha bozorlar (Binance crypto, Forex, Stocks, indekslar, oltin, neft). Trend, S/R, RSI, MACD, EMA, Bollinger, ATR, Fibonacci, Price Action, Smart Money (BOS/CHoCH/OB/FVG/likvidlik), Risk Manager, Backtest, Strategy Competition, Simulator, Jurnal, AI Mentor, Akademiya (noldan Advanced darajagacha) |
| **Xavfsizlik** | Login/parol (bcrypt + JWT), har bir foydalanuvchi uchun alohida ID va to'liq izolyatsiya, Permission Manager, Action Validator, Sandbox, Approval Center, Audit Log, Emergency STOP, Backup, prompt-injection himoyasi, kalitlarni shifrlash |
| **Smart Home** | Home Assistant orqali qurilmalarni boshqarish |

## Bir nechta laptopni ulash

Server bitta joyda (yoki bulutda) ishlaydi, har bir laptopda esa agent ishga tushiriladi:

```
Dashboard → Settings → Qurilmalar → "Token olish"
python desktop/robin_agent.py --server http://SERVER:8000 --token <token> --widget
```
Agent Windows, macOS va Linux'da ishlaydi. Favqulodda to'xtatish uchun sichqonchani ekran burchagiga olib boring.

## Mobil

Dashboard PWA sifatida ishlaydi: telefonda saytni ochib, "Bosh ekranga qo'shish" ni tanlang. iOS cheklovlari
sababli telefon versiyasi kompyuterdagi barcha amallarni bajara olmaydi, u boshqarish va monitoring uchun
mo'ljallangan (Telegram ham shu vazifani bajaradi).

## Tuzilma

```
backend/  main.py · config.py
  ai/        brain.py (Multi-Brain) · providers.py (Claude/GPT/Gemini) · prompts.py · planner.py
  agents/    executor.py (agent sikli, Autopilot, Approval) · tools.py · computer.py · devices.py · scheduler.py · events.py
  memory/    database.py (barcha modellar) · memory.py (3 qatlam) · settings_store.py
  voice/     speech_to_text.py · text_to_speech.py
  security/  auth.py · permissions.py · services.py (admin siyosati) · vault.py
  trading/   market.py · indicators.py · risk.py · backtest.py · broker.py · lessons.py
  api/       auth · chat · voice · robin · trading · system · admin
  integrations/ telegram_bot.py
frontend/ pages/index.html (Dashboard) · pages/widget.html · src/app.js · avatar.js · voice.js · styles.css
desktop/  robin_widget.py · robin_agent.py
mobile/   manifest.json · sw.js
tests/    38 ta test
```

## Ishlab chiqarish (production)

- PostgreSQL: `DATABASE_URL=postgresql+asyncpg://...` va `pip install asyncpg`.
- `.env` faylidagi `SECRET_KEY` o'rnatishda tasodifiy qilib yaratilgan. Uni sir saqlang.
- HTTPS orqasida ishga tushiring (nginx/caddy) va `HOST=0.0.0.0` qiling.
- Real trading: avval `BINANCE_TESTNET=true` bilan sinab ko'ring. Real hisobdagi har bir savdo faqat tasdiq bilan bajariladi.

> ⚠️ Trading moduli ta'lim va tahlil uchun mo'ljallangan, moliyaviy maslahat emas.
