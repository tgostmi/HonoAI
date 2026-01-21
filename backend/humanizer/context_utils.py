import re
import time
from datetime import datetime
from typing import Optional, Tuple, List

WEEKDAYS_RU = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
MONTHS_RU = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"]


def get_current_datetime_info() -> str:
    now = datetime.now()
    weekday = WEEKDAYS_RU[now.weekday()]
    month = MONTHS_RU[now.month - 1]
    hour = now.hour
    
    time_of_day = "ночь" if hour < 6 else "утро" if hour < 12 else "день" if hour < 18 else "вечер"
    
    return f"Сейчас: {now.day} {month} {now.year}, {weekday}, {now.strftime('%H:%M')} ({time_of_day})"


def detect_media_type(message) -> Optional[str]:
    if message.photo:
        return "[фото]"
    if message.sticker:
        emoji = message.sticker.alt or ""
        return f"[стикер {emoji}]"
    if message.voice:
        duration = message.voice.duration if hasattr(message.voice, 'duration') else 0
        return f"[голосовое {duration}сек]"
    if message.video_note:
        return "[видео-кружок]"
    if message.video:
        return "[видео]"
    if message.audio:
        return "[аудио]"
    if message.document:
        filename = message.document.attributes[0].file_name if message.document.attributes else "файл"
        return f"[файл: {filename[:30]}]"
    if message.geo:
        return "[геолокация]"
    if message.poll:
        return "[опрос]"
    if message.contact:
        return "[контакт]"
    return None


def extract_buttons(message) -> List[dict]:
    buttons = []
    reply_markup = getattr(message, 'reply_markup', None)
    if not reply_markup:
        return buttons
    
    rows = getattr(reply_markup, 'rows', None)
    if not rows:
        return buttons
    
    btn_num = 1
    for row in rows:
        for button in row.buttons:
            text = getattr(button, 'text', '')
            url = getattr(button, 'url', None)
            data = getattr(button, 'data', None)
            
            btn_info = {
                "num": btn_num,
                "text": text,
                "type": "url" if url else "callback" if data else "other"
            }
            if url:
                btn_info["url"] = url
            
            buttons.append(btn_info)
            btn_num += 1
    
    return buttons


def format_buttons_for_ai(buttons: List[dict]) -> str:
    if not buttons:
        return ""
    
    parts = []
    for btn in buttons:
        if btn["type"] == "url":
            parts.append(f"[🔗 {btn['text']}]")
        else:
            parts.append(f"[🔘 {btn['text']}]")
    
    return " ".join(parts)


def count_my_messages_in_row(context: list, my_username: str) -> int:
    if not context or not my_username:
        return 0
    
    count = 0
    my_username_lower = my_username.lower()
    
    for msg in reversed(context):
        username = msg.get('username', '')
        if username and username.lower() == my_username_lower:
            count += 1
        else:
            break
    
    return count


def extract_mentions(text: str, entities=None) -> List[str]:
    mentions = []
    
    pattern = r'@(\w+)'
    for match in re.finditer(pattern, text):
        mentions.append(match.group(1))
    
    if entities:
        from telethon.tl.types import MessageEntityMention, MessageEntityMentionName
        for entity in entities:
            if isinstance(entity, MessageEntityMention):
                mention = text[entity.offset:entity.offset + entity.length]
                if mention.startswith('@'):
                    mentions.append(mention[1:])
            elif isinstance(entity, MessageEntityMentionName):
                mentions.append(f"user_{entity.user_id}")
    
    return list(set(mentions))


def extract_links(text: str) -> List[str]:
    patterns = [
        r'https?://[^\s<>"{}|\\^`\[\]]+',
        r't\.me/[^\s<>"{}|\\^`\[\]]+',
        r'@[a-zA-Z][a-zA-Z0-9_]{3,}',
    ]
    
    links = []
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            links.append(match.group())
    
    return links


def get_chat_activity_info(context: list, hours: int = 1) -> str:
    if not context:
        return ""
    
    now = int(time.time())
    hour_ago = now - (hours * 3600)
    
    recent_count = sum(1 for msg in context if msg.get('timestamp', 0) > hour_ago)
    total = len(context)
    
    if recent_count > 20:
        return "Чат очень активен"
    elif recent_count > 10:
        return "Чат активен"
    elif recent_count > 3:
        return "Чат умеренно активен"
    elif recent_count > 0:
        return "Чат малоактивен"
    return ""


def get_relationship_stats(profile: dict) -> str:
    if not profile:
        return ""
    
    first_seen = profile.get('created_at') or profile.get('first_seen', 0)
    last_seen = profile.get('last_seen', 0)
    
    if not first_seen:
        return ""
    
    now = int(time.time())
    days_known = (now - first_seen) // 86400
    
    if days_known == 0:
        known_text = "знакомы сегодня"
    elif days_known == 1:
        known_text = "знакомы 1 день"
    elif days_known < 7:
        known_text = f"знакомы {days_known} дней"
    elif days_known < 30:
        weeks = days_known // 7
        known_text = f"знакомы {weeks} нед."
    else:
        months = days_known // 30
        known_text = f"знакомы {months} мес."
    
    return known_text


_online_cache = {}

def get_online_status_from_user(user) -> str:
    try:
        from telethon.tl.types import UserStatusOnline, UserStatusOffline, UserStatusRecently, UserStatusLastWeek, UserStatusLastMonth
        
        status = getattr(user, 'status', None)
        if not status:
            return ""
        
        if isinstance(status, UserStatusOnline):
            return "онлайн"
        elif isinstance(status, UserStatusRecently):
            return "был(а) недавно"
        elif isinstance(status, UserStatusOffline):
            if status.was_online:
                diff = int(time.time()) - status.was_online.timestamp()
                if diff < 300:
                    return "был(а) только что"
                elif diff < 3600:
                    return f"был(а) {diff // 60} мин назад"
                elif diff < 86400:
                    return f"был(а) {diff // 3600} ч назад"
            return "оффлайн"
        elif isinstance(status, UserStatusLastWeek):
            return "был(а) на этой неделе"
        elif isinstance(status, UserStatusLastMonth):
            return "был(а) в этом месяце"
        return ""
    except:
        return ""


async def get_online_status(client, user_id: int) -> str:
    now = int(time.time())
    cached = _online_cache.get(user_id)
    if cached and now - cached[1] < 60:
        return cached[0]
    
    try:
        user = await client.get_entity(user_id)
        result = get_online_status_from_user(user)
        _online_cache[user_id] = (result, now)
        return result
    except:
        return ""


def format_group_profile_brief(profile: dict) -> str:
    if not profile:
        return ""
    
    parts = []
    
    if profile.get('atmosphere'):
        parts.append(f"атмосфера: {profile['atmosphere'][:50]}")
    
    if profile.get('main_topics'):
        parts.append(f"темы: {profile['main_topics'][:50]}")
    
    if profile.get('communication_style'):
        parts.append(f"стиль: {profile['communication_style'][:30]}")
    
    if not parts:
        return ""
    
    return "О ЧАТЕ: " + "; ".join(parts)

