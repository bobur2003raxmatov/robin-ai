# 🔑 AI kalitlarini olish (Brain bo'limi)

Bir nechta kalit kiritsangiz, ROBIN ulardan birini avtomatik tanlaydi: bittasi band bo'lsa yoki limiti tugasa, keyingisiga o'tadi. Kalitlar shifrlangan holda saqlanadi.

| AI | Narx | Qayerdan olinadi | Izoh |
|---|---|---|---|
| Google Gemini | bepul tarif bor | aistudio.google.com/apikey | Kredit karta shart emas. Asosan Flash modellar, limiti kichik |
| Groq | bepul limit yaxshi | console.groq.com/keys | Llama, Qwen, GPT-OSS; juda tez |
| OpenRouter | `:free` modellar | openrouter.ai/keys | Bitta kalit bilan ko'p modelga ulanadi; ROBIN faqat bepullarini tanlaydi |
| Mistral | "Experiment" tarifi | console.mistral.ai/api-keys | Bepul sinov tarifi |
| Cerebras | bepul tarif | cloud.cerebras.ai | Juda tez, ochiq modellar |
| GitHub Models | GitHub akkaunti bilan bepul | github.com/settings/tokens | Token (`models:read`). ⚠️ Sizning tarmog'ingizda sinovda g'ayritabiiy javob berdi |
| Cloudflare Workers AI | kuniga bepul limit | dash.cloudflare.com → API Tokens | Kalitni **ACCOUNT_ID:API_TOKEN** ko'rinishida kiriting |
| Hugging Face | bepul, juda cheklangan | huggingface.co/settings/tokens | Inference token |
| Claude (Anthropic) | pullik | console.anthropic.com | Eng kuchli agent rejimi |
| ChatGPT (OpenAI) | pullik | platform.openai.com/api-keys | Whisper ovoz tanish ham shu kalit bilan |

## Maslahatlar
- **Eng yaxshi bepul to'plam:** Gemini + Groq + OpenRouter. ROBIN ular orasida avtomatik almashadi.
- **Model maydoni bo'sh qolsin:** ROBIN modelni o'zi tanlaydi va model nomi o'zgarsa yangisini o'zi topadi.
- **Natijani tekshirish:** "⚡ Ulanishni sinash" har bir AI uchun ✅/❌, qaysi model javob bergani va vaqtini ko'rsatadi.
- **Kuzatish:** Settings → 📊 Ishlash holati'da har bir AI'ning muvaffaqiyat foizi va o'rtacha javob vaqti ko'rinadi.
