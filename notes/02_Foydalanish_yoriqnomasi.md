# 📘 ROBIN'dan foydalanish yo'riqnomasi

## 1. Ishga tushirish
1. `C:\Users\USER\AI Assist` papkasidagi **`start_robin.bat`** faylini ikki marta bosing. Qora oyna ochiladi, bu server — **uni yopmang**.
2. Brauzerda **http://127.0.0.1:8000** ochiladi. Login va parol bilan kiring.
3. **Brain** bo'limida kamida bitta AI kalitini kiriting va "⚡ Ulanishni sinash" ni bosing.
4. Laptop chetidagi 3D robot uchun `start_widget.bat` ni ishga tushiring yoki **Download App** bo'limidan foydalaning.

## 2. ROBIN bilan gaplashish
- **Chat:** yozing va Enter bosing. 🎙️ tugmasi bilan gapirish mumkin, 🖼️ bilan rasm yuboriladi.
- **Live suhbat:** Chat → "Live suhbat" ni yoqing. ROBIN to'xtovsiz tinglaydi, gapingizni bo'lib javob bera oladi.
- **Tillar:** o'zbek (lotin/kirill, sheva), rus va ingliz. ROBIN qaysi tilda gapirsangiz, o'sha tilda javob beradi.
- **Misollar:**
  - "Ertaga soat 10:00 ga investor bilan uchrashuv belgilab qo'y"
  - "Desktop'dagi savdo.xlsx faylini tahlil qil, xatolarni top va hisobot tayyorla"
  - "Kompyuterim holatini ko'rsat" · "Chrome'ni och va youtube.com ga kir"
  - "Internetdan qidir: …" · "BTCUSDT ni 4 soatlik grafikda tahlil qil"
  - "Buni notesga yozib qo'y: …" · "Eslab qol: men har kuni 9 da ishni boshlayman"

## 3. Bo'limlar
| Bo'lim | Nima uchun |
|---|---|
| Home | Avatar, tezkor buyruq, umumiy holat |
| Chat | Suhbatlar tarixi, ovoz, rasm, ekranni ulashish (Live Vision) |
| Autopilot | Katta vazifalar: navbat, bajarilayotganlar, Approval Center, jurnal |
| Brain | 10 ta AI kaliti, modellar, Multi-Brain, Personality |
| Memory | ROBIN eslab qolgan faktlar, loyihalar, qarorlar |
| Agents | Mutaxassis agentga to'g'ridan-to'g'ri topshiriq berish |
| Automation | Saqlangan buyruqlar (＋), eslatma va uchrashuvlar |
| Files | PDF/Word/Excel yuklash (bilimlar bazasi), Excel tahlil |
| Notes | Yo'riqnomalar va ROBIN avtomatik yozadigan qaydlar |
| Voice / Avatar | Ovoz, til, uyg'otish so'zi; robot ranglari va vidjet |
| Trading | Tahlil, AI tahlilchi, risk, backtest, simulator, jurnal, akademiya |
| Settings | Ruxsatlar, qurilmalar, Telegram, Ishlash holati (live), admin |
| Download App | Desktop va mobil ilovani yuklab olish |

## 4. Buyruq qo'shish (Automation → ＋)
- **✍️ Qo'lda:** bosqichlarni (asboblarni) ketma-ket qo'shasiz.
- **🎥 Aqlli:** "Yozishni boshlash" ni bosing va ishingizni odatdagidek bajaring. Keyin "To'xtatish" ni bosing: ROBIN harakatlaringizni kuzatib, buyruq tuzadi. Saqlashdan oldin bosqichlarni tekshiring.
- **🧠 Ta'riflash:** kunlik ishingizni so'z bilan yozasiz, ROBIN bosqichlarni o'zi tuzadi.
- Har bir buyruq nomi bilan saqlanadi. Uni nomi yoki ovozli iborasi bilan ("ROBIN, ertalabki ish") ishga tushirasiz. Jadval bilan avtomatik ham ishlaydi.

