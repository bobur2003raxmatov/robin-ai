"""Text-to-Speech: natural Uzbek (uz-UZ-SardorNeural / MadinaNeural), Russian and English voices.

Engines: edge (free, neural, best Uzbek pronunciation) | openai (tts-1 / tts-1-hd / gpt-4o-mini-tts) | browser.

Uzbek pronunciation pipeline (the neural voice only reads well what it is given):
  1. clean_for_speech  — markdown, links, emoji, tables → natural spoken text with pauses
  2. cyr_to_lat        — Uzbek Cyrillic → Latin (the uz-UZ voices are trained on Latin script)
  3. apply_lexicon     — tech words / brands / abbreviations → how an Uzbek speaker says them
                         (built-in dictionary + the user's own "Talaffuz lug'ati")
  4. numbers_to_uz     — 15:30, 5-noyabr, 2026-yil, 15%, 3,5, $100, 1 000 000 → Uzbek words
  5. normalize_uzbek   — oʻ / gʻ / tutuq belgisi with the correct Unicode letters
Mixed replies (Uzbek + Russian sentences) are read with the right voice per sentence.
"""
from __future__ import annotations

import asyncio
import hashlib
import re
import time

import httpx

from backend.config import DATA_DIR

AUDIO_DIR = DATA_DIR / "audio"
AUDIO_DIR.mkdir(exist_ok=True)

UZ_CYR = set("ўқғҳЎҚҒҲ")
UZ_WORDS = {"va", "bu", "men", "sen", "siz", "uchun", "bilan", "qanday", "nima", "yaxshi", "rahmat", "ham", "bor",
            "yoʻq", "kerak", "qil", "boʻladi", "endi", "hozir", "ertaga", "salom", "bajarildi", "fayl", "soat",
            "emas", "lekin", "agar", "yoki", "keyin", "oldin", "bugun", "kecha", "qilib", "qildim", "beraman",
            "tayyor", "xato", "iltimos", "albatta", "mumkin", "kerakmi", "qanaqa", "shu", "u", "biz", "ular"}
EN_WORDS = {"the", "and", "is", "are", "you", "your", "to", "of", "in", "it", "for", "with", "this", "that", "be",
            "have", "i", "we", "can", "will", "not", "what", "how", "hello", "please", "thanks", "on", "at", "my"}
UZ_SUFFIX = re.compile(r"\w{2,}(lar|ning|dagi|larni|larga|imiz|ingiz|yapti|moqda|gan|dim|ish|chi|siz)\b")


def _norm_apos(t: str) -> str:
    return re.sub(r"[ʻʼ’‘`´]", "'", t)


def detect_language(text: str) -> str:
    if any(ch in UZ_CYR for ch in text):
        return "uz"
    cyr = sum(1 for ch in text if "Ѐ" <= ch <= "ӿ")
    lat = sum(1 for ch in text if ch.isascii() and ch.isalpha())
    if cyr > lat:
        return "ru"
    t = _norm_apos(text.lower())
    words = re.findall(r"[a-z']+", t)
    if not words:
        return "uz"
    uz = sum(1 for w in words if w.replace("'", "ʻ") in UZ_WORDS or w in UZ_WORDS)
    uz += 2 * len(re.findall(r"\b\w*[og]'\w*", t)) + len(UZ_SUFFIX.findall(t))
    uz += sum(1 for w in words if re.search(r"(q|x)", w) and not re.search(r"(qu|x$|ex|ax)", w))
    en = sum(1 for w in words if w in EN_WORDS)
    return "en" if en > uz else "uz"


