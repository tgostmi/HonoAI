from datetime import datetime, timedelta
import pytz
import re

MSK = pytz.timezone('Europe/Moscow')


def get_msk_now() -> datetime:
    return datetime.now(MSK)


def parse_time_manual(text: str) -> tuple[int, str]:
    text_lower = text.lower()
    
    if not any(kw in text_lower for kw in ['напомни', 'напиши', 'через', 'в ']):
        return 0, ""
    
    if 'через минутку' in text_lower or 'через минуту' in text_lower:
        return 1, extract_topic(text)
    
    if 'через полчаса' in text_lower:
        return 30, extract_topic(text)
    
    if 'через час' in text_lower:
        return 60, extract_topic(text)
    
    if 'через пару часов' in text_lower or 'через 2 часа' in text_lower:
        return 120, extract_topic(text)
    
    match = re.search(r'через\s+(\d+)\s*(мин|час|ч\.?|м\.?|секунд|сек)', text_lower)
    if match:
        num = int(match.group(1))
        unit = match.group(2)
        if 'час' in unit or unit.startswith('ч'):
            return num * 60, extract_topic(text)
        elif 'сек' in unit:
            return 1, extract_topic(text)
        return num, extract_topic(text)
    
    match = re.search(r'(?:в|к)\s+(\d{1,2})[:\.](\d{2})', text_lower)
    if match:
        hour = int(match.group(1))
        minute = int(match.group(2))
        now = get_msk_now()
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        diff = (target - now).total_seconds() / 60
        return max(1, int(diff)), extract_topic(text)
    
    return 0, ""


def extract_topic(text: str) -> str:
    patterns = [
        r'(?:напомни|напиши).*?(?:о том что|про то что|что)\s+(.+)',
        r'(?:напомни|напиши).*?про\s+(.+)',
        r'(?:напомни|напиши).*?о\s+(.+)',
    ]
    for p in patterns:
        match = re.search(p, text.lower())
        if match:
            return match.group(1).strip()
    return ""


def parse_reminder_time(message: str) -> tuple[int, str]:
    return parse_time_manual(message)


def needs_ai_parsing(message: str) -> bool:
    mins, _ = parse_time_manual(message)
    if mins > 0:
        return False
    keywords = ['напомни', 'напиши мне через', 'напиши через', 'напиши в ']
    return any(kw in message.lower() for kw in keywords)


PARSE_PROMPT = """Извлеки время из сообщения. Ответь СТРОГО в формате:
+МИНУТЫ (например +10, +60) или HH:MM (например 16:40) или НЕТ

Сообщение: {message}
Сейчас: {current_time}
Ответ:"""


async def parse_reminder_ai(ai_client, model: str, message: str) -> tuple[int, str]:
    try:
        now = get_msk_now()
        prompt = PARSE_PROMPT.format(message=message[:150], current_time=now.strftime('%H:%M'))
        
        result = await ai_client.chat(model, [{"role": "user", "content": prompt}], retries=1, max_tokens=10)
        response = result.get("content", "").strip() if isinstance(result, dict) else str(result).strip()
        
        if not response or "НЕТ" in response.upper():
            return 0, ""
        
        topic = extract_topic(message)
        
        if response.startswith('+'):
            mins = int(response[1:].split()[0])
            return max(1, min(mins, 1440)), topic
        
        if ':' in response:
            parts = response.replace(' ', '').split(':')
            hour, minute = int(parts[0][-2:]), int(parts[1][:2])
            target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if target <= now:
                target += timedelta(days=1)
            return max(1, int((target - now).total_seconds() / 60)), topic
        
        return 0, ""
    except:
        return 0, ""


def get_send_timestamp(minutes_from_now: int) -> int:
    now = get_msk_now()
    target = now + timedelta(minutes=minutes_from_now)
    return int(target.timestamp())


def format_time_msk(timestamp: int) -> str:
    dt = datetime.fromtimestamp(timestamp, MSK)
    return dt.strftime('%H:%M')

