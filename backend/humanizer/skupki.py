import re
import hashlib
import time
from typing import Optional, Tuple

SKUPKA_KEYWORDS = [
    'скуп', 'skup', 'продаж', 'покупа', 'куплю', 'продам',
    'robux', 'робукс', 'korblox', 'корблокс', 'headless', 'хедлес',
    'rap', 'рап', 'лимитед', 'limited', 'gamepass', 'геймпас',
    'кук', 'cookie', 'acc', 'акк', 'аккаунт', 'account',
    'скупаю', 'продаю', 'меняю', 'обмен', 'trade',
    'написать', 'тык', 'связь', 'лс', 'dm', 'pm'
]

SKUPKA_PATTERNS = [
    r'\d+\s*[$₽руб]',
    r'[$₽]\s*\d+',
    r'\d+%',
    r't\.me/',
    r'@\w+',
    r'отзыв',
    r'гарант',
    r'прайс',
    r'курс'
]


def is_skupka(text: str) -> Tuple[bool, float]:
    text_lower = text.lower()
    
    keyword_count = sum(1 for kw in SKUPKA_KEYWORDS if kw in text_lower)
    pattern_count = sum(1 for p in SKUPKA_PATTERNS if re.search(p, text_lower))
    
    has_prices = bool(re.search(r'\d+\s*[$₽руб]|\d+%|курс', text_lower))
    has_links = bool(re.search(r't\.me/|@\w{3,}', text_lower))
    has_trade_words = any(w in text_lower for w in ['скуп', 'прода', 'покуп', 'купл', 'меняю'])
    
    score = 0
    if keyword_count >= 3:
        score += 30
    if pattern_count >= 2:
        score += 25
    if has_prices:
        score += 20
    if has_links:
        score += 15
    if has_trade_words:
        score += 20
    if len(text) > 200:
        score += 10
    
    return (score >= 50, score / 100)


def extract_prices(text: str) -> dict:
    prices = {}
    text_lower = text.lower()
    
    korblox = re.search(r'korblox|корблокс|крб[^\w]*(\d+[-\d]*)\s*[$₽]?', text_lower)
    if korblox:
        prices['korblox'] = korblox.group(1) if korblox.lastindex else re.search(r'(\d+[-\d]*)\s*[$₽]', text_lower[korblox.start():korblox.start()+50])
    
    headless = re.search(r'headless|хедлес[^\w]*(\d+[-\d]*)\s*[$₽]?', text_lower)
    if headless:
        prices['headless'] = headless.group(1) if headless.lastindex else None
    
    for pattern in [
        r'korblox[^\d]*(\d+[-\d+]*)\s*[$₽]',
        r'корблокс[^\d]*(\d+[-\d+]*)\s*[$₽]',
        r'headless[^\d]*(\d+[-\d+]*)\s*[$₽]',
        r'хедлес[^\d]*(\d+[-\d+]*)\s*[$₽]',
        r'robux[^\d]*(\d+[.,]?\d*)\s*[$₽]',
        r'(\d+[.,]?\d*)\s*[$₽]\s*за\s*1?к',
    ]:
        match = re.search(pattern, text_lower)
        if match:
            key = pattern.split('[')[0].replace('\\', '')
            if key not in prices:
                prices[key] = match.group(1)
    
    return prices


def extract_keywords(text: str) -> str:
    text_lower = text.lower()
    
    items = []
    if 'korblox' in text_lower or 'корблокс' in text_lower or 'крб' in text_lower:
        items.append('korblox')
    if 'headless' in text_lower or 'хедлес' in text_lower or 'хэдлес' in text_lower:
        items.append('headless')
    if 'robux' in text_lower or 'робукс' in text_lower or ' рб ' in text_lower:
        items.append('robux')
    if 'limited' in text_lower or 'лимитед' in text_lower or 'лим ' in text_lower:
        items.append('limited')
    if 'cookie' in text_lower or 'кук' in text_lower:
        items.append('cookie')
    if 'rap' in text_lower or 'рап' in text_lower:
        items.append('rap')
    if 'gamepass' in text_lower or 'геймпас' in text_lower:
        items.append('gamepass')
    if 'acc' in text_lower or 'акк' in text_lower or 'аккаунт' in text_lower:
        items.append('account')
    
    if '2fa' in text_lower or '2фа' in text_lower or 'двухфактор' in text_lower:
        items.append('2fa_bypass')
    if 'bypass' in text_lower or 'байпас' in text_lower or 'обход' in text_lower:
        items.append('bypass')
    if 'вьетнам' in text_lower or 'vietnam' in text_lower:
        items.append('vietnam')
    if 'вериф' in text_lower or 'verif' in text_lower:
        items.append('verification')
    if 'гарант' in text_lower:
        items.append('garant')
    if 'mm2' in text_lower or 'murder mystery' in text_lower:
        items.append('mm2')
    if 'adopt me' in text_lower or 'адопт' in text_lower:
        items.append('adopt_me')
    if 'blade ball' in text_lower or 'блейд болл' in text_lower:
        items.append('blade_ball')
    if 'bee swarm' in text_lower or 'пчёл' in text_lower or 'пчел' in text_lower:
        items.append('bee_swarm')
    if 'pet sim' in text_lower or 'psx' in text_lower:
        items.append('pet_sim')
    
    action = ''
    if any(w in text_lower for w in ['скупаю', 'куплю', 'покупаю', 'беру']):
        action = 'buying'
    elif any(w in text_lower for w in ['продаю', 'продам', 'продажа']):
        action = 'selling'
    elif any(w in text_lower for w in ['меняю', 'обмен', 'trade']):
        action = 'trading'
    
    prices = extract_prices(text)
    price_str = []
    for k, v in prices.items():
        if v:
            price_str.append(f"{k}:{v}")
    
    result = []
    if action:
        result.append(action)
    result.extend(items)
    if price_str:
        result.append('prices:' + '|'.join(price_str))
    
    return ','.join(result) if result else 'other'