# ------------------------------------------------------------------ 1. cleaning
def clean_for_speech(text: str, read_code: bool = False, limit: int = 3000) -> str:
    t = text or ""
    t = re.sub(r"```.*?```", (lambda m: " " + m.group(0).strip("`") + ". ") if read_code else " (kod ekranda). ",
               t, flags=re.S)
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", t)                       # images
    t = re.sub(r"\[([^\]]+)\]\((https?:[^)\s]+)\)", r"\1", t)          # [text](url) → text
    t = re.sub(r"https?://\S+|www\.\S+", " havola ", t)
    t = re.sub(r"^[ \t]*\|?[ \t:\-|]+\|?[ \t]*$", "", t, flags=re.M)   # table separators
    t = re.sub(r"^[ \t]*\|(.*)\|[ \t]*$", lambda m: ", ".join(c.strip() for c in m.group(1).split("|") if c.strip()) + ".",
               t, flags=re.M)                                           # table rows → "a, b, c."
    t = re.sub(r"^\s*#{1,6}\s*(.+)$", r"\1.", t, flags=re.M)           # headings → sentence
    t = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s+(.+)$", lambda m: m.group(1).rstrip() + ("" if m.group(1).rstrip()[-1:] in ".!?:;," else ";"),
               t, flags=re.M)                                           # list items → pause
    t = re.sub(r"`([^`]+)`", r"\1", t)
    t = re.sub(r"(\*\*|__|\*|_|~~)(\S.*?\S|\S)\1", r"\2", t)
    t = re.sub(r"[#>|*_~]+", " ", t)
    t = t.replace("→", ", ").replace("⇒", ", ").replace("—", ", ").replace("–", ", ").replace("…", ".")
    t = re.sub(r"[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F\u200D\u2190-\u21FF\u2300-\u23FF\u25A0-\u25FF]", " ", t)
    t = re.sub(r"\n{2,}", ". ", t)
    t = re.sub(r"\n", " ", t)
    t = re.sub(r"\s+([.,!?;:])", r"\1", t)
    t = re.sub(r"([.!?;:,])\1+", r"\1", t)
    t = re.sub(r"[.;,]\s*\.", ".", t)
    t = re.sub(r"\s+", " ", t).strip(" ,;")
    if len(t) > limit:
        cut = t[:limit]
        end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
        t = cut[:end + 1] if end > limit * 0.6 else cut
    return t


# ------------------------------------------------------------------ 2. Cyrillic → Latin
_CYR = {"а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo", "ж": "j", "з": "z", "и": "i", "й": "y",
        "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f",
        "х": "x", "ц": "s", "ч": "ch", "ш": "sh", "щ": "sh", "ъ": "ʼ", "ы": "i", "ь": "", "э": "e", "ю": "yu",
        "я": "ya", "ў": "oʻ", "қ": "q", "ғ": "gʻ", "ҳ": "h"}


def cyr_to_lat(text: str) -> str:
    out = []
    for i, ch in enumerate(text):
        low = ch.lower()
        if low not in _CYR:
            out.append(ch)
            continue
        lat = _CYR[low]
        prev = text[i - 1] if i else " "
        if low == "е" and (not prev.isalpha() or prev.lower() in "аеёиоуўэюяъь"):
            lat = "ye"                                   # word-initial / after vowel: е → ye
        if low == "ц" and prev.isalpha() and prev.lower() in "аеиоуўэ":
            lat = "ts"
        out.append(lat.capitalize() if ch != low and lat else lat)
    return "".join(out)


