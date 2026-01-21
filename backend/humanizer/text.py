import random
import re

TYPO_MAP = {
    "привет": ["приветт", "прмвет", "привт"],
    "как дела": ["как делаа", "как дел"],
    "хорошо": ["хорошоо", "хрошо"],
    "нормально": ["нормас", "норм"],
    "спасибо": ["спс", "спасиб"],
    "пожалуйста": ["пожалуста", "пж"],
    "что": ["чт", "што", "чё"],
    "почему": ["почму", "поч"],
    "сейчас": ["щас", "ща"],
    "вообще": ["вобще", "ваще"],
}

SHORT_RESPONSES = [
    "ага", "угу", "ну", "да", "неа", "хз", "мб", "ок", "лан", "ясн", "понял", "ладн"
]

def add_typo(text: str) -> str:
    if random.random() > 0.15:
        return text
    
    text_lower = text.lower()
    for word, typos in TYPO_MAP.items():
        if word in text_lower:
            typo = random.choice(typos)
            if random.random() > 0.5:
                return text + f"\n{typo}*"
            else:
                pattern = re.compile(re.escape(word), re.IGNORECASE)
                return pattern.sub(typo, text, count=1)
    
    return text

def maybe_split_message(text: str) -> list:
    if len(text) < 60 or random.random() > 0.25:
        return [text]
    
    sentences = re.split(r'(?<=[.!?])\s+', text)
    
    if len(sentences) < 2:
        return [text]
    
    mid = len(sentences) // 2
    part1 = ' '.join(sentences[:mid])
    part2 = ' '.join(sentences[mid:])
    
    if part1 and part2:
        return [part1, part2]
    
    return [text]

def get_short_response() -> str:
    return random.choice(SHORT_RESPONSES)

def should_short_response(text: str) -> bool:
    short_triggers = ["ок", "понял", "ясно", "хорошо", "ладно", "да", "нет", "угу", "ага"]
    text_lower = text.lower().strip()
    
    if len(text_lower) < 15 and any(t in text_lower for t in short_triggers):
        return random.random() < 0.4
    
    return False