def get_skupka_hash(text: str) -> str:
    clean = re.sub(r'\s+', '', text.lower())
    clean = re.sub(r'[^\w]', '', clean)
    return hashlib.md5(clean[:200].encode()).hexdigest()[:16]


def clean_premium_emoji(text: str) -> str:
    clean = re.sub(r'[🔤🔠🔣🔢🔡*️⃣#️⃣0️⃣1️⃣2️⃣3️⃣4️⃣5️⃣6️⃣7️⃣8️⃣9️⃣🔟]+', '', text)
    clean = re.sub(r'➖+|➕+|🔷+|🔶+|🔹+|🔺+|🔻+|◻+|◼+|▪+|▫+', ' ', clean)
    clean = re.sub(r'\s+', ' ', clean).strip()
    return clean


def is_readable(text: str) -> bool:
    clean = clean_premium_emoji(text)
    if len(clean) < 20:
        return False
    
    words = re.findall(r'[a-zA-Zа-яА-ЯёЁ]{3,}', clean)
    return len(words) >= 5


async def parse_skupka_with_vision(client, ai_client, vision_model: str, message) -> Optional[str]:
    try:
        if not message.photo:
            return None
        
        photo = await message.download_media(bytes)
        if not photo:
            return None
        
        result = await ai_client.chat_with_image(
            vision_model,
            [{"role": "user", "content": "Прочитай текст на картинке. Напиши ТОЛЬКО текст, без описаний."}],
            photo
        )
        
        return result if result and len(result) > 20 else None
    except:
        return None


def format_skupka_for_user(skupka: dict) -> str:
    username = skupka.get('username', '?')
    keywords = skupka.get('keywords', '')
    ts = skupka.get('timestamp', 0)
    
    age = ""
    if ts:
        diff = int(time.time()) - ts
        if diff < 3600:
            age = f"{diff // 60}м"
        elif diff < 86400:
            age = f"{diff // 3600}ч"
        else:
            age = f"{diff // 86400}д"
    
    items = []
    if 'robux' in keywords:
        items.append('робуксы')
    if 'korblox' in keywords:
        items.append('корблокс')
    if 'headless' in keywords:
        items.append('хедлес')
    if 'limited' in keywords:
        items.append('лимитеды')
    if 'cookie' in keywords:
        items.append('куки')
    if 'account' in keywords:
        items.append('аккаунты')
    if 'mm2' in keywords:
        items.append('MM2')
    if 'adopt_me' in keywords:
        items.append('Adopt Me')
    if 'blade_ball' in keywords:
        items.append('Blade Ball')
    if 'bee_swarm' in keywords:
        items.append('Bee Swarm')
    if 'pet_sim' in keywords:
        items.append('Pet Sim')
    
    extras = []
    if '2fa_bypass' in keywords or 'bypass' in keywords:
        extras.append('байпас')
    if 'vietnam' in keywords:
        extras.append('вьетнам')
    if 'garant' in keywords:
        extras.append('гарант')
    
    action = ""
    if 'buying' in keywords:
        action = "скупает"
    elif 'selling' in keywords:
        action = "продаёт"
    elif 'trading' in keywords:
        action = "меняет"
    else:
        action = "торгует"
    
    prices_match = re.search(r'prices:([^,]+)', keywords)
    price_info = ""
    if prices_match:
        price_parts = prices_match.group(1).split('|')
        price_info = " (" + ", ".join(price_parts[:3]) + ")"
    
    what = ', '.join(items) if items else 'разное'
    extra_str = f" +{', '.join(extras)}" if extras else ""
    
    return f"@{username} — {action} {what}{extra_str}{price_info} [{age}]"


def check_skupka_cooldown(last_skupka: dict, rules: str) -> Tuple[bool, int]:
    if not last_skupka:
        return (False, 0)
    
    cooldown_minutes = 30
    
    patterns = [
        r'скупк[аи]\s*(?:раз в|каждые?)\s*(\d+)\s*(мин|час|ч)',
        r'рассылк[аи]\s*(?:раз в|каждые?)\s*(\d+)\s*(мин|час|ч)',
        r'(\d+)\s*(мин|час|ч).*скупк',
        r'(\d+)\s*(мин|час|ч).*рассылк'
    ]
    
    rules_lower = rules.lower() if rules else ""
    for pattern in patterns:
        match = re.search(pattern, rules_lower)
        if match:
            num = int(match.group(1))
            unit = match.group(2)
            if 'час' in unit or unit == 'ч':
                cooldown_minutes = num * 60
            else:
                cooldown_minutes = num
            break
    
    last_ts = last_skupka.get('timestamp', 0)
    elapsed = int(time.time()) - last_ts
    cooldown_seconds = cooldown_minutes * 60
    
    if elapsed < cooldown_seconds:
        remaining = cooldown_seconds - elapsed
        return (True, remaining)
    
    return (False, 0)