# ------------------------------------------------------------------ 3. pronunciation lexicon (Uzbek voice)
UZ_LEXICON: dict[str, str] = {
    "ROBIN": "Robin", "AI": "ey-ay", "API": "ey-pi-ay", "URL": "yu-ar-el", "PDF": "pe-de-ef", "PC": "pi-si",
    "CPU": "si-pi-yu", "GPU": "ji-pi-yu", "RAM": "ram", "SSD": "es-es-di", "USB": "yu-es-bi", "QR": "kyu-ar",
    "SMS": "es-em-es", "IT": "ay-ti", "OK": "okey", "STOP": "stop", "PIN": "pin", "ID": "ay-di", "TV": "ti-vi",
    "JSON": "jeyson", "HTML": "eych-ti-em-el", "CSS": "si-es-es", "SQL": "es-kyu-el", "HTTPS": "eych-ti-ti-pi-es",
    "PWA": "pi-dabl-yu-ey", "STT": "es-ti-ti", "TTS": "ti-ti-es", "LED": "led", "3D": "uch-di",
    "Excel": "Eksel", "Word": "Vord", "PowerPoint": "Pauerpoint", "Outlook": "Autluk", "Windows": "Vindovs",
    "Microsoft": "Maykrosoft", "macOS": "mak-o-es", "Linux": "Linuks", "iPhone": "Ayfon", "iOS": "ay-o-es",
    "Android": "Android", "Google": "Gugl", "Gmail": "Jimeyl", "YouTube": "Yutub", "Chrome": "Xrom",
    "Edge": "Ej", "Telegram": "Telegram", "WhatsApp": "Votsap", "Instagram": "Instagram", "Facebook": "Feysbuk",
    "Zoom": "Zum", "GitHub": "Githab", "Python": "Payton", "JavaScript": "Javaskript", "ChatGPT": "Chat ji-pi-ti",
    "GPT": "ji-pi-ti", "OpenAI": "Open ey-ay", "Claude": "Klod", "Anthropic": "Antropik", "Gemini": "Jemini",
    "Whisper": "Visper", "Groq": "Grok", "Mistral": "Mistral", "Hugging Face": "Haging Feys", "Cloudflare": "Klaudfler",
    "Binance": "Bayns", "Bitcoin": "Bitkoyn", "BTC": "bitkoyn", "ETH": "efirium", "Ethereum": "Efirium",
    "USDT": "yu-es-di-ti", "USD": "dollar", "EUR": "yevro", "UZS": "soʻm", "RUB": "rubl", "Forex": "Foreks",
    "Trading": "Treyding", "trading": "treyding", "trader": "treyder", "Backtest": "Bektest", "backtest": "bektest",
    "RSI": "ar-es-ay", "MACD": "mak-di", "EMA": "i-em-ey", "SMA": "es-em-ey", "ATR": "ey-ti-ar",
    "Smart Money": "Smart Mani", "Price Action": "Prays Ekshn", "Stop Loss": "Stop Los", "Take Profit": "Teyk Profit",
    "Dashboard": "Deshbord", "Autopilot": "Avtopilot", "Notes": "Nouts", "Download": "Daunload",
    "Settings": "Setings", "Home Assistant": "Houm Assistent", "Smart Home": "Smart Houm", "widget": "vidjet",
    "email": "imeyl", "e-mail": "imeyl", "Wi-Fi": "vay-fay", "WiFi": "vay-fay", "Bluetooth": "blutuz",
    "online": "onlayn", "offline": "oflayn", "login": "login", "browser": "brauzer", "server": "server",
    "update": "apdeyt", "feedback": "fidbek", "deadline": "dedlayn", "meeting": "miting", "chat": "chat",
    "km": "kilometr", "kg": "kilogramm", "MB": "megabayt", "GB": "gigabayt", "TB": "terabayt", "KB": "kilobayt",
    "ms": "millisekund", "°C": " daraja", "°": " daraja", "km/h": "kilometr soatiga", "№": "raqam ",
}
_SYMBOLS = {"&": " va ", "+": " plyus ", "=": " teng ", "@": " kuchukcha ", "/": " ", "\\": " "}
_LETTERS_UZ = {"A": "a", "B": "be", "C": "si", "D": "de", "E": "e", "F": "ef", "G": "ge", "H": "ha", "I": "i",
               "J": "je", "K": "ka", "L": "el", "M": "em", "N": "en", "O": "o", "P": "pe", "Q": "qu", "R": "er",
               "S": "es", "T": "te", "U": "u", "V": "ve", "W": "dabl-yu", "X": "iks", "Y": "vay", "Z": "zet"}


def _lex_pattern(lex: dict[str, str]):
    keys = sorted(lex, key=len, reverse=True)
    parts = []
    for k in keys:
        e = re.escape(k)
        parts.append(rf"(?<![\w]){e}(?![\w])" if k[0].isalnum() and k[-1].isalnum() else e)
    return re.compile("|".join(parts)) if parts else None


_BUILTIN_RE = _lex_pattern(UZ_LEXICON)
_LOWER_MAP = {k.lower(): v for k, v in UZ_LEXICON.items() if not k.isupper()}
_LOWER_RE = re.compile("|".join(rf"(?<![\w]){re.escape(k)}(?![\w])" for k in sorted(_LOWER_MAP, key=len, reverse=True)
                                if k[0].isalnum() and k[-1].isalnum()), re.IGNORECASE)


