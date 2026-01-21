from datetime import datetime
import time
import random

PERSONAL_EVENTS = [
    "только проснулась",
    "ем",
    "смотрю сериал",
    "лежу в кровати",
    "пью чай",
    "слушаю музыку",
    "скучаю",
    "ничего не делаю",
    "залипаю в телефон",
]

VOICE_EXCUSES = [
    "лень слушать, напиши текстом",
    "не могу сейчас слушать, напиши",
    "голосовые не люблю, пиши текстом",
    "ааа голосовое, напиши лучше",
    "слушать лень, че там?",
    "не, напиши словами",
]


def get_time_context(last_seen: int = 0) -> str:
    if last_seen:
        pause = time.time() - last_seen
        if pause < 3600:
            return ""
    
    hour = datetime.now().hour
    
    if 0 <= hour < 6:
        return "Сейчас глубокая ночь. Ты сонная, отвечай коротко и можешь спросить 'чё не спишь?'"
    elif 6 <= hour < 9:
        return "Раннее утро. Ты только проснулась, немного сонная."
    
    return ""


def get_pause_reaction(last_seen: int) -> str:
    if not last_seen:
        return ""
    
    pause = time.time() - last_seen
    hours = pause / 3600
    
    if hours > 48:
        return "Он давно не писал. Можешь спросить где пропадал."
    elif hours > 12:
        return "Прошло много часов. Можешь сказать 'о, привет'."
    
    return ""


def get_personal_event() -> str:
    if random.random() > 0.08:
        return ""
    return random.choice(PERSONAL_EVENTS)


def get_voice_excuse() -> str:
    return random.choice(VOICE_EXCUSES)


def should_use_caps() -> bool:
    return random.random() < 0.05


def add_caps_emotion(text: str) -> str:
    if not should_use_caps():
        return text
    
    caps_words = ["да", "нет", "что", "ааа", "ого", "вау", "блин", "ладно"]
    text_lower = text.lower()
    
    for word in caps_words:
        if word in text_lower and random.random() < 0.5:
            text = text.replace(word, word.upper(), 1)
            break
    
    return text


def fix_name_typos(text: str) -> str:
    import re
    typos = {
        r'\bХорно\b': 'Хоно',
        r'\bхорно\b': 'хоно',
        r'\bХона\b': 'Хоно',
        r'\bхона\b': 'хоно',
        r'\bХонно\b': 'Хоно',
        r'\bхонно\b': 'хоно',
        r'\bHorno\b': 'Hono',
        r'\bhorno\b': 'hono',
    }
    for pattern, replacement in typos.items():
        text = re.sub(pattern, replacement, text)
    return text


def remove_self_mention(text: str) -> str:
    import re
    patterns = [
        r'^@?HonoAI[:\s]*',
        r'^@?Hono_AI[:\s]*',
        r'^@?hono[:\s]*',
        r'^\[?Хоно\]?[:\s]*',
        r'^Я[:\s]+',
    ]
    for pattern in patterns:
        text = re.sub(pattern, '', text, flags=re.IGNORECASE)
    return text.strip()