## 5. Xavfsizlik va tasdiq
- **Xavfli amallar** (fayl o'chirish, terminal, real savdo, xabar yuborish) **Approval Center** orqali tasdiqlanadi. Tasdiqni Dashboard, Telegram yoki vidjet orqali berish mumkin.
- **⛔ STOP** tugmasi barcha agentlarni darhol to'xtatadi. Qayta bosilsa, davom ettiradi.
- **O'chirilgan fayllar** `~/.robin_trash` papkasiga tushadi va qayta tiklanishi mumkin.
- **Settings → Xavfsizlik** bo'limida har bir modul ruxsati va mustaqillik darajasi sozlanadi.

## 6. Telegram orqali boshqarish
1. `.env` faylida `TELEGRAM_BOT_TOKEN=` ga @BotFather'dan olingan tokenni yozing va ROBIN'ni qayta ishga tushiring.
2. Settings → Telegram → "Ulash kodini olish" ni bosing va botga `/link KOD` yuboring.
3. Endi botga matn yoki ovozli xabar yuborishingiz mumkin. Buyruqlar: `/stop`, `/resume`, `/tasks`.

## 7. Boshqa kompyuterlarni ulash
**Download App → Desktop ilova** bo'limiga kiring va "Shu kompyuterga yuklab olish" yoki "Boshqa noutbuk uchun QR" ni tanlang. ZIP'ni ochib, o'rnatuvchini ishga tushiring. Server manzili va qurilma tokeni paket ichida tayyor.

## 8. Muammo bo'lsa
- **"AI kvotasi tugadi"** — bepul kalit limiti tugagan. Bir daqiqa kuting yoki Brain'ga ikkinchi AI qo'shing.
- **Sahifa eski ko'rinyapti** — **Ctrl+F5** ni bosing.
- **Server ishlamayapti** — `start_robin.bat` ni qayta ishga tushiring.
- **Holatni tekshirish** — Settings → 📊 Ishlash holati, 👑 Admin → Xavfsizlik va sozlamalar → Xatolar (Self-Repair).
- **"Xizmat o'chirilgan" (🔒)** — bu xizmatni administrator o'chirgan. Admin uni 👑 Admin → Xizmatlar nazorati'da yoqadi.
- **ROBIN biror so'zni noto'g'ri aytadi** — Voice → 📖 Talaffuz lug'ati'ga so'zni va uning aytilishini yozing.

## 9. Ovoz sozlamalari (Voice)
- **Gapirish:** dvigatel (Edge Neural bepul, OpenAI yoki brauzer), o'zbek/rus/ingliz ovozlari (▶ tugmasi bilan eshitib ko'riladi), tezlik, ohang, ovoz balandligi va tayyor uslublar (Tabiiy, Sekin va aniq, Tez, Chuqur, Yorqin).
- **O'zbekcha talaffuz:** raqam, sana, vaqt, foiz va pul miqdorlari so'z bilan o'qiladi (`15:30` → "o'n besh o'ttiz", `5-noyabr` → "beshinchi noyabr", `12,5%` → "o'n ikki butun o'ndan besh foiz"). Excel, PDF, AI, ChatGPT kabi 150 dan ortiq so'z to'g'ri aytiladi. Kirill yozuvidagi o'zbekcha matn lotinga o'giriladi.
- **Aralash matn:** javobdagi ruscha gaplar rus ovozida, qolgani o'zbek ovozida o'qiladi.
- **👁 Qanday o'qiladi?** tugmasi ROBIN aynan qaysi so'zlarni aytishini ko'rsatadi.
- **📖 Talaffuz lug'ati:** noto'g'ri aytilgan so'zni va uning qanday aytilishini yozasiz, masalan `CRM → si-ar-em`.
- **Tinglash:** brauzer (bepul) yoki Whisper (shevalarni yaxshiroq taniydi), tanish tili, uyg'otish so'zi, gapni bo'lish (barge-in), aks-sado filtri, sukut vaqti, shovqinni pasaytirish, signal ovozi.
- Uzun javoblar bo'laklab o'qiladi: birinchi gap darhol eshitiladi, qolgani orqa fonda tayyorlanadi.