def apply_lexicon(text: str, custom: dict | None = None) -> str:
    custom = {k.strip(): v for k, v in (custom or {}).items() if k and k.strip()}
    if custom:   # the user's own dictionary wins (case-insensitive for words)
        rx = re.compile("|".join(rf"(?<![\w]){re.escape(k)}(?![\w])" for k in sorted(custom, key=len, reverse=True)),
                        re.IGNORECASE)
        low = {k.lower(): v for k, v in custom.items()}
        text = rx.sub(lambda m: low.get(m.group(0).lower(), m.group(0)), text)
    if _BUILTIN_RE:
        lower_map = {k.lower(): v for k, v in UZ_LEXICON.items() if not k.isupper()}
        text = _BUILTIN_RE.sub(lambda m: UZ_LEXICON.get(m.group(0), m.group(0)), text)
        # brand names written in another case (excel, EXCEL, Youtube…)
        rx2 = re.compile("|".join(rf"(?<![\w]){re.escape(k)}(?![\w])" for k in sorted(lower_map, key=len, reverse=True)
                                  if k[0].isalnum() and k[-1].isalnum()), re.IGNORECASE)
        text = rx2.sub(lambda m: lower_map.get(m.group(0).lower(), m.group(0)), text)

    def caps(m):
        w = m.group(0)
        if not re.search(r"[AEIOU]", w) and len(w) <= 5:                 # CRM, PDF-like → spell out
            return "-".join(_LETTERS_UZ.get(c, c) for c in w)
        return w.capitalize()                                             # DIQQAT → Diqqat (not spelled)
    return re.sub(r"\b[A-Z]{2,}\b", caps, text)


# ------------------------------------------------------------------ 4. numbers → Uzbek words
_ONES = ["nol", "bir", "ikki", "uch", "toʻrt", "besh", "olti", "yetti", "sakkiz", "toʻqqiz"]
_TENS = ["", "oʻn", "yigirma", "oʻttiz", "qirq", "ellik", "oltmish", "yetmish", "sakson", "toʻqson"]
_SCALES = [(10 ** 12, "trillion"), (10 ** 9, "milliard"), (10 ** 6, "million"), (1000, "ming")]
_MONTHS = ["yanvar", "fevral", "mart", "aprel", "may", "iyun", "iyul", "avgust", "sentabr", "oktabr", "noyabr", "dekabr"]


