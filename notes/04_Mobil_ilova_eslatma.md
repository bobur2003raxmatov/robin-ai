# 📱 Eslatma: native mobil ilova — keyinroq bajaramiz

**Holat:** ⏳ rejalashtirilgan (hali boshlanmagan). Bu yozuv keyingi bosqich uchun eslatma.

## Hozir nima ishlaydi
- **PWA:** Download App → Mobil ilova bo'limidagi QR kod. Telefonda "Bosh ekranga qo'shish" orqali ROBIN ilova kabi ochiladi.
- **Telegram bot** orqali to'liq boshqarish ishlaydi: matn, ovoz, tasdiqlash, /stop.
- **Shart:** telefon bitta Wi-Fi'da bo'lishi kerak. `.env` faylida `HOST=0.0.0.0` qilinadi.

## Keyingi bosqichda qilinadigan ishlar
1. **Texnologiya tanlash:** Flutter (tavsiya) yoki React Native. Bitta kod bilan Android va iOS.
2. **Ekranlar:** Login, Chat (ovoz bilan), Autopilot, Approval Center, Notes, Trading kuzatuvi, Settings.
3. **Push bildirishnomalar** (Firebase Cloud Messaging / APNs): tasdiq so'rovlari, eslatmalar, vazifa natijalari.
4. **Ovoz:** "Hey ROBIN" uyg'otish so'zi, telefon vidjeti va tezkor buyruq.
5. **Live Vision:** telefon kamerasini Excel jadval, grafik yoki hujjatga qaratib, ROBIN'ga tahlil qildirish.
6. **Xavfsiz ulanish:** uydan tashqarida ishlashi uchun HTTPS (Cloudflare Tunnel yoki domen + sertifikat).
7. **QR orqali juftlash:** kompyuterdagi ROBIN bilan telefonni bir skanerlash bilan bog'lash.
8. **Nashr qilish:** Google Play (APK/AAB) va App Store (TestFlight → nashr).

## Eslatma
iOS cheklovlari sabab telefon kompyuterdagi kabi barcha tizim amallarini mustaqil bajara olmaydi. Mobil ilova asosan **boshqarish, tasdiqlash va monitoring** uchun bo'ladi.