## 10. Admin paneli (👑 Admin — faqat admin uchun)
- **Foydalanuvchilar:** yangi hisob yaratish (parol avtomatik yaratilishi mumkin), ismni o'zgartirish, parolni tiklash, barcha sessiyalardan chiqarish, agentlarini to'xtatish, admin qilish, bloklash va faollik tarixi.
- **🧩 Xizmatlar nazorati:** har bir foydalanuvchi uchun 19 ta xizmatni (chat, ovoz, fayllar, kompyuter, terminal, internet, trading, Telegram…) yoqish yoki o'chirish, shuningdek kunlik xabar va ovozli so'rov limitlari. O'chirilgan xizmat menyudan yo'qoladi va ROBIN u uchun bu asboblarni ishlatmaydi (chat, Telegram va ovozda ham).
- **📊 Statistika:** bugungi va 7 kunlik faollik, 14 kunlik diagramma, eng faol foydalanuvchilar, bloklangan amallar, noto'g'ri parol urinishlari.
- **🛡️ Xavfsizlik:** ro'yxatdan o'tishni yopish (shunda hisobni faqat admin yaratadi), yangi foydalanuvchilar uchun standart xizmatlar va limitlar, zaxira nusxa, Self-Repair, Global STOP.
- **📜 Audit:** barcha foydalanuvchilar bo'yicha kirishlar, admin amallari va bloklangan amallar.
- Login himoyasi: 5 marta noto'g'ri parol kiritilsa, o'sha login 10 daqiqaga bloklanadi.

## 11. 🤖 Claude (Admin → Claude)
1. Yuqori paneldagi 🤖 ikonkani bosing (yoki Admin → 🤖 Claude) va katta 🤖 tugma bilan Claude'ni **yoqing** (yashil rangda yonadi).
2. Vazifani yozing va Ctrl+Enter bosing. Claude ROBIN kodini o'zgartiradi va har bir qadamini ko'rsatib boradi.
3. Ish tugagach, ikonkani o'chirib qo'ying. O'chiq paytda Claude hech narsa qilmaydi.
- Chat yoki Telegram'da ishlatish: `/claude <vazifa>` (faqat admin uchun).
- Claude o'tgan ishlarni o'zi eslaydi: sessiya davom etadi, qo'shimcha xotira `CLAUDE.md` va `notes/05_Claude_jurnali.md` fayllarida.
- Ruxsat rejimi: **acceptEdits** fayllarni tahrirlaydi (tavsiya etiladi). **plan** faqat o'qiydi va reja tuzadi. **bypass** terminaldagidek hamma narsani so'ramasdan bajaradi.

## 12. 🧑‍💼 Mijoz paneli (`/panel`)
- Oddiy foydalanuvchilar tizimga kirganda avtomatik shu panelga o'tadi: unda chat va tayyor buyruqlar bor.
- Admin → 🧑‍💼 Mijoz paneli bo'limida sarlavha, salomlashuv matni va buyruqlar (ikonka, nom, matn, xizmat) sozlanadi.
- Buyruq matni `:` bilan yoki bo'sh joy bilan tugasa, mijozdan qo'shimcha matn so'raladi (masalan, "Tarjima: ").
- Panelni kengaytirish uchun Admin → 🤖 Claude bo'limida vazifa yozing, masalan: "Mijoz paneliga buyurtma holati bo'limini qo'sh".

## 13. 🚀 Doimiy hosting
Qarang: `deploy/README.md`. Qisqacha tartib: GitHub repo yarating, `git push` qiling, serverga `deploy/install.sh` (yoki Docker) bilan o'rnating, so'ng GitHub webhook'ni `https://<domen>/api/deploy/webhook` manziliga ulang.