def _below_1000(n: int) -> list[str]:
    w = []
    if n >= 100:
        if n // 100 > 1:
            w.append(_ONES[n // 100])
        w.append("yuz")
        n %= 100
    if n >= 10:
        w.append(_TENS[n // 10])
        n %= 10
    if n:
        w.append(_ONES[n])
    return w


def num_to_uz(n: int) -> str:
    if n == 0:
        return "nol"
    if n < 0:
        return "minus " + num_to_uz(-n)
    words = []
    for value, name in _SCALES:
        if n >= value:
            q, n = divmod(n, value)
            if not (value == 1000 and q == 1):
                words += _below_1000(q) if q < 1000 else [num_to_uz(q)]
            words.append(name)
    words += _below_1000(n)
    return " ".join(words)


def ordinal_uz(n: int) -> str:
    w = num_to_uz(n)
    if w.endswith("ellik"):
        return w[:-1] + "ginchi"
    return w + ("nchi" if w[-1] in "aeiouʻ" else "inchi")


def _digits(s: str) -> str:
    return " ".join(_ONES[int(c)] for c in s)


def _decimal(int_part: str, frac: str) -> str:
    frac = frac.rstrip("0") or "0"
    if len(frac) <= 3:
        denom = {1: "oʻndan", 2: "yuzdan", 3: "mingdan"}[len(frac)]
        return f"{num_to_uz(int(int_part))} butun {denom} {num_to_uz(int(frac))}"
    return f"{num_to_uz(int(int_part))} butun {_digits(frac)}"


def _int_words(s: str) -> str:
    s = re.sub(r"[\s,_  ]", "", s)
    if len(s) > 15:
        return _digits(s)
    if len(s) > 1 and s.startswith("0"):
        return _digits(s)       # phone codes, 007 …
    return num_to_uz(int(s))


def numbers_to_uz(text: str) -> str:
    t = text
    # phone numbers: +998 90 123 45 67 → digit groups
    t = re.sub(r"\+(\d{1,3})((?:[\s-]?\d{2,3}){3,4})",
               lambda m: "plyus " + ", ".join(_int_words(g) for g in [m.group(1)] + re.findall(r"\d+", m.group(2))), t)
    # dates
    t = re.sub(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", lambda m: _date(m.group(3), m.group(2), m.group(1)), t)
    t = re.sub(r"\b(\d{1,2})[./](\d{1,2})[./](\d{4})\b", lambda m: _date(m.group(1), m.group(2), m.group(3)), t)
    # time 15:30 / 9:05
    t = re.sub(r"\b([01]?\d|2[0-3]):([0-5]\d)(?::[0-5]\d)?\b",
               lambda m: num_to_uz(int(m.group(1))) + ("" if m.group(2) == "00" else
                                                        (" nol " + _ONES[int(m.group(2))] if m.group(2).startswith("0")
                                                         else " " + num_to_uz(int(m.group(2))))), t)
    # money
    cur = {"$": "dollar", "€": "yevro", "£": "funt", "₽": "rubl", "¥": "yen"}
    t = re.sub(r"([$€£₽¥])\s?(\d+(?:[  ,]\d{3})*(?:[.]\d+)?)", lambda m: f"{m.group(2)} {cur[m.group(1)]}", t)
    t = re.sub(r"(\d)\s?([$€£₽¥])", lambda m: f"{m.group(1)} {cur[m.group(2)]}", t)
    # thousands separators: 1 000 000 / 1,250,000
    t = re.sub(r"\b\d{1,3}(?:[  ]\d{3})+\b(?![.,]\d)", lambda m: _int_words(m.group(0)), t)
    t = re.sub(r"\b\d{1,3}(?:,\d{3}){1,4}\b(?!,\d)", lambda m: _int_words(m.group(0)), t)
    # ranges 5-10 → beshdan oʻngacha
    t = re.sub(r"\b(\d+)\s?[-–]\s?(\d+)\b(?!-)", lambda m: f"{num_to_uz(int(m.group(1)))}dan {num_to_uz(int(m.group(2)))}gacha", t)
    # ordinals: 5-noyabr, 2-bosqich, 1-chi
    t = re.sub(r"\b(\d+)-(?:chi|nchi|inchi)?\s?(?=[^\W\d]|\s|$)",
               lambda m: ordinal_uz(int(m.group(1))) + " ", t)
    # decimals and percents
    t = re.sub(r"\b(\d+)[.,](\d+)\s?%", lambda m: _decimal(m.group(1), m.group(2)) + " foiz", t)
    t = re.sub(r"\b(\d+)\s?%", lambda m: num_to_uz(int(m.group(1))) + " foiz", t)
    t = re.sub(r"\b(\d+)[.,](\d+)\b", lambda m: _decimal(m.group(1), m.group(2)), t)
    t = re.sub(r"(?<![\w-])-(\d+)\b", lambda m: "minus " + _int_words(m.group(1)), t)
    t = re.sub(r"\d+", lambda m: _int_words(m.group(0)), t)
    return t


def _date(d: str, m: str, y: str) -> str:
    try:
        di, mi, yi = int(d), int(m), int(y)
        if not (1 <= mi <= 12 and 1 <= di <= 31):
            raise ValueError
    except ValueError:
        return f"{d} {m} {y}"
    return f"{ordinal_uz(yi)} yil {ordinal_uz(di)} {_MONTHS[mi - 1]}"


# ------------------------------------------------------------------ 5. apostrophes
def normalize_uzbek(text: str) -> str:
    """Correct apostrophes so the neural voice pronounces oʻ / gʻ / tutuq belgisi properly."""
    t = re.sub(r"([oOgG])['’`‘ʼ´]", lambda m: m.group(1) + "ʻ", text)
    t = re.sub(r"(\w)['’`´](\w)", r"\1ʼ\2", t)
    return t


def prepare_uz(text: str, custom_lexicon: dict | None = None, numbers: bool = True) -> str:
    t = cyr_to_lat(text) if any(ch in UZ_CYR for ch in text) else text
    t = normalize_uzbek(t)
    t = apply_lexicon(t, custom_lexicon)
    if numbers:
        t = numbers_to_uz(t)
    for k, v in _SYMBOLS.items():
        t = t.replace(k, v)
    t = normalize_uzbek(t)
    return re.sub(r"\s+", " ", t).strip()


# ------------------------------------------------------------------ multilingual segmentation
def split_segments(text: str, base: str) -> list[tuple[str, str]]:
    """[(lang, text)] — consecutive sentences in the same language are merged."""
    sents = [s for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    segs: list[list[str]] = []
    for s in sents:
        cyr = sum(1 for ch in s if "Ѐ" <= ch <= "ӿ")
        lat = sum(1 for ch in s if ch.isascii() and ch.isalpha())
        if any(ch in UZ_CYR for ch in s):
            lang = "uz"
        elif cyr > lat:
            lang = "ru"
        elif base == "ru" and lat > cyr:
            lang = detect_language(s)
        elif base == "uz" and len(s) > 25 and detect_language(s) == "en" and \
                len(re.findall(r"\b(the|and|is|are|you|with|this|that)\b", s.lower())) >= 2:
            lang = "en"
        else:
            lang = base if base != "ru" else detect_language(s)
        if segs and segs[-1][0] == lang:
            segs[-1][1] += " " + s
        else:
            segs.append([lang, s])
    return [(lang, s) for lang, s in segs] or [(base, text)]


# ------------------------------------------------------------------ config helpers
def _num(v, default: int) -> int:
    m = re.search(r"-?\d+", str(v if v is not None else ""))
    return int(m.group(0)) if m else default


def edge_params(cfg: dict) -> dict:
    rate = max(-50, min(100, _num(cfg.get("rate"), 0)))
    pitch = max(-50, min(50, _num(cfg.get("pitch"), 0)))
    vol = max(-50, min(50, _num(cfg.get("volume"), 0)))
    return {"rate": f"{rate:+d}%", "pitch": f"{pitch:+d}Hz", "volume": f"{vol:+d}%"}


DEFAULT_VOICE = {"uz": "uz-UZ-SardorNeural", "ru": "ru-RU-DmitryNeural", "en": "en-US-AndrewNeural"}
_last_cleanup = 0.0


def _cleanup_audio(max_age_h: float = 48, keep: int = 400) -> None:
    global _last_cleanup
    if time.time() - _last_cleanup < 600:
        return
    _last_cleanup = time.time()
    files = sorted(AUDIO_DIR.glob("*.mp3"), key=lambda p: p.stat().st_mtime, reverse=True)
    for i, p in enumerate(files):
        try:
            if i >= keep or time.time() - p.stat().st_mtime > max_age_h * 3600:
                p.unlink()
        except OSError:
            pass


async def _edge(text: str, voice: str, prm: dict) -> bytes:
    import edge_tts
    buf = bytearray()
    comm = edge_tts.Communicate(text, voice, rate=prm["rate"], pitch=prm["pitch"], volume=prm["volume"], proxy=_proxy())
    async for chunk in comm.stream():
        if chunk["type"] == "audio":
            buf.extend(chunk["data"])
    if not buf:
        raise RuntimeError("Edge TTS bo'sh audio qaytardi")
    return bytes(buf)


async def _openai(text: str, cfg: dict, key: str, lang: str) -> bytes:
    model = cfg.get("openai_model") or "tts-1"
    body = {"model": model, "voice": cfg.get("openai_voice", "onyx"), "input": text,
            "speed": round(max(0.5, min(2.0, 1 + _num(cfg.get("rate"), 0) / 100)), 2)}
    if model.startswith("gpt-4o"):
        body["instructions"] = cfg.get("openai_instructions") or {
            "uz": "Adabiy oʻzbek tilida, Toshkent talaffuzida, tabiiy va iliq ohangda gapir. oʻ, gʻ, q, x, h tovushlarini aniq ayt.",
            "ru": "Говори на естественном русском, спокойно и дружелюбно.",
        }.get(lang, "Speak naturally, warm and clear.")
    async with httpx.AsyncClient(timeout=90) as c:
        r = await c.post("https://api.openai.com/v1/audio/speech", headers={"Authorization": f"Bearer {key}"}, json=body)
        r.raise_for_status()
        return r.content


def prepare_text(text: str, lang: str, cfg: dict) -> str:
    if lang == "uz":
        return prepare_uz(text, cfg.get("lexicon") or {}, cfg.get("speak_numbers", True))
    return text


def _proxy() -> str | None:
    """edge-tts (aiohttp) ignores HTTPS_PROXY by itself — needed on hosts like PythonAnywhere free plan."""
    import os
    return os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or None


async def synthesize(text: str, voice_cfg: dict, openai_key: str = "", lang: str | None = None) -> dict:
    cfg = voice_cfg or {}
    text = clean_for_speech(text, bool(cfg.get("read_code")), int(cfg.get("max_chars") or 3000))
    if not text:
        return {"file": None, "lang": lang or "uz", "engine": "none", "text": ""}
    forced = cfg.get("speak_language") if cfg.get("speak_language") in ("uz", "ru", "en") else None
    lang = lang or forced or detect_language(text)
    engine = cfg.get("tts_engine", "edge")
    if engine == "openai" and not openai_key:
        engine = "edge"
    if engine == "browser":
        return {"file": None, "lang": lang, "engine": "browser", "text": prepare_text(text, lang, cfg)}

    segs = split_segments(text, lang) if cfg.get("multilingual", True) and not forced else [(lang, text)]
    segs = [(lg, prepare_text(s, lg, cfg)) for lg, s in segs]
    prm = edge_params(cfg)
    voices = {lg: cfg.get(f"voice_{lg}") or DEFAULT_VOICE.get(lg, DEFAULT_VOICE["en"]) for lg in ("uz", "ru", "en")}
    sig = repr((engine, segs, prm, voices, cfg.get("openai_voice"), cfg.get("openai_model"), cfg.get("openai_instructions")))
    name = hashlib.sha1(sig.encode()).hexdigest()[:24] + ".mp3"
    out = AUDIO_DIR / name
    spoken = " ".join(s for _, s in segs)
    if out.exists() and out.stat().st_size > 0:
        out.touch()
        return {"file": name, "lang": lang, "engine": engine, "voice": voices.get(lang), "cached": True, "spoken": spoken}
    _cleanup_audio()
    parts: list[bytes] = []
    used = engine
    for lg, s in segs:
        try:
            if engine == "openai":
                parts.append(await _openai(s, cfg, openai_key, lg))
            else:
                parts.append(await _edge(s, voices.get(lg, DEFAULT_VOICE["en"]), prm))
        except Exception:
            if engine == "openai":     # OpenAI down / quota → free neural voice
                used = "edge"
                parts.append(await _edge(s, voices.get(lg, DEFAULT_VOICE["en"]), prm))
            else:      # chosen voice may have been retired → default voice
                parts.append(await _edge(s, DEFAULT_VOICE.get(lg, DEFAULT_VOICE["en"]), prm))
    await asyncio.to_thread(out.write_bytes, b"".join(parts))   # MP3 frames concatenate cleanly
    return {"file": name, "lang": lang, "engine": used, "voice": voices.get(lang), "segments": len(segs), "spoken": spoken}


# ------------------------------------------------------------------ voice catalogue
EDGE_VOICES = {
    "uz": ["uz-UZ-SardorNeural", "uz-UZ-MadinaNeural"],
    "ru": ["ru-RU-DmitryNeural", "ru-RU-SvetlanaNeural"],
    "en": ["en-US-AndrewNeural", "en-US-AvaNeural", "en-US-GuyNeural", "en-US-AriaNeural", "en-US-BrianNeural",
           "en-US-EmmaNeural", "en-US-JennyNeural", "en-GB-RyanNeural", "en-GB-SoniaNeural",
           "en-US-AndrewMultilingualNeural", "en-US-AvaMultilingualNeural"],
}
OPENAI_VOICES = ["alloy", "ash", "ballad", "coral", "echo", "fable", "onyx", "nova", "sage", "shimmer", "verse"]
OPENAI_MODELS = ["tts-1", "tts-1-hd", "gpt-4o-mini-tts"]
_catalog: dict | None = None
_catalog_at = 0.0


async def voice_catalog() -> dict:
    """Live list of Edge neural voices (uz / ru / en + multilingual), with gender; cached (offline → retry in 10 min)."""
    global _catalog, _catalog_at
    if _catalog and (_catalog.get("_live") or time.time() - _catalog_at < 600):
        return {k: v for k, v in _catalog.items() if k != "_live"} | {"openai": OPENAI_VOICES, "openai_models": OPENAI_MODELS}
    out = {lg: [{"id": v, "gender": "Female" if any(x in v for x in ("Madina", "Svetlana", "Ava", "Aria", "Emma", "Jenny", "Sonia")) else "Male"}
                for v in vs] for lg, vs in EDGE_VOICES.items()}
    try:
        import edge_tts
        allv = await asyncio.wait_for(edge_tts.list_voices(proxy=_proxy()), 8)
        live = {"uz": [], "ru": [], "en": []}
        for v in allv:
            loc, sn = v.get("Locale", ""), v.get("ShortName", "")
            lg = loc[:2]
            if lg in live and (lg != "en" or loc in ("en-US", "en-GB", "en-AU") or "Multilingual" in sn):
                live[lg].append({"id": sn, "gender": v.get("Gender", "")})
        if all(live.values()):
            out = {**live, "_live": True}
    except Exception:
        pass
    _catalog, _catalog_at = out, time.time()
    return {k: v for k, v in out.items() if k != "_live"} | {"openai": OPENAI_VOICES, "openai_models": OPENAI_MODELS}
