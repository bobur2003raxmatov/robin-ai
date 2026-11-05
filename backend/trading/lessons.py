"""Trading Academy curriculum: from zero to advanced. Lesson content is generated/explained by the Trader agent;
this file defines structure, key points and quiz questions so progress can be tracked."""

CURRICULUM = [
    {"level": "Boshlang'ich", "lessons": [
        {"id": "b1", "title": "Trading nima? Bozorlar: Forex, Crypto, Stocks, Indekslar, Xomashyo",
         "points": ["Bozor ishtirokchilari", "Spot va derivativlar", "Bid/Ask va spred", "Likvidlik"],
         "quiz": [{"q": "Spred nima?", "a": "Bid va Ask narxlari orasidagi farq"}]},
        {"id": "b2", "title": "Yapon shamlari va taymfreymlar",
         "points": ["OHLC", "Tana va soya", "Taymfreymlar ierarxiyasi (MTF)"],
         "quiz": [{"q": "Shamning tanasi nimani bildiradi?", "a": "Ochilish va yopilish narxlari orasini"}]},
        {"id": "b3", "title": "Trend, Support va Resistance",
         "points": ["Higher high / higher low", "Daraja zonalari", "Breakout va retest"],
         "quiz": [{"q": "Ko'tariluvchi trend belgisi?", "a": "Yuqoriroq cho'qqilar va yuqoriroq tubliklar"}]},
        {"id": "b4", "title": "Risk menejmenti asoslari",
         "points": ["1% qoidasi", "Stop Loss majburiy", "R:R kamida 1:2", "Pozitsiya hajmini hisoblash"],
         "quiz": [{"q": "10000$ hisob, 1% risk, SL 50$ masofa — necha birlik?", "a": "2 birlik (100$/50$)"}]},
    ]},
    {"level": "O'rta", "lessons": [
        {"id": "i1", "title": "Indikatorlar: EMA, RSI, MACD, Bollinger, ATR",
         "points": ["Trend va momentum indikatorlari", "Divergensiya", "ATR asosida SL"],
         "quiz": [{"q": "RSI 70 dan yuqori nimani bildiradi?", "a": "Haddan tashqari sotib olinganlik"}]},
        {"id": "i2", "title": "Fibonacci va Price Action",
         "points": ["0.382 / 0.5 / 0.618 retracement", "Pin bar, engulfing, inside bar", "Konfluensiya"],
         "quiz": [{"q": "Oltin nisbat?", "a": "0.618"}]},
        {"id": "i3", "title": "Fundamental tahlil va iqtisodiy kalendar",
         "points": ["Foiz stavkalari", "CPI, NFP, GDP", "Yangiliklar paytida risk"],
         "quiz": [{"q": "NFP qaysi mamlakat ma'lumoti?", "a": "AQSH ish o'rinlari"}]},
        {"id": "i4", "title": "Trading psixologiyasi",
         "points": ["FOMO", "Revenge trading", "Jurnal yuritish", "Intizom"],
         "quiz": [{"q": "Zarardan keyin darhol katta pozitsiya ochish?", "a": "Revenge trading — xato"}]},
    ]},
    {"level": "Yuqori (Advanced)", "lessons": [
        {"id": "a1", "title": "Smart Money Concepts: BOS, CHoCH, Order Block, FVG, Likvidlik",
         "points": ["Bozor tuzilmasi", "Likvidlik ovlash", "Premium/Discount zonalar"],
         "quiz": [{"q": "CHoCH nima?", "a": "Bozor xarakterining (trend yo'nalishining) o'zgarishi"}]},
        {"id": "a2", "title": "Wyckoff, Elliott va harmonik patternlar",
         "points": ["Akkumulyatsiya/distribyutsiya", "Impuls va korreksiya to'lqinlari", "Gartley, Bat"],
         "quiz": [{"q": "Elliott impulsida nechta to'lqin?", "a": "5 ta"}]},
        {"id": "a3", "title": "Strategiya yaratish va backtesting",
         "points": ["Qoidalarni formallashtirish", "Look-ahead bias", "Overfitting", "Walk-forward"],
         "quiz": [{"q": "Overfitting nima?", "a": "Strategiyani tarixga haddan tashqari moslash"}]},
        {"id": "a4", "title": "Portfel boshqaruvi va korrelyatsiya",
         "points": ["Diversifikatsiya", "Korrelyatsiyalangan risk", "Drawdown boshqaruvi", "Kelly mezoni"],
         "quiz": [{"q": "Max drawdown nima?", "a": "Cho'qqidan eng katta pasayish foizi"}]},
    ]},
]


def find_lesson(lesson_id: str) -> dict | None:
    for lvl in CURRICULUM:
        for les in lvl["lessons"]:
            if les["id"] == lesson_id:
                return {**les, "level": lvl["level"]}
    return None
