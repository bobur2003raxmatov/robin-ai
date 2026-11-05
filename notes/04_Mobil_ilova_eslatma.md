# 📱 ROBIN mobil ilovasi (Android / iOS)

**Holat:** ✅ 1-versiya tayyor (2026-11-05). Kod: `mobile/robin_app` (Flutter).

## O'rnatish (Android)
1. Kompyuterda: Dashboard → **Download App** → "ROBIN Android ilovasi" → **⬇ ROBIN.apk** (yoki telefon bilan QR'ni skanerlang).
2. Telefonda APK'ni oching → "Noma'lum manbalardan o'rnatish"ga ruxsat bering → O'rnatish.
3. Ilovani oching → **"QR orqali ulanish"** → kompyuterda Download App → **📱 Telefonni ulash** bosilganda chiqqan QR'ni skanerlang. Parol kiritish shart emas.
   - Yoki server manzili (`http://192.168.x.x:8000`), login va parol bilan kiring.
4. Shart: telefon va kompyuter bitta Wi-Fi'da, serverda `.env` → `HOST=0.0.0.0`. Internet orqali — HTTPS domen (hostingdan keyin).

## Imkoniyatlar
- 💬 **Chat**: matn, markdown javoblar, tayyor buyruqlar (Admin → Mijoz paneli'dagi tugmalar).
- 🎤 **Ovoz**: mikrofon → matn (uz/ru/en) → ROBIN → javob server ovozida (Edge TTS) o'qiladi. Xabarni uzoq bosish — qayta o'qish.
- 📷 **Live Vision**: kamera bilan rasm olib tahlil qildirish (Excel, grafik, hujjat).
- ✅ **Tasdiqlar**: ROBIN xavfli amaldan oldin so'raydi — telefondan Ruxsat / Rad; ⛔ STOP tugmasi.
- 🔔 **Bildirishnomalar**: ilova ochiq (yoki fonda) turganda tasdiq so'rovlari va xabarlar.
- 📝 **Notes**: barcha qaydlar va yo'riqnomalar, yangi qayd qo'shish.
- 🤖 **Claude** (faqat admin): ikonkani yoqish/o'chirish va vazifa berish, natija jonli.
- ⚙️ Sozlamalar: hisob, server, bugungi limit, javoblarni avtomatik o'qish, chiqish.

## Yangilash (admin)
`mobile\robin_app\build_apk.bat` — APK'ni qayta yig'adi va `database\apps\ROBIN.apk` ga joylaydi (Download App sahifasida darhol ko'rinadi).

## Keyingi qadamlar
- Firebase push (ilova yopiq bo'lsa ham bildirishnoma) — Firebase loyihasi kerak.
- iOS: Mac + Xcode orqali yig'ish va TestFlight.
- Google Play: imzo kaliti (keystore) va do'kon sahifasi.
- "Hey ROBIN" uyg'otish so'zi va bosh ekran vidjeti.
