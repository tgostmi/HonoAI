import asyncio
import os
import json
import re
import time
from telethon import TelegramClient, events, functions
from telethon.errors import SessionPasswordNeededError
from telethon.tl.types import MessageEntityCustomEmoji, MessageEntityBold, MessageEntityCode, SendMessageTypingAction, ReactionCustomEmoji, InputStickerSetID
from telethon.tl.functions.messages import SendReactionRequest
from backend.ai import OpenRouterClient, get_models, get_vision_models, sort_models, format_price
from backend.database import SQLite, EmojiDB, UserDB, ReminderDB, StickerDB, GroupDB
from backend.database.memory import GlobalMemory, detect_reaction_type
from backend.humanizer import analyze_mood_ai, get_mood_prompt, update_mood, get_time_context, get_pause_reaction, maybe_split_message, should_short_response, get_short_response, parse_reminder_time, get_send_timestamp, format_time_msk, needs_ai_parsing, parse_reminder_ai, get_personal_event, get_voice_excuse, add_caps_emotion, remove_self_mention, should_respond_quick, should_respond_ai, get_group_system_prompt, parse_rules_response, parse_staff_response, parse_rules_ai, parse_staff_ai, wait_for_bot_response, get_join_greeting
from backend.humanizer.moderation import check_promotion, process_moderation, track_admin_action
from backend.humanizer.context_utils import get_current_datetime_info, detect_media_type, count_my_messages_in_row, extract_mentions, extract_links, get_chat_activity_info, get_relationship_stats, get_online_status, get_online_status_from_user, format_group_profile_brief, extract_buttons, format_buttons_for_ai
from backend.humanizer.learning import get_contextual_lessons, process_pending_interactions, quick_learn
from backend.tools import TOOLS, execute_tool


def utf16_len(text: str) -> int:
    return len(text.encode('utf-16-le')) // 2


def get_display_name(sender, sender_id: int) -> str:
    if sender:
        if sender.username:
            return sender.username
        name_parts = []
        if sender.first_name:
            name_parts.append(sender.first_name)
        if sender.last_name:
            name_parts.append(sender.last_name)
        if name_parts:
            return " ".join(name_parts)
    return f"user_{sender_id}"


DATA_DIR = "data"
SESSION_NAME = os.path.join(DATA_DIR, "hono_session")
CONFIG_FILE = "config.json"
PROMPT_FILE = os.path.join(DATA_DIR, "prompt.txt")

config = {}
ai_client = None
db = None
emoji_db = None
user_db = None
reminder_db = None
sticker_db = None
group_db = None
memory_db = None
last_bot_responses = {}
models_cache = {"free": [], "paid": [], "all": {}}
vision_models_cache = {"free": [], "paid": []}
chat_history = {}
system_prompt = ""
analyze_locks = {}
analyze_queue = {}
chat_queues = {}
chat_workers = {}
chat_locks = {}
bot_off_reason = None


def load_prompt():
    global system_prompt
    if os.path.exists(PROMPT_FILE):
        with open(PROMPT_FILE, "r", encoding="utf-8") as f:
            system_prompt = f.read().strip()
    else:
        system_prompt = "Ты дружелюбный помощник."


def load_config():
    global config, ai_client
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        config = json.load(f)
    if config.get("api_key"):
        ai_client = OpenRouterClient(config["api_key"])


async def init_db():
    global db, emoji_db, user_db, reminder_db, sticker_db, group_db
    db = SQLite(os.path.join(DATA_DIR, "database.db"))
    await db.connect()
    emoji_db = EmojiDB(db)
    await emoji_db.init_table()
    user_db = UserDB(db)
    await user_db.init_table()
    reminder_db = ReminderDB(db)
    await reminder_db.init_table()
    sticker_db = StickerDB(db)
    await sticker_db.init_table()
    group_db = GroupDB(os.path.join(DATA_DIR, "groups.db"))
    await group_db.init()
    
    global memory_db
    memory_db = GlobalMemory(os.path.join(DATA_DIR, "global_memory.db"))
    await memory_db.init()


def save_config():
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def is_admin(user_id: int) -> bool:
    return user_id in config.get("admins_ids", [])


async def login(client: TelegramClient):
    await client.connect()
    
    if await client.is_user_authorized():
        me = await client.get_me()
        print(f"Уже авторизован как: {me.first_name} (@{me.username})")
        return me
    
    phone = input("Введите номер телефона: ").strip()
    await client.send_code_request(phone)
    
    code = input("Введите код из Telegram: ").strip()
    
    try:
        await client.sign_in(phone, code)
    except SessionPasswordNeededError:
        password = input("Введите пароль 2FA: ").strip()
        await client.sign_in(password=password)
    
    me = await client.get_me()
    print(f"Успешный вход как: {me.first_name} (@{me.username})")
    return me


def extract_custom_emoji_entities(message):
    if not message.entities:
        return []
    
    custom_emojis = []
    for entity in message.entities:
        if isinstance(entity, MessageEntityCustomEmoji):
            custom_emojis.append(MessageEntityCustomEmoji(
                offset=entity.offset,
                length=entity.length,
                document_id=entity.document_id
            ))
    return custom_emojis


def utf16_to_python_index(text: str, utf16_offset: int) -> int:
    encoded = text.encode('utf-16-le')
    byte_offset = utf16_offset * 2
    return len(encoded[:byte_offset].decode('utf-16-le'))


def extract_emoji_with_id(message) -> list[tuple[str, int]]:
    if not message.entities:
        return []
    
    result = []
    text = message.message
    for entity in message.entities:
        if isinstance(entity, MessageEntityCustomEmoji):
            start = utf16_to_python_index(text, entity.offset)
            end = utf16_to_python_index(text, entity.offset + entity.length)
            emoji_char = text[start:end]
            result.append((emoji_char, entity.document_id))
    return result


def format_models_page(models: list, page: int, per_page: int = 10) -> tuple[str, int]:
    total_pages = max(1, (len(models) + per_page - 1) // per_page)
    start = page * per_page
    end = start + per_page
    page_models = models[start:end]
    
    lines = []
    for i, m in enumerate(page_models, start + 1):
        pricing = m.get("pricing", {})
        prompt_price = float(pricing.get("prompt", 0))
        compl_price = float(pricing.get("completion", 0))
        
        name = m.get("name", m["id"])
        model_id = m["id"]
        
        if prompt_price == 0 and compl_price == 0:
            price_str = "FREE"
        else:
            price_str = f"{format_price(prompt_price)}/{format_price(compl_price)}"
        
        lines.append(f"`{i}.` **{name}**\n    `{model_id}`\n    💰 {price_str}")
    
    return "\n\n".join(lines), total_pages


def format_vision_models_page(models: list, page: int, per_page: int = 8) -> tuple[str, int]:
    total_pages = max(1, (len(models) + per_page - 1) // per_page)
    start = page * per_page
    end = start + per_page
    page_models = models[start:end]
    
    lines = []
    for i, m in enumerate(page_models, start + 1):
        endpoint = m.get("endpoint", {})
        pricing = endpoint.get("pricing", {})
        prompt_price = float(pricing.get("prompt", 0))
        compl_price = float(pricing.get("completion", 0))
        
        name = m.get("short_name", m.get("name", m["slug"]))
        model_id = m["slug"]
        
        if prompt_price == 0 and compl_price == 0:
            price_str = "FREE"
        else:
            price_str = f"${prompt_price*1000000:.2f}/${compl_price*1000000:.2f}"
        
        lines.append(f"`{i}.` **{name}**\n    `{model_id}`\n    💰 {price_str}")
    
    return "\n\n".join(lines), total_pages


def get_chat_history(chat_id: int) -> list:
    if chat_id not in chat_history:
        chat_history[chat_id] = []
    return chat_history[chat_id]


def add_to_history(chat_id: int, role: str, content: str):
    history = get_chat_history(chat_id)
    history.append({"role": role, "content": content})
    if len(history) > 20:
        history.pop(0)
        history.pop(0)


def clear_history(chat_id: int):
    chat_history[chat_id] = []


_analyze_counter = {}

async def analyze_all(user_id: int, username: str, name: str, last_message: str, messages: list):
    global _analyze_counter
    
    _analyze_counter[user_id] = _analyze_counter.get(user_id, 0) + 1
    if _analyze_counter[user_id] % 3 != 0:
        return
    
    analyze_model = config.get("analyze_model")
    if not analyze_model or not ai_client:
        return
    
    if user_id not in analyze_locks:
        analyze_locks[user_id] = asyncio.Lock()
    
    async with analyze_locks[user_id]:
        print(f"[ANALYZE] Запуск для {user_id}")
        try:
            await analyze_user(user_id, username, name, messages)
            print(f"[ANALYZE] Завершено для {user_id}")
        except Exception as e:
            print(f"Ошибка analyze_all: {e}")


async def try_ai_reminder(user_id: int, chat_id: int, text: str):
    try:
        analyze_model = config.get("analyze_model")
        if not analyze_model or not ai_client:
            return
        
        mins, topic = await parse_reminder_ai(ai_client, analyze_model, text)
        if mins > 0 and topic:
            send_at = get_send_timestamp(mins)
            await reminder_db.add(user_id, chat_id, topic, send_at)
            print(f"[AI] Напоминание '{topic}' на {format_time_msk(send_at)} МСК")
    except Exception as e:
        print(f"Ошибка AI reminder: {e}")


async def analyze_user(user_id: int, username: str, name: str, messages: list):
    analyze_model = config.get("analyze_model")
    if not analyze_model or not ai_client:
        return
    
    profile = await user_db.get_profile(user_id)
    current_profile = profile["profile"] if profile else ""
    current_rel = profile["relationship"] if profile else 0
    current_topics = profile.get("topics", "") if profile else ""
    current_dates = profile.get("dates", "") if profile else ""
    
    recent = messages[-8:]
    if not any(m['role'] == 'user' for m in recent):
        return
    
    dialog_lines = []
    for m in recent:
        role = "Юзер" if m['role'] == 'user' else "Хоно"
        dialog_lines.append(f"{role}: {m['content'][:100]}")
    dialog_text = chr(10).join(dialog_lines)
    
    prev_info = ""
    if current_profile and current_profile != "нет":
        prev_info += f"Известные факты: {current_profile}\n"
    if current_topics and current_topics != "нет":
        prev_info += f"Известные интересы: {current_topics}\n"
    if current_dates and current_dates != "нет":
        prev_info += f"Известные даты: {current_dates}\n"
    
    combined_prompt = f"""Проанализируй диалог. Извлеки ТОЛЬКО то что ЮЗЕР сам написал о себе.

{f"УЖЕ ИЗВЕСТНО:{chr(10)}{prev_info}" if prev_info else ""}
ДИАЛОГ:
{dialog_text}

ОТВЕТЬ В ФОРМАТЕ (каждая строка отдельно):
ФАКТЫ: (имя, город, возраст - ТОЛЬКО если юзер СКАЗАЛ | иначе: нет)
ИНТЕРЕСЫ: (игры, хобби - ТОЛЬКО если юзер СКАЗАЛ "играю в", "люблю" | иначе: нет)
ДАТЫ: (ДР, события - ТОЛЬКО если юзер НАЗВАЛ дату | иначе: нет)
ОТНОШЕНИЕ: (число от -3 до 5)

ШКАЛА ОТНОШЕНИЙ:
-3 = оскорбляет | -1 = грубит | 1 = норм | 2 = вежливо | 3 = дружелюбно | 4+ = тепло/флирт
Текущее: {current_rel}

ВАЖНО:
- "привет", "го", "хз" = НЕ факты!
- Слова Хоно ИГНОРИРУЙ
- Сохраняй старые факты если они верны"""

    try:
        result = await ai_client.chat(analyze_model, [
            {"role": "system", "content": "Извлекай ТОЛЬКО факты которые юзер ПРЯМО написал. Не выдумывай!"},
            {"role": "user", "content": combined_prompt}
        ], retries=5, max_tokens=150)
        
        response = (result.get("content") or "") if isinstance(result, dict) else str(result)
        print(f"[ANALYZE {user_id}] {response[:150]}")
        
        if not response or response.startswith("Ошибка"):
            return
        
        lines = response.strip().split('\n')
        facts = ""
        interests = ""
        dates = ""
        rel_value = current_rel
        
        for line in lines:
            line_lower = line.lower()
            if line_lower.startswith("факты:"):
                facts = line.split(":", 1)[1].strip() if ":" in line else ""
            elif line_lower.startswith("интересы:"):
                interests = line.split(":", 1)[1].strip() if ":" in line else ""
            elif line_lower.startswith("даты:"):
                dates = line.split(":", 1)[1].strip() if ":" in line else ""
            elif line_lower.startswith("отношение:"):
                rel_str = ''.join(c for c in line if c.isdigit() or c == '-')
                if rel_str:
                    rel_value = int(rel_str)
        
        bad_words = ['хоно', 'бот', 'она', 'ии', 'ai', 'assistant']
        
        if facts and facts.lower() != "нет" and len(facts) > 3:
            if not any(bw in facts.lower() for bw in bad_words):
                await user_db.update_profile(user_id, facts[:120], username, name)
                print(f"[PROFILE] {user_id}: {facts[:50]}")
        
        if interests and interests.lower() != "нет" and len(interests) > 2:
            if not any(bw in interests.lower() for bw in bad_words):
                await user_db.update_topics(user_id, interests[:80])
                print(f"[INTERESTS] {user_id}: {interests[:40]}")
        
        if dates and dates.lower() != "нет" and len(dates) > 3:
            await user_db.update_dates(user_id, dates[:80])
            print(f"[DATES] {user_id}: {dates[:40]}")
        
        rel_value = max(-5, min(7, rel_value))
        if rel_value != current_rel:
            if rel_value > current_rel:
                smooth = min(current_rel + 1, rel_value)
            else:
                smooth = max(current_rel - 1, rel_value)
            await user_db.update_relationship(user_id, smooth)
            print(f"[REL] {user_id}: {current_rel} -> {smooth}")
            
    except Exception as e:
        print(f"[ANALYZE ERR] {e}")


def parse_markdown_entities(text: str) -> tuple[str, list]:
    from telethon.tl.types import MessageEntityBold, MessageEntityItalic, MessageEntityCode, MessageEntityPre
    
    entities = []
    result = text
    
    code_blocks = list(re.finditer(r'```(\w*)\n?([\s\S]*?)```', result))
    for match in reversed(code_blocks):
        lang = match.group(1) or ''
        code = match.group(2)
        start = match.start()
        result = result[:start] + code + result[match.end():]
        offset = utf16_len(result[:start])
        length = utf16_len(code)
        entities.append(MessageEntityPre(offset=offset, length=length, language=lang))
    
    inline_codes = list(re.finditer(r'`([^`]+)`', result))
    for match in reversed(inline_codes):
        code = match.group(1)
        start = match.start()
        result = result[:start] + code + result[match.end():]
        offset = utf16_len(result[:start])
        length = utf16_len(code)
        entities.append(MessageEntityCode(offset=offset, length=length))
    
    bolds = list(re.finditer(r'\*\*([^*]+)\*\*', result))
    for match in reversed(bolds):
        content = match.group(1)
        start = match.start()
        result = result[:start] + content + result[match.end():]
        offset = utf16_len(result[:start])
        length = utf16_len(content)
        entities.append(MessageEntityBold(offset=offset, length=length))
    
    italics = list(re.finditer(r'(?<!\*)\*([^*]+)\*(?!\*)', result))
    for match in reversed(italics):
        content = match.group(1)
        start = match.start()
        result = result[:start] + content + result[match.end():]
        offset = utf16_len(result[:start])
        length = utf16_len(content)
        entities.append(MessageEntityItalic(offset=offset, length=length))
    
    return result, entities


def parse_emoji_tags(text: str, emoji_map: dict, id_map: dict) -> tuple[str, list]:
    pattern = r'#(\d+)'
    
    text, md_entities = parse_markdown_entities(text)
    entities = list(md_entities)
    
    result = text
    offset_shift = 0
    
    for match in re.finditer(pattern, text):
        num = int(match.group(1))
        start = match.start() - offset_shift
        tag_len = len(match.group(0))
        
        if num in id_map:
            doc_id = id_map[num]
            emoji_char = emoji_map.get(doc_id, "")
            
            if emoji_char:
                result = result[:start] + emoji_char + result[start + tag_len:]
                
                emoji_offset = utf16_len(result[:start])
                emoji_length = utf16_len(emoji_char)
                
                entities.append(MessageEntityCustomEmoji(
                    offset=emoji_offset,
                    length=emoji_length,
                    document_id=doc_id
                ))
                
                offset_shift += tag_len - len(emoji_char)
            else:
                result = result[:start] + result[start + tag_len:]
                offset_shift += tag_len
        else:
            result = result[:start] + result[start + tag_len:]
            offset_shift += tag_len
    
    return result, entities


async def send_reaction(client, chat_id: int, msg_id: int, text: str, relationship: int = 0):
    import random
    
    if relationship < 2:
        if random.random() > 0.1:
            return
    elif relationship < 4:
        if random.random() > 0.3:
            return
    else:
        if random.random() > 0.5:
            return
    
    try:
        emojis = await emoji_db.get_all()
        if not emojis:
            return
        
        emoji = await pick_reaction_emoji(text, emojis)
        if not emoji:
            return
        
        await client(SendReactionRequest(
            peer=chat_id,
            msg_id=msg_id,
            reaction=[ReactionCustomEmoji(document_id=emoji['document_id'])]
        ))
        print(f"Реакция {emoji['emoji']} на сообщение {msg_id}")
    except Exception as e:
        print(f"Ошибка реакции: {e}")


async def handle_tool_calls(client, model: str, messages: list, tool_calls: list, emoji_list: str, system_prompt: str, on_join_callback=None, current_chat_id=None, sender_role=None, current_msg_id=None) -> str:
    import json
    
    emojis = await emoji_db.get_all() if emoji_db else []
    emoji_map = {e["document_id"]: e["emoji"] for e in emojis}
    _, id_map = await get_emojis_for_ai()
    
    async def send_with_emoji(entity, text):
        text = text.replace("\\n", "\n")
        final_text, entities = parse_emoji_tags(text, emoji_map, id_map)
        if entities:
            await client.send_message(entity, final_text, formatting_entities=entities)
        else:
            await client.send_message(entity, final_text, parse_mode='md')
    
    messages_with_tools = messages.copy()
    messages_with_tools.append({
        "role": "assistant",
        "content": None,
        "tool_calls": tool_calls
    })
    
    for tool_call in tool_calls:
        tool_name = tool_call["function"]["name"]
        try:
            arguments = json.loads(tool_call["function"]["arguments"])
        except:
            arguments = {}
        
        print(f"[TOOL] Вызов {tool_name}: {arguments}")
        
        analyze_model = config.get("analyze_model")
        owner_id = config.get("admin_ids", [None])[0]
        result = await execute_tool(
            client, tool_name, arguments,
            send_func=send_with_emoji,
            group_db=group_db,
            user_db=user_db,
            reminder_db=reminder_db,
            ai_client=ai_client,
            analyze_model=analyze_model,
            current_chat_id=current_chat_id,
            sender_role=sender_role,
            current_msg_id=current_msg_id,
            owner_id=owner_id
        )
        print(f"[TOOL] Результат: {result}")
        
        if tool_name == "join_group" and result.get("success") and result.get("group_id"):
            if on_join_callback:
                group_info = await group_db.get_group(result["group_id"]) if group_db else None
                has_rules = group_info.get("rules") if group_info else None
                has_staff = group_info.get("staff") if group_info else None
                print(f"[TOOL] join_group: has_rules={bool(has_rules)}, has_staff={bool(has_staff)}")
                if not has_rules or not has_staff:
                    print(f"[TOOL] Запускаю on_group_join для {result.get('group_title')}")
                    asyncio.create_task(on_join_callback(
                        result["group_id"],
                        result.get("group_title", "Unknown"),
                        result.get("username")
                    ))
                else:
                    print(f"[TOOL] Пропускаю on_group_join - rules и staff уже есть")
        
        messages_with_tools.append({
            "role": "tool",
            "tool_call_id": tool_call["id"],
            "content": json.dumps(result, ensure_ascii=False)
        })
    
    final_result = await ai_client.chat(model, messages_with_tools, tools=TOOLS)
    final_text = final_result.get("content", "") if isinstance(final_result, dict) else str(final_result)
    
    new_tool_calls = final_result.get("tool_calls") if isinstance(final_result, dict) else None
    if new_tool_calls:
        return await handle_tool_calls(client, model, messages_with_tools, new_tool_calls, emoji_list, system_prompt, on_join_callback, current_chat_id, sender_role, current_msg_id)
    
    return final_text


async def pick_reaction_emoji(text: str, emojis: list) -> dict:
    import random
    analyze_model = config.get("analyze_model")
    if not analyze_model or not ai_client or not emojis:
        return random.choice(emojis) if emojis else None
    
    emoji_list = "\n".join([f"#{i+1} {e['emoji']} — {e.get('description', '')}" for i, e in enumerate(emojis[:15])])
    
    prompt = f"""Выбери emoji-реакцию на сообщение.

СООБЩЕНИЕ: {text[:150]}

ДОСТУПНЫЕ EMOJI:
{emoji_list}

Правила:
- Выбери ОДНУ подходящую по смыслу реакцию
- ❤️ — для милых/романтичных сообщений
- 😂/👅 — для смешных
- 👍/💪 — для одобрения
- 😢 — для грустных
- Если ничего не подходит — напиши: нет

Ответь ТОЛЬКО номером (например: 3) или "нет":"""

    try:
        result = await ai_client.chat(analyze_model, [
            {"role": "system", "content": "Выбери подходящую реакцию. Ответь только номером."},
            {"role": "user", "content": prompt}
        ], retries=5, max_tokens=50)
        
        response = result.get("content", "").strip() if isinstance(result, dict) else str(result).strip()
        
        if "нет" in response.lower():
            return None
        
        import re
        match = re.search(r'\d+', response)
        if match:
            idx = int(match.group()) - 1
            if 0 <= idx < len(emojis):
                return emojis[idx]
        
        return random.choice(emojis)
    except:
        return random.choice(emojis) if emojis else None


async def maybe_send_sticker(client, chat_id: int, text: str, relationship: int = 0) -> bool:
    import random
    
    if relationship < 3:
        if random.random() > 0.05:
            return False
    else:
        if random.random() > 0.15:
            return False
    
    try:
        sticker = await sticker_db.get_by_keywords(text)
        if not sticker:
            sticker = await sticker_db.get_random()
        
        if sticker:
            await client.send_file(chat_id, sticker['file_id'])
            print(f"Отправлен стикер {sticker['id']}")
            return True
    except Exception as e:
        print(f"Ошибка стикера: {e}")
    
    return False


async def get_emojis_for_ai() -> tuple[str, dict]:
    emojis = await emoji_db.get_all()
    if not emojis:
        return "ЭМОДЗИ НЕТ - не используй никакие эмодзи!", {}
    
    lines = []
    id_map = {}
    for i, e in enumerate(emojis, 1):
        lines.append(f"#{i} — {e['description']}")
        id_map[i] = e['document_id']
    
    text = "ПРЕМИУМ ЭМОДЗИ (пиши #номер):\n" + "\n".join(lines)
    return text, id_map


async def main():
    global models_cache, vision_models_cache
    
    os.makedirs(DATA_DIR, exist_ok=True)
    load_config()
    load_prompt()
    await init_db()
    
    client = TelegramClient(SESSION_NAME, config["api_id"], config["api_hash"])
    me = await login(client)

    @client.on(events.NewMessage(pattern=r"^/help$", func=lambda e: e.is_private))
    async def help_handler(event):
        text = (
            "📚 **Список команд**\n\n"
            "**Основные:**\n"
            "`/help` — эта справка\n"
            "`/panel` — панель управления\n"
            "`/clear` — очистить свою историю\n"
            "`/reset_memory <id>` — сбросить историю\n"
            "`/info <id>` — инфо о юзере\n"
            "`/off <причина>` — выключить бота\n"
            "`/on` — включить бота\n\n"
            "**Модели:**\n"
            "`/models` — текстовые модели\n"
            "`/setmodel <id>` — основная\n"
            "`/set_alt_model <id>` — запасная\n"
            "`/set_analyze_model <id>` — анализ\n\n"
            "**Vision модели:**\n"
            "`/models_vision` — модели с картинками\n"
            "`/setvision <id>` — установить vision\n\n"
            "**Группы:**\n"
            "`/groups` — список групп\n"
            "`/groupinfo <номер>` — инфо о группе\n"
            "`/del_group <номер/all>` — удалить группу\n"
            "`/set_chat_analyze_models m1 m2...` — модели для чатов\n"
            "`/mod_status <номер>` — статус модерации\n"
            "`/set_mod <номер> <0-3>` — уровень модерации\n\n"
            "**Эмодзи:**\n"
            "`/emojis` — список эмодзи\n"
            "`/add_emoji {эмодзи} {описание}` — добавить\n"
            "`/del_emoji <номер>` — удалить\n\n"
            "**Напоминания:**\n"
            "`/reminders` — список напоминаний\n"
            "`/del_reminder <номер>` — удалить"
        )
        await event.respond(text)

    @client.on(events.NewMessage(pattern=r"^/panel$", func=lambda e: e.is_private))
    async def panel_handler(event):
        if not is_admin(event.sender_id):
            return
        
        current_model = config.get("selected_model", "не выбрана")
        alt_model = config.get("alt_model", "не выбрана")
        vision_model = config.get("selected_vision_model", "не выбрана")
        analyze_model = config.get("analyze_model", "не выбрана")
        
        balance_text = ""
        if ai_client:
            try:
                credits = await ai_client.get_credits()
                balance = credits["balance"]
                
                if balance > 0:
                    avg_cost = 0.0001
                    est_messages = int(balance / avg_cost)
                    
                    if est_messages > 1000000:
                        est_str = f"~{est_messages // 1000000}M+"
                    elif est_messages > 1000:
                        est_str = f"~{est_messages // 1000}K+"
                    else:
                        est_str = f"~{est_messages}"
                    
                    balance_text = f"💰 Баланс: **${balance:.4f}** ({est_str} сообщ.)\n\n"
                else:
                    balance_text = f"💰 Баланс: **${balance:.4f}** (0 сообщ.)\n\n"
            except:
                balance_text = "💰 Баланс: ошибка загрузки\n\n"
        
        text = (
            "⚙️ **Панель управления**\n\n"
            f"{balance_text}"
            f"🤖 Модель: `{current_model}`\n"
            f"🔄 Alt: `{alt_model}`\n"
            f"👁 Vision: `{vision_model}`\n"
            f"🧠 Анализ: `{analyze_model}`\n\n"
            "`/help` — все команды"
        )
        
        await event.respond(text)

    @client.on(events.NewMessage(pattern=r"^/models_vision", func=lambda e: e.is_private))
    async def models_vision_handler(event):
        global vision_models_cache
        if not is_admin(event.sender_id):
            return
        
        if not ai_client:
            await event.respond("❌ API ключ не настроен!")
            return
        
        args = event.raw_text.split()[1:] if len(event.raw_text.split()) > 1 else []
        
        if not vision_models_cache["free"] and not vision_models_cache["paid"]:
            msg = await event.respond("⏳ Загрузка vision моделей...")
            free, paid = await get_vision_models(ai_client)
            vision_models_cache = {"free": free, "paid": paid}
            await msg.delete()
        
        if not args:
            text = (
                "👁 **Vision модели**\n\n"
                f"🆓 Бесплатные: {len(vision_models_cache['free'])}\n"
                f"💰 Платные: {len(vision_models_cache['paid'])}\n\n"
                "**Команды:**\n"
                "`/models_vision free` — бесплатные\n"
                "`/models_vision paid` — платные\n"
                "`/models_vision free 2` — страница 2"
            )
            await event.respond(text)
            return
        
        category = args[0].lower()
        page = int(args[1]) - 1 if len(args) > 1 and args[1].isdigit() else 0
        
        if category not in ["free", "paid"]:
            await event.respond("❌ Используй: `/models_vision free` или `/models_vision paid`")
            return
        
        models = vision_models_cache.get(category, [])
        title = "🆓 **Бесплатные vision модели**" if category == "free" else "💰 **Платные vision модели**"
        
        if not models:
            await event.respond(f"{title}\n\nМоделей нет")
            return
        
        page = max(0, min(page, (len(models) - 1) // 8))
        models_text, total_pages = format_vision_models_page(models, page)
        
        nav = f"\n\n📄 Страница {page + 1}/{total_pages}"
        if total_pages > 1:
            nav += f"\n`/models_vision {category} <1-{total_pages}>`"
        
        text = f"{title}\nЦены за 1M токенов\n\n{models_text}{nav}"
        text += f"\n\n**Установить:** `/setvision <id>`"
        
        await event.respond(text)

    @client.on(events.NewMessage(pattern=r"^/models(?!_)", func=lambda e: e.is_private))
    async def models_handler(event):
        global models_cache
        if not is_admin(event.sender_id):
            return
        
        if not ai_client:
            await event.respond("❌ API ключ не настроен!")
            return
        
        args = event.raw_text.split()[1:] if len(event.raw_text.split()) > 1 else []
        
        if not models_cache["free"] and not models_cache["paid"]:
            msg = await event.respond("⏳ Загрузка моделей...")
            all_models, popular_paid, popular_free = await get_models(ai_client)
            free, paid = sort_models(all_models, popular_paid, popular_free)
            models_cache = {
                "free": free, 
                "paid": paid,
                "all": {m["id"]: m for m in all_models}
            }
            await msg.delete()
        
        if not args:
            text = (
                "🤖 **Выберите категорию**\n\n"
                f"🆓 Бесплатные: {len(models_cache['free'])}\n"
                f"💰 Платные: {len(models_cache['paid'])}\n\n"
                "**Команды:**\n"
                "`/models free` — бесплатные\n"
                "`/models paid` — платные\n"
                "`/models free 2` — страница 2"
            )
            await event.respond(text)
            return
        
        category = args[0].lower()
        page = int(args[1]) - 1 if len(args) > 1 and args[1].isdigit() else 0
        
        if category not in ["free", "paid"]:
            await event.respond("❌ Используй: `/models free` или `/models paid`")
            return
        
        models = models_cache.get(category, [])
        title = "🆓 **Бесплатные модели**" if category == "free" else "💰 **Платные модели**"
        
        if not models:
            await event.respond(f"{title}\n\nМоделей нет")
            return
        
        page = max(0, min(page, (len(models) - 1) // 10))
        models_text, total_pages = format_models_page(models, page)
        
        nav = f"\n\n📄 Страница {page + 1}/{total_pages}"
        if total_pages > 1:
            nav += f"\n`/models {category} <1-{total_pages}>`"
        
        text = f"{title}\nЦены за 1M токенов (вход/выход)\n\n{models_text}{nav}"
        text += f"\n\n**Установить:** `/setmodel <id>`"
        
        await event.respond(text)

    @client.on(events.NewMessage(pattern=r"^/setmodel", func=lambda e: e.is_private))
    async def setmodel_handler(event):
        if not is_admin(event.sender_id):
            return
        
        args = event.raw_text.split(maxsplit=1)
        if len(args) < 2:
            await event.respond("❌ Использование: `/setmodel <model_id>`")
            return
        
        model_id = args[1].strip()
        config["selected_model"] = model_id
        save_config()
        
        await event.respond(f"✅ Модель установлена:\n`{model_id}`")

    @client.on(events.NewMessage(pattern=r"^/setvision", func=lambda e: e.is_private))
    async def setvision_handler(event):
        if not is_admin(event.sender_id):
            return
        
        args = event.raw_text.split(maxsplit=1)
        if len(args) < 2:
            await event.respond("❌ Использование: `/setvision <model_id>`")
            return
        
        model_id = args[1].strip()
        config["selected_vision_model"] = model_id
        save_config()
        
        await event.respond(f"✅ Vision модель установлена:\n`{model_id}`")

    @client.on(events.NewMessage(pattern=r"^/set_alt_model", func=lambda e: e.is_private))
    async def set_alt_model_handler(event):
        if not is_admin(event.sender_id):
            return
        
        args = event.raw_text.split(maxsplit=1)
        if len(args) < 2:
            await event.respond("❌ Использование: `/set_alt_model <model_id>`")
            return
        
        model_id = args[1].strip()
        config["alt_model"] = model_id
        save_config()
        
        await event.respond(f"✅ Альтернативная модель установлена:\n`{model_id}`")

    @client.on(events.NewMessage(pattern=r"^/set_analyze_model", func=lambda e: e.is_private))
    async def set_analyze_model_handler(event):
        if not is_admin(event.sender_id):
            return
        
        args = event.raw_text.split(maxsplit=1)
        if len(args) < 2:
            await event.respond("❌ Использование: `/set_analyze_model <model_id>`")
            return
        
        model_id = args[1].strip()
        config["analyze_model"] = model_id
        save_config()
        
        await event.respond(f"✅ Модель анализа установлена:\n`{model_id}`")

    @client.on(events.NewMessage(pattern=r"^/set_chat_analyze_models", func=lambda e: e.is_private))
    async def set_chat_analyze_models_handler(event):
        if not is_admin(event.sender_id):
            return
        
        args = event.raw_text.split()[1:]
        if not args:
            current = config.get("chat_analyze_models", [])
            if current:
                lines = ["📋 **Модели для анализа чатов:**\n"]
                for i, m in enumerate(current, 1):
                    lines.append(f"{i}. `{m}`")
                await event.respond("\n".join(lines))
            else:
                await event.respond("❌ Модели не установлены\n\nИспользование:\n`/set_chat_analyze_models model1 model2 model3`")
            return
        
        models = [m.strip() for m in args if m.strip()]
        config["chat_analyze_models"] = models
        save_config()
        
        await event.respond(f"✅ Установлено {len(models)} моделей для анализа чатов:\n" + "\n".join([f"• `{m}`" for m in models]))

    @client.on(events.NewMessage(pattern=r"^/off", func=lambda e: e.is_private))
    async def off_handler(event):
        global bot_off_reason
        if not is_admin(event.sender_id):
            return
        
        args = event.raw_text.split(maxsplit=1)
        if len(args) < 2:
            await event.respond("❌ Использование: `/off причина выключения`")
            return
        
        reason = args[1].strip()
        bot_off_reason = reason
        await event.respond(f"🔴 Бот выключен\nПричина: {reason}\n\nДля включения: `/on`")

    @client.on(events.NewMessage(pattern=r"^/on$", func=lambda e: e.is_private))
    async def on_handler(event):
        global bot_off_reason
        if not is_admin(event.sender_id):
            return
        
        if bot_off_reason is None:
            await event.respond("✅ Бот уже включён")
            return
        
        old_reason = bot_off_reason
        bot_off_reason = None
        await event.respond(f"🟢 Бот включён!\nБыл выключен по причине: {old_reason}")

    @client.on(events.NewMessage(pattern=r"^/clear$", func=lambda e: e.is_private))
    async def clear_handler(event):
        clear_history(event.chat_id)
        await event.respond("🗑 История очищена")

    @client.on(events.NewMessage(pattern=r"^/reset_memory", func=lambda e: e.is_private))
    async def reset_memory_handler(event):
        if not is_admin(event.sender_id):
            return
        
        args = event.raw_text.split(maxsplit=1)
        if len(args) < 2:
            await event.respond(
                "❌ Использование:\n"
                "`/reset_memory <user_id>` - сбросить память об одном юзере\n"
                "`/reset_memory all` - сбросить ВСЮ память о пользователях\n\n"
                f"Активные чаты: {len(chat_history)}"
            )
            return
        
        arg = args[1].strip().lower()
        
        if arg == "all":
            count = await user_db.delete_all_profiles()
            chat_history.clear()
            await event.respond(f"✅ Удалено {count} профилей и очищена история всех чатов")
            return
        
        if not arg.lstrip('-').isdigit():
            await event.respond("❌ Укажите user_id (число) или 'all'")
            return
        
        user_id = int(arg)
        
        deleted_history = False
        deleted_profile = False
        
        if user_id in chat_history:
            del chat_history[user_id]
            deleted_history = True
        
        profile = await user_db.get_profile(user_id)
        if profile:
            await user_db.delete_profile(user_id)
            deleted_profile = True
        
        if deleted_history or deleted_profile:
            parts = []
            if deleted_history:
                parts.append("история")
            if deleted_profile:
                parts.append("профиль")
            await event.respond(f"✅ Удалено для `{user_id}`: {', '.join(parts)}")
        else:
            await event.respond(f"❌ Данные о `{user_id}` не найдены")

    @client.on(events.NewMessage(pattern=r"^/memory$", func=lambda e: e.is_private))
    async def memory_handler(event):
        if not is_admin(event.sender_id):
            return
        
        if not memory_db:
            await event.respond("❌ Глобальная память не инициализирована")
            return
        
        stats = await memory_db.get_stats()
        lessons = await memory_db.get_all_lessons()
        
        text = (
            f"🧠 **Глобальная память**\n\n"
            f"📚 Уроков: {stats['lessons']}\n"
            f"💬 Взаимодействий: {stats['interactions']}\n"
            f"🔄 Паттернов: {stats['patterns']}\n\n"
        )
        
        if stats.get('by_category'):
            text += "**По категориям:**\n"
            for cat, cnt in stats['by_category'].items():
                text += f"• {cat}: {cnt}\n"
        
        if lessons:
            text += "\n**Последние уроки:**\n"
            for lesson in lessons[:5]:
                imp = "⭐" * min(lesson['importance'], 5)
                text += f"• {lesson['lesson'][:60]}... {imp}\n"
        
        text += f"\n`/memory_add` — добавить урок\n`/memory_del <id>` — удалить"
        await event.respond(text)

    @client.on(events.NewMessage(pattern=r"^/memory_add", func=lambda e: e.is_private))
    async def memory_add_handler(event):
        if not is_admin(event.sender_id):
            return
        
        if not memory_db:
            await event.respond("❌ Память не инициализирована")
            return
        
        args = event.raw_text.split(maxsplit=2)
        if len(args) < 3:
            await event.respond(
                "❌ Использование: `/memory_add <категория> <урок>`\n\n"
                "Категории: `mistake`, `success`, `style`, `knowledge`, `trigger`"
            )
            return
        
        category = args[1].lower()
        lesson = args[2]
        
        lesson_id = await quick_learn(memory_db, category, lesson)
        await event.respond(f"✅ Урок #{lesson_id} добавлен: {lesson[:50]}...")

    @client.on(events.NewMessage(pattern=r"^/memory_del", func=lambda e: e.is_private))
    async def memory_del_handler(event):
        if not is_admin(event.sender_id):
            return
        
        if not memory_db:
            await event.respond("❌ Память не инициализирована")
            return
        
        args = event.raw_text.split(maxsplit=1)
        if len(args) < 2 or not args[1].strip().isdigit():
            await event.respond("❌ Использование: `/memory_del <id>`")
            return
        
        lesson_id = int(args[1].strip())
        await memory_db.delete_lesson(lesson_id)
        await event.respond(f"✅ Урок #{lesson_id} удалён")

    @client.on(events.NewMessage(pattern=r"^/learn$", func=lambda e: e.is_private))
    async def learn_handler(event):
        if not is_admin(event.sender_id):
            return
        
        if not memory_db:
            await event.respond("❌ Память не инициализирована")
            return
        
        analyze_model = config.get("analyze_model")
        if not analyze_model:
            await event.respond("❌ Нет модели анализа")
            return
        
        msg = await event.respond("🔄 Анализирую взаимодействия...")
        
        lessons_created = await process_pending_interactions(ai_client, analyze_model, memory_db)
        
        await msg.edit(f"✅ Проанализировано. Новых уроков: {lessons_created}")

    @client.on(events.NewMessage(pattern=r"^/(profile|info)", func=lambda e: e.is_private))
    async def profile_handler(event):
        if not is_admin(event.sender_id):
            return
        
        args = event.raw_text.split(maxsplit=1)
        if len(args) < 2 or not args[1].strip().lstrip('-').isdigit():
            await event.respond("❌ Использование: `/info <user_id>`")
            return
        
        user_id = int(args[1].strip())
        profile = await user_db.get_profile(user_id)
        
        if profile:
            import datetime
            updated = profile.get('last_updated', 0)
            updated_str = datetime.datetime.fromtimestamp(updated).strftime('%d.%m.%Y %H:%M') if updated else 'никогда'
            
            rel_level = profile.get('relationship', 0)
            rel_name, rel_desc = user_db.get_relationship_info(rel_level)
            mood = profile.get('mood', 0)
            mood_names = {-2: "😤", -1: "😐", 0: "🙂", 1: "😊", 2: "😄"}
            
            topics = profile.get('topics', '') or 'нет'
            
            text = (
                f"🧠 **Инфо о пользователе**\n\n"
                f"🆔 ID: `{user_id}`\n"
                f"👤 @{profile.get('username') or 'нет'} | {profile.get('name') or 'нет'}\n\n"
                f"**Отношения:** {rel_name} ({rel_level})\n"
                f"**Настроение:** {mood_names.get(mood, '🙂')} ({mood})\n"
                f"🕐 {updated_str}\n\n"
                f"**Факты:**\n{profile.get('profile') or 'Пока нет'}\n\n"
                f"**Интересы:**\n{topics}\n\n"
                f"**Даты:**\n{profile.get('dates') or 'нет'}"
            )
            await event.respond(text)
        else:
            await event.respond(f"❌ Инфо о `{user_id}` не найдено")

    @client.on(events.NewMessage(pattern=r"^/reminders$", func=lambda e: e.is_private))
    async def reminders_handler(event):
        if not is_admin(event.sender_id):
            return
        
        reminders = await reminder_db.get_user_reminders(event.sender_id)
        
        if not reminders:
            await event.respond("📋 Нет активных напоминаний")
            return
        
        lines = ["⏰ **Активные напоминания:**\n"]
        for i, r in enumerate(reminders, 1):
            time_str = format_time_msk(r['send_at'])
            topic = r['message'][:40] + "..." if len(r['message']) > 40 else r['message']
            lines.append(f"{i}. `{time_str}` — {topic}")
        
        lines.append(f"\n`/del_reminder <номер>` — удалить")
        await event.respond("\n".join(lines))

    @client.on(events.NewMessage(pattern=r"^/del_reminder", func=lambda e: e.is_private))
    async def del_reminder_handler(event):
        if not is_admin(event.sender_id):
            return
        
        args = event.raw_text.split(maxsplit=1)
        if len(args) < 2 or not args[1].strip().isdigit():
            await event.respond("❌ Использование: `/del_reminder <номер>`")
            return
        
        index = int(args[1].strip())
        reminders = await reminder_db.get_user_reminders(event.sender_id)
        
        if 0 < index <= len(reminders):
            r = reminders[index - 1]
            await reminder_db.delete(r['id'])
            await event.respond(f"✅ Напоминание #{index} удалено")
        else:
            await event.respond(f"❌ Напоминание #{index} не найдено")

    @client.on(events.NewMessage(pattern=r"^/add_emoji", func=lambda e: e.is_private))
    async def add_emoji_handler(event):
        if not is_admin(event.sender_id):
            return
        
        emojis = extract_emoji_with_id(event.message)
        
        if not emojis:
            await event.respond(
                "❌ **Использование:**\n"
                "`/add_emoji {премиум эмодзи} {описание}`\n\n"
                "Пример:\n"
                "`/add_emoji 🔥 огонь, круто, восторг`"
            )
            return
        
        text_after_emoji = event.raw_text
        for emoji_char, _ in emojis:
            text_after_emoji = text_after_emoji.replace(emoji_char, "", 1)
        
        description = text_after_emoji.replace("/add_emoji", "").strip()
        
        if not description:
            await event.respond("❌ Укажи описание для эмодзи!")
            return
        
        emoji_char, doc_id = emojis[0]
        await emoji_db.add(emoji_char, doc_id, description)
        
        response_text = f"Эмодзи добавлен!\n\nЭмодзи: {emoji_char}\nID: {doc_id}\nОписание: {description}"
        
        emoji_pos = response_text.find(emoji_char)
        emoji_offset = utf16_len(response_text[:emoji_pos])
        emoji_length = utf16_len(emoji_char)
        
        await client.send_message(
            event.chat_id,
            response_text,
            formatting_entities=[
                MessageEntityCustomEmoji(
                    offset=emoji_offset,
                    length=emoji_length,
                    document_id=doc_id
                )
            ]
        )

    @client.on(events.NewMessage(pattern=r"^/emojis$", func=lambda e: e.is_private))
    async def emojis_handler(event):
        if not is_admin(event.sender_id):
            return
        
        emoji_list, emoji_entities = await emoji_db.get_formatted_list()
        header = "Список эмодзи:\n\n"
        footer = "\n\n/del_emoji <номер> — удалить"
        
        header_len = utf16_len(header)
        
        entities = [
            MessageEntityBold(offset=0, length=utf16_len("Список эмодзи:"))
        ]
        
        for e in emoji_entities:
            entities.append(MessageEntityCustomEmoji(
                offset=header_len + e["offset"],
                length=e["length"],
                document_id=e["document_id"]
            ))
        
        cmd_start = utf16_len(header + emoji_list + "\n\n")
        entities.append(MessageEntityCode(offset=cmd_start, length=utf16_len("/del_emoji <номер>")))
        
        await client.send_message(
            event.chat_id,
            header + emoji_list + footer,
            formatting_entities=entities
        )

    @client.on(events.NewMessage(pattern=r"^/test ", func=lambda e: e.is_private))
    async def test_handler(event):
        if not is_admin(event.sender_id):
            return
        
        parts = event.raw_text.split()
        if len(parts) < 4:
            await event.respond(
                "❌ Использование:\n"
                "`/test {сообщение} {страница} {free/paid}`\n\n"
                "Пример: `/test Привет! 1 free`"
            )
            return
        
        category = parts[-1].lower()
        page = parts[-2]
        message = " ".join(parts[1:-2])
        
        if category not in ["free", "paid"]:
            await event.respond("❌ Укажи `free` или `paid`")
            return
        
        if not page.isdigit():
            await event.respond("❌ Номер страницы должен быть числом")
            return
        
        page = int(page) - 1
        
        if not models_cache["free"] and not models_cache["paid"]:
            msg = await event.respond("⏳ Загрузка моделей...")
            all_models, popular_paid, popular_free = await get_models(ai_client)
            free, paid = sort_models(all_models, popular_paid, popular_free)
            models_cache["free"] = free
            models_cache["paid"] = paid
            models_cache["all"] = {m["id"]: m for m in all_models}
            await msg.delete()
        
        models = models_cache.get(category, [])
        per_page = 10
        start = page * per_page
        end = start + per_page
        page_models = models[start:end]
        
        if not page_models:
            await event.respond(f"❌ Страница {page + 1} пустая")
            return
        
        status_msg = await event.respond(f"🧪 Тестирую {len(page_models)} моделей параллельно...")
        
        emoji_list, _ = await get_emojis_for_ai()
        full_prompt = system_prompt + "\n\n" + emoji_list
        
        async def test_model(m):
            model_id = m["id"]
            model_name = m.get("name", model_id)
            
            try:
                start_time = time.time()
                
                msgs = [
                    {"role": "system", "content": full_prompt},
                    {"role": "user", "content": message}
                ]
                result = await ai_client.chat(model_id, msgs)
                
                elapsed = time.time() - start_time
                
                response = result.get("content", "") if isinstance(result, dict) else str(result)
                
                if response and not response.startswith("Ошибка"):
                    char_count = len(response)
                    speed = char_count / elapsed if elapsed > 0 else 0
                    
                    short_response = response[:100] + "..." if len(response) > 100 else response
                    
                    return (
                        f"**{model_name}**\n"
                        f"`{model_id}`\n"
                        f"⏱ {elapsed:.1f}с | 📝 {char_count} симв | ⚡ {speed:.0f} с/с\n"
                        f"💬 {short_response}\n"
                    )
                else:
                    return f"**{model_name}**\n❌ {response[:50] if response else 'Пустой ответ'}\n"
            except Exception as e:
                return f"**{model_name}**\n❌ Ошибка: {str(e)[:50]}\n"
        
        total_start = time.time()
        results = await asyncio.gather(*[test_model(m) for m in page_models])
        total_time = time.time() - total_start
        
        await status_msg.delete()
        
        header = f"🧪 **Тест страницы {page + 1} ({category})**\n📨 `{message}`\n⏱ Общее время: {total_time:.1f}с\n\n"
        await event.respond(header + "\n".join(results))

    @client.on(events.NewMessage(pattern=r"^/del_emoji", func=lambda e: e.is_private))
    async def del_emoji_handler(event):
        if not is_admin(event.sender_id):
            return
        
        args = event.raw_text.split(maxsplit=1)
        if len(args) < 2 or not args[1].strip().isdigit():
            await event.respond("❌ Использование: `/del_emoji <номер>`")
            return
        
        index = int(args[1].strip())
        deleted = await emoji_db.delete_by_index(index)
        
        if deleted:
            await event.respond(f"✅ Эмодзи #{index} удалён")
        else:
            await event.respond(f"❌ Эмодзи #{index} не найден")

    @client.on(events.NewMessage(func=lambda e: e.is_private and e.sticker))
    async def sticker_receive_handler(event):
        if not is_admin(event.sender_id):
            return
        
        if event.raw_text and event.raw_text.startswith("/add_sticker"):
            sticker = event.sticker
            keywords = event.raw_text.replace("/add_sticker", "").strip()
            
            await sticker_db.add(
                file_id=str(sticker.id),
                emoji=sticker.attributes[1].alt if len(sticker.attributes) > 1 else None,
                keywords=keywords
            )
            
            count = await sticker_db.count()
            await event.respond(f"✅ Стикер добавлен! ({count} всего)\nКлючевые слова: {keywords or 'нет'}")

    @client.on(events.NewMessage(func=lambda e: e.is_private and e.voice))
    async def voice_handler(event):
        if event.message.out:
            return
        
        excuse = get_voice_excuse()
        await event.respond(excuse)

    async def on_group_join(chat_id: int, title: str, username: str = None):
        try:
            await group_db.add_group(chat_id, title, username)
            print(f"[GROUP] Зашла в {title} ({chat_id})")
            
            existing = await group_db.get_group(chat_id)
            has_rules = existing and existing.get("rules")
            has_staff = existing and existing.get("staff")
            rules_tried = existing and existing.get("rules_tried")
            staff_tried = existing and existing.get("staff_tried")
            
            if (has_rules or rules_tried) and (has_staff or staff_tried):
                print(f"[GROUP] Rules/Staff уже получены или пробовали для {title}, пропускаю")
                return
            
            await asyncio.sleep(3)
            
            try:
                entity = await client.get_entity(chat_id)
            except Exception as e:
                print(f"[GROUP] Не могу получить entity для {chat_id}: {e}")
                return
            
            analyze_model = config.get("analyze_model")
            
            if not has_rules and not rules_tried:
                try:
                    print(f"[GROUP] Отправляю /rules в {title}")
                    await group_db.mark_rules_tried(chat_id)  # Отмечаем ДО попытки
                    rules_msg = await client.send_message(entity, "/rules")
                    rules_response = await wait_for_bot_response(client, chat_id, rules_msg.id, timeout=70)
                    try:
                        await rules_msg.delete()
                    except:
                        pass
                        
                    if rules_response:
                        print(f"[GROUP] Получен ответ на /rules: {rules_response[:100]}...")
                        parsed_rules = None
                        if analyze_model and ai_client:
                            parsed_rules = await parse_rules_ai(ai_client, analyze_model, rules_response)
                        if not parsed_rules:
                            parsed_rules = parse_rules_response(rules_response)
                        if parsed_rules:
                            await group_db.update_rules(chat_id, parsed_rules)
                            print(f"[GROUP] ✅ Правила сохранены для {title}")
                        else:
                            print(f"[GROUP] ❌ Ответ не похож на правила")
                    else:
                        print(f"[GROUP] Нет ответа на /rules (таймаут), больше не пробуем")
                except Exception as e:
                    print(f"[GROUP] Ошибка /rules: {e}")
                
                await asyncio.sleep(2)
            
            if not has_staff and not staff_tried:
                try:
                    print(f"[GROUP] Отправляю /staff в {title}")
                    await group_db.mark_staff_tried(chat_id)  # Отмечаем ДО попытки
                    staff_msg = await client.send_message(entity, "/staff")
                    staff_response = await wait_for_bot_response(client, chat_id, staff_msg.id, timeout=70)
                    try:
                        await staff_msg.delete()
                    except:
                        pass
                        
                    if staff_response:
                        print(f"[GROUP] Получен ответ на /staff: {staff_response[:100]}...")
                        parsed_staff = None
                        if analyze_model and ai_client:
                            parsed_staff = await parse_staff_ai(ai_client, analyze_model, staff_response)
                        if not parsed_staff:
                            parsed_staff = parse_staff_response(staff_response)
                        if parsed_staff:
                            await group_db.update_staff(chat_id, parsed_staff)
                            print(f"[GROUP] ✅ Стафф сохранён для {title}")
                        else:
                            print(f"[GROUP] ❌ Ответ не похож на стафф")
                    else:
                        print(f"[GROUP] Нет ответа на /staff (таймаут), больше не пробуем")
                except Exception as e:
                    print(f"[GROUP] Ошибка /staff: {e}")
                    
        except Exception as e:
            print(f"Ошибка on_group_join: {e}")

    @client.on(events.NewMessage(incoming=True, func=lambda e: e.is_group or e.is_channel))
    async def group_message_handler(event):
        if event.message.out:
            return
        
        text = event.message.message
        if not text:
            return
        
        chat = await event.get_chat()
        chat_id = event.chat_id
        
        # Очередь: ждём пока предыдущее сообщение обработается
        if chat_id not in chat_locks:
            chat_locks[chat_id] = asyncio.Lock()
        
        async with chat_locks[chat_id]:
            await _process_group_message(event, chat, chat_id, text)
    
    async def _process_group_message(event, chat, chat_id, text):
        group_info = await group_db.get_group(chat_id)
        if not group_info:
            await group_db.add_group(chat_id, getattr(chat, 'title', 'Unknown'), getattr(chat, 'username', None))
            group_info = await group_db.get_group(chat_id)
        
        sender = await event.get_sender()
        sender_id = event.sender_id
        sender_username = get_display_name(sender, sender_id)
        
        me = await client.get_me()
        my_username = me.username
        my_id = me.id
        
        if sender_id == my_id:
            return

        
        interaction_key = f"{chat_id}_{sender_id}"
        if interaction_key in last_bot_responses and memory_db:
            last_resp = last_bot_responses[interaction_key]
            reaction_type = detect_reaction_type(text)
            if reaction_type != "neutral":
                await memory_db.log_interaction(
                    chat_id=chat_id,
                    user_id=sender_id,
                    my_message=last_resp,
                    user_reaction=text,
                    reaction_type=reaction_type
                )
            del last_bot_responses[interaction_key]
        
        reply_to_me = False
        reply_context = None
        reply_msg_id = None
        
        if event.message.reply_to:
            try:
                reply_msg = await event.message.get_reply_message()
                if reply_msg:
                    reply_msg_id = reply_msg.id
                    if reply_msg.sender_id == my_id:
                        reply_to_me = True
                    
                    reply_sender = await reply_msg.get_sender()
                    reply_username = reply_sender.username if reply_sender else "user"
                    reply_context = {
                        "from": reply_username,
                        "text": reply_msg.message[:300] if reply_msg.message else "",
                        "is_me": reply_msg.sender_id == my_id
                    }
            except:
                pass
        
        text_lower_off = text.lower()
        bot_mentioned = reply_to_me or '@honoai' in text_lower_off or 'хоно' in text_lower_off or (my_username and f'@{my_username.lower()}' in text_lower_off)
        if bot_off_reason is not None and bot_mentioned:
            await client.send_message(chat_id, f"Бот выключен по причине: {bot_off_reason}", reply_to=event.message.id)
            return
        
        if bot_off_reason is not None:
            return
        
        forward_info = ""
        if event.message.fwd_from:
            fwd = event.message.fwd_from
            fwd_name = None
            if fwd.from_name:
                fwd_name = fwd.from_name
            elif fwd.from_id:
                try:
                    fwd_entity = await client.get_entity(fwd.from_id)
                    if hasattr(fwd_entity, 'title'):
                        fwd_name = fwd_entity.title
                    elif hasattr(fwd_entity, 'username') and fwd_entity.username:
                        fwd_name = fwd_entity.username
                    elif hasattr(fwd_entity, 'first_name'):
                        fwd_name = f"{fwd_entity.first_name} {fwd_entity.last_name or ''}".strip()
                except:
                    pass
            if fwd_name:
                forward_info = f"[переслано от {fwd_name}] "
        
        sender_role = ""
        sender_role_ru = ""
        try:
            permissions = await client.get_permissions(chat_id, sender_id)
            if permissions:
                if getattr(permissions, 'is_creator', False):
                    sender_role = "owner"
                    sender_role_ru = "владелец"
                elif getattr(permissions, 'is_admin', False):
                    sender_role = "admin"
                    sender_role_ru = "админ"
        except:
            pass
        
        sender_profile = await user_db.get_profile(sender_id)
        
        context_text = f"{forward_info}{text}" if forward_info else text
        
        if sender_role in ['owner', 'admin']:
            await track_admin_action(ai_client, config.get("selected_model"), text, sender_id, sender_username, sender_role, chat_id, group_db)
        
        text_lower = text.lower()
        
        has_demotion_pattern = any(p in text_lower for p in ['снять', 'убрать права', 'отключить мод', 'выключить мод'])
        if sender_role in ['owner', 'admin'] and has_demotion_pattern:
            if reply_to_me or '@honoai' in text_lower:
                await group_db.set_mod_level(chat_id, 0, None)
                print(f"[MODERATION] Снята с модерации в {chat.title}")
                await client.send_message(chat_id, "ладно, больше не модерирую, как скажешь", reply_to=event.message.id)
                return
        
        has_promotion_pattern = any(p in text_lower for p in ['повысить', 'повысь', 'права ', 'уровень '])
        
        if sender_role in ['owner', 'admin'] and reply_to_me and has_promotion_pattern:
            promo_models = config.get("chat_analyze_models", ["google/gemini-2.0-flash-lite"])
            analyze_model = promo_models[0] if promo_models else "google/gemini-2.0-flash-lite"
            is_promotion, level = await check_promotion(
                ai_client, analyze_model, text, sender_role, reply_to_me, True
            )
            if is_promotion and level > 0:
                import re
                original_level_match = re.search(r'(\d+)', text)
                original_level = int(original_level_match.group(1)) if original_level_match else level
                await group_db.set_mod_level(chat_id, level, sender_id)
                print(f"[MODERATION] Повышена до уровня {original_level} (внутр: {level}) в {chat.title}")
                await client.send_message(chat_id, f"окей, теперь я модератор уровня {original_level}, буду следить за порядком", reply_to=event.message.id)
                return
        
        mentioned_ids = []
        if event.message.entities:
            from telethon.tl.types import MessageEntityMention, MessageEntityMentionName
            for entity in event.message.entities:
                if isinstance(entity, MessageEntityMentionName):
                    mentioned_ids.append(entity.user_id)
        
        should_respond, reason = should_respond_quick(text, my_username, my_id, reply_to_me, mentioned_ids)
        
        if should_respond is None:
            chat_models = config.get("chat_analyze_models", [])
            if chat_models:
                context = await group_db.get_context(chat_id, limit=8)
                
                if len(context) < 3:
                    try:
                        tg_messages = []
                        async for msg in client.iter_messages(chat_id, limit=5):
                            if msg.message and msg.sender:
                                sender = await msg.get_sender()
                                uname = sender.username if sender else "user"
                                tg_messages.append({
                                    "username": uname,
                                    "message": msg.message[:100],
                                    "user_id": msg.sender_id
                                })
                        context = list(reversed(tg_messages))
                        print(f"[GROUP] Загрузил {len(context)} сообщений из TG")
                    except Exception as e:
                        print(f"[GROUP] Ошибка загрузки из TG: {e}")
                
                should_respond, reason = await should_respond_ai(ai_client, chat_models, text, context, my_username, sender_username, chat_id)
            else:
                should_respond = False
        
        from backend.humanizer.skupki import is_skupka, extract_keywords, get_skupka_hash, check_skupka_cooldown, is_readable, clean_premium_emoji
        
        skupka_detected, skupka_score = is_skupka(text)
        if skupka_detected and sender_role not in ['owner', 'admin']:
            print(f"[SKUPKA] Обнаружена скупка от {sender_username} (score: {skupka_score:.0%})")
            
            rules = group_info.get('rules', '') if group_info else ''
            last_skupka = await group_db.get_user_last_skupka(chat_id, sender_id)
            cooldown_violated, remaining = check_skupka_cooldown(last_skupka, rules)
            
            if cooldown_violated:
                remaining_min = remaining // 60
                print(f"[SKUPKA] Cooldown нарушен! Осталось {remaining_min} мин")
                
                mod_info = await group_db.get_mod_info(chat_id)
                mod_level = mod_info.get('mod_level', 0) if mod_info else 0
                
                if mod_level > 0:
                    mute_time = "30м" if remaining_min < 30 else "1ч"
                    await client.send_message(chat_id, f"мут {mute_time}\nСлишком частая рассылка скупки", reply_to=event.message.id)
                return
            
            readable = is_readable(text)
            parsed_text = clean_premium_emoji(text) if readable else text[:200]
            keywords = extract_keywords(text)
            msg_hash = get_skupka_hash(text)
            
            await group_db.add_skupka(chat_id, sender_id, sender_username, text[:500], parsed_text, keywords, msg_hash)
            print(f"[SKUPKA] Сохранена: {keywords}")
            return
        
        await group_db.add_context(chat_id, sender_id, sender_username, context_text[:300], event.message.id, reply_msg_id)
        await group_db.increment_messages(chat_id)
        
        chat_analyze_models = config.get("chat_analyze_models", [])
        sender_rel = sender_profile.get('relationship', 0) if sender_profile else 0
        print(f"[MOD CHECK] chat_analyze_models={len(chat_analyze_models)}, sender_role='{sender_role}', rel={sender_rel}")
        if chat_analyze_models and sender_role not in ['owner', 'admin'] and not skupka_detected and sender_rel < 3:
            context = await group_db.get_context(chat_id, limit=10)
            mod_command = await process_moderation(
                ai_client,
                chat_analyze_models[0],
                text,
                sender_id,
                sender_username,
                sender_role,
                chat_id,
                group_db,
                context,
                reply_context
            )
            if mod_command:
                print(f"[MODERATION] Действие: {mod_command[:50]}")
                await client.send_message(chat_id, mod_command, reply_to=event.message.id)
                return
        elif not chat_analyze_models:
            print(f"[MOD CHECK] Пропуск - нет chat_analyze_models")
        elif sender_role in ['owner', 'admin']:
            print(f"[MOD CHECK] Пропуск - отправитель {sender_role}")
        
        if not should_respond:
            return
        
        try:
            user_profile = await user_db.get_profile(sender_id)
            rel_level = user_profile.get("relationship", 0) if user_profile else 0
            asyncio.create_task(send_reaction(client, chat_id, event.message.id, text, rel_level))
        except:
            pass
        
        print(f"[GROUP] Отвечаю в {chat.title} (причина: {reason})")
        
        model = config.get("selected_model")
        if not model or not ai_client:
            return
        
        typing_task = asyncio.create_task(keep_typing(client, chat_id))
        
        try:
            context = await group_db.get_context(chat_id, limit=20)
            group_prompt = get_group_system_prompt(group_info, context)
            
            my_role_info = ""
            mod_info = await group_db.get_mod_info(chat_id)
            my_mod_level = mod_info.get('mod_level', 0) if mod_info else 0
            if my_mod_level > 0:
                role_names = {1: "младший модератор", 2: "модератор", 3: "старший модератор"}
                my_role_info = f"\n\nТВОЯ РОЛЬ: Ты {role_names.get(my_mod_level, 'модератор')} этого чата (уровень {my_mod_level}). Можешь модерировать."
            
            sender_info = ""
            sender_profile = await user_db.get_profile(sender_id)
            if sender_profile:
                from backend.database.users import RELATIONSHIP_LEVELS
                rel = sender_profile.get('relationship', 0)
                rel_emoji, rel_how = RELATIONSHIP_LEVELS.get(rel, RELATIONSHIP_LEVELS[0])
                facts = sender_profile.get('profile', '')
                interests = sender_profile.get('topics', '')
                dates = sender_profile.get('dates', '')
                
                sender_info = f"\n\nОТПРАВИТЕЛЬ: @{sender_username}"
                if sender_role_ru:
                    sender_info += f" — {sender_role_ru} чата"
                sender_info += f"\nОтношения: {rel_emoji} ({rel}) — {rel_how}"
                if facts and facts != "нет":
                    sender_info += f"\nЗнаю о нём: {facts}"
                if interests and interests != "нет":
                    sender_info += f"\nИнтересы: {interests}"
                if dates and dates != "нет":
                    sender_info += f"\nВажные даты: {dates}"
            elif sender_role_ru:
                sender_info = f"\n\nОТПРАВИТЕЛЬ: @{sender_username} — {sender_role_ru} чата"
            
            reply_info = ""
            if reply_context:
                reply_from = "ты" if reply_context.get("is_me") else f"@{reply_context.get('from', 'user')}"
                reply_info = f"\n\n⚠️ ТЕКУЩЕЕ СООБЩЕНИЕ — ЭТО ОТВЕТ НА ТВОЁ/ЧУЖОЕ СООБЩЕНИЕ:\nОтвечают на [{reply_from}]: \"{reply_context.get('text', '')[:200]}\"\nУчти этот контекст в ответе!"
            
            relationships_info = ""
            user_ids_in_context = set()
            for msg in context[-20:]:
                uid = msg.get('user_id')
                if uid and uid != my_id:
                    user_ids_in_context.add(uid)
            user_ids_in_context.add(sender_id)
            
            if user_ids_in_context:
                from backend.database.users import RELATIONSHIP_LEVELS
                rel_lines = []
                for uid in user_ids_in_context:
                    profile = await user_db.get_profile(uid)
                    if profile:
                        uname = profile.get('username') or profile.get('name') or f"user_{uid}"
                        rel = profile.get('relationship', 0)
                        rel_emoji, rel_how = RELATIONSHIP_LEVELS.get(rel, RELATIONSHIP_LEVELS[0])
                        rel_lines.append(f"• {uname}: {rel_emoji} — {rel_how}")
                if rel_lines:
                    relationships_info = "\n\nТВОЁ ОТНОШЕНИЕ К УЧАСТНИКАМ ЧАТА:\n" + "\n".join(rel_lines)
            
            emoji_list, id_map = await get_emojis_for_ai()
            
            lessons_text = ""
            if memory_db:
                lessons_text = await get_contextual_lessons(memory_db, text, limit=4)
                if lessons_text:
                    lessons_text = "\n\n" + lessons_text
            
            datetime_info = get_current_datetime_info()
            
            media_type = detect_media_type(event.message)
            media_info = f"\n📎 К сообщению прикреплено: {media_type}" if media_type else ""
            
            buttons = extract_buttons(event.message)
            buttons_info = ""
            if buttons:
                btns_text = format_buttons_for_ai(buttons)
                buttons_info = f"\n🔘 Кнопки в сообщении: {btns_text}"
            
            my_msgs_in_row = count_my_messages_in_row(context, my_username)
            spam_warning = ""
            if my_msgs_in_row >= 2:
                spam_warning = f"\n⚠️ Ты уже написал(а) {my_msgs_in_row} сообщений подряд! Подожди ответа других."
            
            group_profile = await group_db.get_group_profile(chat_id)
            group_profile_info = ""
            if group_profile:
                brief = format_group_profile_brief(group_profile)
                if brief:
                    group_profile_info = f"\n\n{brief}"
            
            mentions = extract_mentions(text, event.message.entities)
            links = extract_links(text)
            msg_meta = ""
            if mentions:
                msg_meta += f"\n👤 Упоминания в сообщении: {', '.join(mentions)}"
            if links:
                msg_meta += f"\n🔗 Ссылки: {len(links)} шт"
            
            chat_activity = get_chat_activity_info(context, hours=1)
            activity_info = f"\n📊 {chat_activity}" if chat_activity else ""
            
            if sender_profile:
                rel_stats = get_relationship_stats(sender_profile)
                if rel_stats:
                    sender_info += f" ({rel_stats})"
            
            full_prompt = f"🕐 {datetime_info}\n\n" + system_prompt + "\n\n" + group_prompt + my_role_info + group_profile_info + sender_info + msg_meta + media_info + buttons_info + spam_warning + reply_info + relationships_info + activity_info + lessons_text + "\n\n" + emoji_list
            
            messages = [{"role": "system", "content": full_prompt}]
            
            for msg in context[-15:]:
                msg_username = msg.get('username') or f"user_{msg.get('user_id', '?')}"
                role = "assistant" if msg_username == my_username else "user"
                msg_text = msg.get('message', '')
                
                msg_reply_id = msg.get('reply_to_msg_id')
                reply_marker = ""
                if msg_reply_id:
                    reply_data = await group_db.get_message_by_msg_id(chat_id, msg_reply_id)
                    if reply_data:
                        reply_username = reply_data.get('username') or f"user_{reply_data.get('user_id', '?')}"
                        reply_marker = f" ↩️[ответ на @{reply_username}: {reply_data.get('message', '')[:60]}]"
                
                content = f"@{msg_username}{reply_marker}: {msg_text}"
                messages.append({"role": role, "content": content})
            
            has_photo = event.message.photo is not None
            vision_model = config.get("selected_vision_model")
            
            current_msg_prefix = f"@{sender_username}"
            if forward_info:
                current_msg_prefix += f" {forward_info}"
            if reply_context:
                reply_from = "тебя" if reply_context.get("is_me") else f"@{reply_context.get('from', 'user')}"
                current_msg_prefix += f" ↩️[отвечает на {reply_from}]"
            
            if has_photo and vision_model:
                try:
                    photo = await event.message.download_media(bytes)
                    user_msg = text or "Что на картинке?"
                    messages.append({"role": "user", "content": f"{current_msg_prefix}: [фото] {user_msg}"})
                    
                    response_text = await ai_client.chat_with_image(vision_model, messages, photo)
                    print(f"[GROUP] Использовал vision модель для фото")
                    tool_calls = None
                except Exception as e:
                    print(f"[GROUP] Ошибка vision: {e}, использую обычную модель")
                    messages.append({"role": "user", "content": f"{current_msg_prefix}: {text}"})
                    result = await ai_client.chat(model, messages, tools=TOOLS, max_tokens=500)
                    response_text = result.get("content", "") if isinstance(result, dict) else str(result)
                    tool_calls = result.get("tool_calls") if isinstance(result, dict) else None
            else:
                messages.append({"role": "user", "content": f"{current_msg_prefix}: {text}"})
                result = await ai_client.chat(model, messages, tools=TOOLS, max_tokens=500)
                response_text = result.get("content", "") if isinstance(result, dict) else str(result)
                tool_calls = result.get("tool_calls") if isinstance(result, dict) else None
            
            if tool_calls:
                response_text = await handle_tool_calls(client, model, messages, tool_calls, emoji_list, full_prompt, on_group_join, chat_id, sender_role, event.message.id)
            
            if not response_text or response_text.startswith("Ошибка"):
                alt_model = config.get("alt_model")
                if alt_model:
                    result = await ai_client.chat(alt_model, messages, max_tokens=500)
                    response_text = result.get("content", "") if isinstance(result, dict) else str(result)
            
            if response_text and not response_text.startswith("Ошибка"):
                await group_db.add_context(chat_id, my_id, my_username, response_text[:300])
                await group_db.increment_messages(chat_id, is_mine=True)
                
                response_text = remove_self_mention(response_text)
                response_text = response_text.replace("\\n", "\n")
                
                emojis = await emoji_db.get_all()
                emoji_map = {e["document_id"]: e["emoji"] for e in emojis}
                
                final_text, entities = parse_emoji_tags(response_text, emoji_map, id_map)
                
                if entities:
                    await client.send_message(chat_id, final_text, formatting_entities=entities, reply_to=event.message.id)
                else:
                    await client.send_message(chat_id, final_text, parse_mode='md', reply_to=event.message.id)
                
                interaction_key = f"{chat_id}_{sender_id}"
                last_bot_responses[interaction_key] = response_text[:300]
                
                try:
                    user_messages = []
                    for msg in context[-20:]:
                        msg_username = msg.get('username', '')
                        msg_text = msg.get('message', '')
                        if msg_username == my_username:
                            user_messages.append({"role": "assistant", "content": msg_text})
                        else:
                            user_messages.append({"role": "user", "content": msg_text})
                    user_messages.append({"role": "assistant", "content": response_text})
                    
                    sender_name_full = ""
                    if sender:
                        sender_name_full = f"{sender.first_name or ''} {sender.last_name or ''}".strip()
                    
                    should_analyze = False
                    if sender_profile:
                        msg_count = sender_profile.get('message_count', 0) + 1
                        await user_db.increment_message_count(sender_id)
                        if msg_count % 5 == 0:
                            should_analyze = True
                    else:
                        should_analyze = True
                    
                    if should_analyze:
                        asyncio.create_task(analyze_user(sender_id, sender_username, sender_name_full, user_messages))
                except Exception as e:
                    print(f"[GROUP] Ошибка запуска analyze_user: {e}")
                    
        except Exception as e:
            print(f"Ошибка group_message: {e}")
        finally:
            typing_task.cancel()

    @client.on(events.NewMessage(pattern=r"^/groups$", func=lambda e: e.is_private))
    async def groups_handler(event):
        if not is_admin(event.sender_id):
            return
        
        groups = await group_db.get_all_groups()
        if not groups:
            await event.respond("📋 Нет групп")
            return
        
        lines = ["📋 **Группы:**\n"]
        for i, g in enumerate(groups, 1):
            title = g.get('title', '?')
            username = g.get('username')
            msg_count = g.get('message_count', 0)
            my_msgs = g.get('my_messages', 0)
            has_rules = "✅" if g.get('rules') else "❌"
            
            line = f"{i}. **{title}**"
            if username:
                line += f" (@{username})"
            line += f"\n   📊 {msg_count} сообщений (моих: {my_msgs}) | Правила: {has_rules}"
            lines.append(line)
        
        await event.respond("\n".join(lines))

    @client.on(events.NewMessage(pattern=r"^/groupinfo", func=lambda e: e.is_private))
    async def groupinfo_handler(event):
        if not is_admin(event.sender_id):
            return
        
        args = event.raw_text.split(maxsplit=1)
        if len(args) < 2:
            await event.respond("❌ Укажи номер группы: `/groupinfo 1`")
            return
        
        try:
            index = int(args[1]) - 1
        except:
            await event.respond("❌ Неверный номер")
            return
        
        groups = await group_db.get_all_groups()
        if 0 <= index < len(groups):
            g = groups[index]
            lines = [
                f"📋 **{g.get('title', '?')}**",
                f"ID: `{g.get('group_id')}`",
            ]
            if g.get('username'):
                lines.append(f"Username: @{g['username']}")
            if g.get('rules'):
                lines.append(f"\n**Правила:**\n{g['rules'][:500]}")
            if g.get('staff'):
                lines.append(f"\n**Стафф:**\n{g['staff'][:300]}")
            if g.get('topics'):
                lines.append(f"\n**Темы:** {g['topics']}")
            
            await event.respond("\n".join(lines))
        else:
            await event.respond(f"❌ Группа #{index+1} не найдена")

    @client.on(events.NewMessage(pattern=r"^/del_group", func=lambda e: e.is_private))
    async def del_group_handler(event):
        if not is_admin(event.sender_id):
            return
        
        args = event.raw_text.split(maxsplit=1)
        if len(args) < 2:
            await event.respond("❌ Использование: `/del_group <номер>` или `/del_group all`")
            return
        
        arg = args[1].strip().lower()
        
        if arg == "all":
            groups = await group_db.get_all_groups()
            for g in groups:
                await group_db.delete_group(g['group_id'])
            await event.respond(f"✅ Удалено {len(groups)} групп")
            return
        
        try:
            index = int(arg) - 1
        except:
            await event.respond("❌ Неверный номер")
            return
        
        groups = await group_db.get_all_groups()
        if 0 <= index < len(groups):
            g = groups[index]
            await group_db.delete_group(g['group_id'])
            await event.respond(f"✅ Группа `{g.get('title', '?')}` удалена")
        else:
            await event.respond(f"❌ Группа #{index+1} не найдена")

    @client.on(events.NewMessage(pattern=r"^/mod_status", func=lambda e: e.is_private))
    async def mod_status_handler(event):
        if not is_admin(event.sender_id):
            return
        
        args = event.raw_text.split(maxsplit=1)
        if len(args) < 2:
            await event.respond("❌ Использование: `/mod_status <номер группы>`")
            return
        
        try:
            index = int(args[1]) - 1
        except:
            await event.respond("❌ Неверный номер")
            return
        
        groups = await group_db.get_all_groups()
        if not (0 <= index < len(groups)):
            await event.respond(f"❌ Группа #{index+1} не найдена")
            return
        
        g = groups[index]
        group_id = g['group_id']
        mod_info = await group_db.get_mod_info(group_id)
        
        if not mod_info or mod_info.get('mod_level', 0) == 0:
            await event.respond(f"📋 **{g.get('title', '?')}**\n\n🔓 Модерация не активна")
            return
        
        level = mod_info.get('mod_level', 0)
        stats = mod_info.get('mod_stats', {})
        admins = mod_info.get('admins_data', {})
        
        level_desc = {1: "Базовый (warn, mute)", 2: "Средний (+kick)", 3: "Полный (+ban)"}
        
        lines = [
            f"📋 **{g.get('title', '?')}**",
            f"\n🛡 **Модерация уровня {level}**",
            f"_{level_desc.get(level, '?')}_",
            f"\n📊 **Статистика:**",
            f"• Всего действий: {stats.get('total', 0)}",
            f"• Предупреждений: {stats.get('warn', 0)}",
            f"• Мутов: {stats.get('mute', 0)}",
            f"• Киков: {stats.get('kick', 0)}",
            f"• Банов: {stats.get('ban', 0)}"
        ]
        
        if admins:
            lines.append("\n👥 **Активность админов:**")
            for admin_id, data in list(admins.items())[:5]:
                name = data.get('name', 'Unknown')
                actions = data.get('actions', 0)
                eff = data.get('effectiveness', 50)
                lines.append(f"• @{name}: {actions} действий, эффективность {eff}%")
        
        await event.respond("\n".join(lines))

    @client.on(events.NewMessage(pattern=r"^/set_mod", func=lambda e: e.is_private))
    async def set_mod_handler(event):
        if not is_admin(event.sender_id):
            return
        
        args = event.raw_text.split()
        if len(args) < 3:
            await event.respond("❌ Использование: `/set_mod <номер группы> <уровень 0-3>`\n\n0 = выкл, 1 = warn+mute, 2 = +kick, 3 = +ban")
            return
        
        try:
            index = int(args[1]) - 1
            level = int(args[2])
        except:
            await event.respond("❌ Неверные параметры")
            return
        
        if level < 0 or level > 3:
            await event.respond("❌ Уровень должен быть 0-3")
            return
        
        groups = await group_db.get_all_groups()
        if not (0 <= index < len(groups)):
            await event.respond(f"❌ Группа #{index+1} не найдена")
            return
        
        g = groups[index]
        await group_db.set_mod_level(g['group_id'], level, event.sender_id)
        
        if level == 0:
            await event.respond(f"✅ Модерация отключена в **{g.get('title', '?')}**")
        else:
            await event.respond(f"✅ Модерация уровня {level} включена в **{g.get('title', '?')}**")

    @client.on(events.NewMessage(pattern=r"^/stickers$", func=lambda e: e.is_private))
    async def stickers_handler(event):
        if not is_admin(event.sender_id):
            return
        
        stickers = await sticker_db.get_all()
        if not stickers:
            await event.respond("📦 Стикеров пока нет\n\nОтправь стикер с командой `/add_sticker ключевые слова`")
            return
        
        lines = ["📦 **Стикеры:**\n"]
        for i, s in enumerate(stickers[:20], 1):
            kw = s.get('keywords', '')[:30] or 'без ключевых слов'
            lines.append(f"{i}. {s.get('emoji', '❓')} — {kw}")
        
        lines.append(f"\n\nВсего: {len(stickers)}")
        lines.append("`/del_sticker <номер>` — удалить")
        await event.respond("\n".join(lines))

    @client.on(events.NewMessage(pattern=r"^/del_sticker", func=lambda e: e.is_private))
    async def del_sticker_handler(event):
        if not is_admin(event.sender_id):
            return
        
        args = event.raw_text.split(maxsplit=1)
        if len(args) < 2 or not args[1].strip().isdigit():
            await event.respond("❌ Использование: `/del_sticker <номер>`")
            return
        
        index = int(args[1].strip())
        stickers = await sticker_db.get_all()
        
        if 0 < index <= len(stickers):
            await sticker_db.delete(stickers[index - 1]['id'])
            await event.respond(f"✅ Стикер #{index} удалён")
        else:
            await event.respond(f"❌ Стикер #{index} не найден")

    @client.on(events.NewMessage(incoming=True, func=lambda e: e.is_private))
    async def message_handler(event):
        if event.message.out:
            return
        
        text = event.message.message
        if not text or text.startswith("/"):
            return
        
        if not ai_client:
            return
        
        # Проверка на выключенный бот в ЛС
        if bot_off_reason is not None:
            await event.respond(f"Бот выключен по причине: {bot_off_reason}")
            return
        
        chat_id = event.chat_id
        
        # Очередь: ждём пока предыдущее сообщение обработается
        if chat_id not in chat_locks:
            chat_locks[chat_id] = asyncio.Lock()
        
        async with chat_locks[chat_id]:
            await _process_private_message(event, chat_id, text)
    
    async def _process_private_message(event, chat_id, text):
        sender = await event.get_sender()
        username = sender.username if sender else None
        user_name = f"{sender.first_name or ''} {sender.last_name or ''}".strip() if sender else None
        
        user_profile = await user_db.get_profile(event.sender_id)
        rel_level = user_profile.get("relationship", 0) if user_profile else 0
        
        asyncio.create_task(send_reaction(client, event.chat_id, event.message.id, text, rel_level))
        
        model = config.get("selected_model")
        vision_model = config.get("selected_vision_model")
        
        if not model:
            await event.respond("❌ Модель не выбрана! Используй /panel")
            return
        
        has_photo = event.message.photo is not None
        
        async def set_typing():
            await client(functions.messages.SetTypingRequest(
                peer=event.chat_id,
                action=SendMessageTypingAction()
            ))
        
        await set_typing()
        typing_task = asyncio.create_task(keep_typing(client, event.chat_id))
        
        id_map = {}
        emoji_map = {}
        
        try:
            if has_photo:
                if not vision_model:
                    typing_task.cancel()
                    await event.respond("❌ Vision модель не выбрана! Используй /models_vision")
                    return
                
                emoji_list, id_map = await get_emojis_for_ai()
                
                user_profile = await user_db.get_profile(event.sender_id)
                profile_text = ""
                if user_profile and user_profile.get("profile"):
                    profile_text = f"\n\n(возможно о собеседнике: {user_profile['profile']})"
                
                full_prompt = system_prompt + profile_text + "\n\n" + emoji_list
                
                user_msg = text or "Что на картинке?"
                add_to_history(event.chat_id, "user", f"[фото] {user_msg}")
                
                photo = await event.message.download_media(bytes)
                history = get_chat_history(event.chat_id)
                messages = [{"role": "system", "content": full_prompt}]
                messages.extend(history[:-1])
                messages.append({"role": "user", "content": user_msg})
                
                response = await ai_client.chat_with_image(vision_model, messages, photo)
                response_text = response
                
                if response_text and not response_text.startswith("Ошибка"):
                    add_to_history(event.chat_id, "assistant", response_text)
                    
                    asyncio.create_task(analyze_all(event.sender_id, username, user_name, user_msg, get_chat_history(event.chat_id)))
                
                emojis = await emoji_db.get_all()
                emoji_map = {e["document_id"]: e["emoji"] for e in emojis}
            else:
                if should_short_response(text):
                    response_text = get_short_response()
                    id_map = {}
                    emoji_map = {}
                else:
                    add_to_history(event.chat_id, "user", text)
                    
                    emoji_list, id_map = await get_emojis_for_ai()
                    
                    user_profile = await user_db.get_profile(event.sender_id)
                    profile_text = ""
                    mood_text = ""
                    pause_text = ""
                    
                    user_tag = f"@{username}" if username else (user_name if user_name else None)
                    if user_tag:
                        profile_text = f"\n\n(его тег: {user_tag})"
                    
                    last_seen = 0
                    if user_profile:
                        if user_profile.get("profile"):
                            profile_text += f"\n(возможно о нём: {user_profile['profile']})"
                        
                        if user_profile.get("topics"):
                            profile_text += f"\n(его интересы: {user_profile['topics']})"
                        
                        if user_profile.get("dates"):
                            profile_text += f"\n(даты: {user_profile['dates']})"
                        
                        current_mood = user_profile.get("mood", 0)
                        mood_text = f"\n\nТВОЁ НАСТРОЕНИЕ: {get_mood_prompt(current_mood)}"
                        
                        rel_level = user_profile.get("relationship", 0)
                        rel_name, rel_behavior = user_db.get_relationship_info(rel_level)
                        rel_text = f"\n\nУРОВЕНЬ ОТНОШЕНИЙ: {rel_name} — веди себя {rel_behavior}"
                        profile_text += rel_text
                        
                        last_seen = user_profile.get("last_seen", 0)
                        pause_text = get_pause_reaction(last_seen)
                        if pause_text:
                            pause_text = f"\n\n{pause_text}"
                    
                    time_ctx = get_time_context(last_seen)
                    time_text = f"\n\n{time_ctx}" if time_ctx else ""
                    
                    personal_event = get_personal_event()
                    event_text = f"\n\nТЫ СЕЙЧАС: {personal_event}" if personal_event else ""
                    
                    lessons_text = ""
                    if memory_db:
                        lessons_text = await get_contextual_lessons(memory_db, text, limit=3)
                        if lessons_text:
                            lessons_text = "\n\n" + lessons_text
                    
                    datetime_info = get_current_datetime_info()
                    
                    online_status = get_online_status_from_user(sender)
                    online_text = f"\n👤 Пользователь: {online_status}" if online_status else ""
                    
                    media_type = detect_media_type(event.message)
                    media_info = f"\n📎 К сообщению прикреплено: {media_type}" if media_type else ""
                    
                    buttons = extract_buttons(event.message)
                    buttons_info = ""
                    if buttons:
                        btns_text = format_buttons_for_ai(buttons)
                        buttons_info = f"\n🔘 Кнопки в сообщении: {btns_text}"
                    
                    rel_stats = ""
                    if user_profile:
                        stats = get_relationship_stats(user_profile)
                        if stats:
                            rel_stats = f" ({stats})"
                    
                    full_prompt = f"🕐 {datetime_info}\n\n" + system_prompt + profile_text + rel_stats + mood_text + online_text + media_info + buttons_info + time_text + pause_text + event_text + lessons_text + "\n\n" + emoji_list
                    
                    history = get_chat_history(event.chat_id)
                    messages = [{"role": "system", "content": full_prompt}]
                    messages.extend(history)
                    
                    result = await ai_client.chat(model, messages, tools=TOOLS)
                    response_text = result.get("content", "") if isinstance(result, dict) else result
                    tool_calls = result.get("tool_calls") if isinstance(result, dict) else None
                    
                    if tool_calls:
                        response_text = await handle_tool_calls(client, model, messages, tool_calls, emoji_list, full_prompt, on_group_join, event.chat_id, None, event.message.id)
                    
                    if response_text and response_text.startswith("Ошибка"):
                        alt_model = config.get("alt_model")
                        if alt_model:
                            print(f"Основная модель не ответила, пробую alt: {alt_model}")
                            result = await ai_client.chat(alt_model, messages, tools=TOOLS)
                            response_text = result.get("content", "") if isinstance(result, dict) else result
                    
                    if response_text and not response_text.startswith("Ошибка"):
                        add_to_history(event.chat_id, "assistant", response_text)
                        print(f"AI ответ: {response_text}")
                        
                        asyncio.create_task(analyze_all(event.sender_id, username, user_name, text, get_chat_history(event.chat_id)))
                        
                        reminder_mins, reminder_topic = parse_reminder_time(text)
                        if reminder_mins > 0 and reminder_topic:
                            send_at = get_send_timestamp(reminder_mins)
                            await reminder_db.add(event.sender_id, event.chat_id, reminder_topic, send_at)
                            print(f"Напоминание '{reminder_topic}' на {format_time_msk(send_at)} МСК")
                        elif needs_ai_parsing(text):
                            asyncio.create_task(try_ai_reminder(event.sender_id, event.chat_id, text))
                    
                    emojis = await emoji_db.get_all()
                    emoji_map = {e["document_id"]: e["emoji"] for e in emojis}
                
                await user_db.update_last_seen(event.sender_id, username, user_name)
                emojis = await emoji_db.get_all()
                emoji_map = {e["document_id"]: e["emoji"] for e in emojis}
        finally:
            typing_task.cancel()
        
        if response_text:
            sticker_sent = await maybe_send_sticker(client, event.chat_id, text, rel_level)
            
            if not sticker_sent:
                response_text = remove_self_mention(response_text)
                response_text = add_caps_emotion(response_text)
                response_text = response_text.replace("\\n", "\n")
                parts = maybe_split_message(response_text)
                
                for i, part in enumerate(parts):
                    final_text, entities = parse_emoji_tags(part, emoji_map, id_map)
                    
                    if entities:
                        await client.send_message(event.chat_id, final_text, formatting_entities=entities)
                    else:
                        await client.send_message(event.chat_id, final_text, parse_mode='md')
                    
                    if i < len(parts) - 1:
                        await asyncio.sleep(0.5)
                
                if i < len(parts) - 1:
                    await asyncio.sleep(0.8)

    async def reminder_checker():
        while True:
            try:
                pending = await reminder_db.get_pending()
                for r in pending:
                    try:
                        topic = r['message']
                        model = config.get("selected_model")
                        
                        is_self_reminder = topic.startswith("[HONO_SELF]")
                        if is_self_reminder:
                            topic = topic.replace("[HONO_SELF]", "").strip()
                            reminder_prompt = f"Ты хотела написать: {topic}. Напиши это сообщение естественно, как будто сама решила написать."
                        else:
                            reminder_prompt = f"Ты напоминаешь пользователю о: {topic}. Напиши короткое напоминание (1-2 предложения)."
                        
                        emoji_list, id_map = await get_emojis_for_ai()
                        
                        result = await ai_client.chat(model, [
                            {"role": "system", "content": system_prompt + "\n\n" + emoji_list},
                            {"role": "user", "content": reminder_prompt}
                        ], max_tokens=150)
                        
                        msg = result.get("content", "") if isinstance(result, dict) else str(result)
                        if not msg or msg.startswith("Ошибка"):
                            msg = topic if is_self_reminder else f"Эй, напоминаю про {topic}!"
                        
                        emojis = await emoji_db.get_all()
                        emoji_map = {e["document_id"]: e["emoji"] for e in emojis}
                        
                        final_text, entities = parse_emoji_tags(msg, emoji_map, id_map)
                        
                        if entities:
                            await client.send_message(r['chat_id'], final_text, formatting_entities=entities)
                        else:
                            await client.send_message(r['chat_id'], final_text)
                        
                        await reminder_db.mark_sent(r['id'])
                        print(f"{'Само-напоминание' if is_self_reminder else 'Напоминание'} '{topic}' отправлено")
                    except Exception as e:
                        print(f"Ошибка отправки напоминания: {e}")
                        await reminder_db.mark_sent(r['id'])
            except Exception as e:
                print(f"Ошибка checker: {e}")
            await asyncio.sleep(30)
    
    async def spontaneous_messages():
        import random
        while True:
            try:
                await asyncio.sleep(random.randint(1800, 7200))
                
                close_users = await user_db.get_close_users(min_level=5)
                if not close_users:
                    continue
                
                user = random.choice(close_users)
                user_id = user['user_id']
                last_seen = user.get('last_seen', 0)
                
                if time.time() - last_seen < 3600:
                    continue
                
                rel_level = user.get('relationship', 0)
                rel_name, rel_behavior = user_db.get_relationship_info(rel_level)
                profile_text = user.get('profile', '')
                
                prompts = [
                    "Ты скучаешь по собеседнику и решила написать первой. Напиши короткое милое сообщение.",
                    "Ты вспомнила о собеседнике. Спроси как дела или что делает.",
                    "Тебе стало скучно и ты решила написать. Напиши что-то игривое или милое.",
                    "Ты хочешь внимания от собеседника. Напиши что скучаешь или думаешь о нём.",
                ]
                
                emoji_list, id_map = await get_emojis_for_ai()
                full_prompt = f"{system_prompt}\n\nУРОВЕНЬ ОТНОШЕНИЙ: {rel_name} — {rel_behavior}\n\n{emoji_list}"
                
                model = config.get("selected_model")
                result = await ai_client.chat(model, [
                    {"role": "system", "content": full_prompt},
                    {"role": "user", "content": random.choice(prompts)}
                ], max_tokens=100)
                
                msg = result.get("content", "") if isinstance(result, dict) else str(result)
                if not msg or msg.startswith("Ошибка"):
                    continue
                
                emojis = await emoji_db.get_all()
                emoji_map = {e["document_id"]: e["emoji"] for e in emojis}
                final_text, entities = parse_emoji_tags(msg, emoji_map, id_map)
                
                if entities:
                    await client.send_message(user_id, final_text, formatting_entities=entities)
                else:
                    await client.send_message(user_id, final_text)
                
                print(f"Спонтанное сообщение для {user_id}: {final_text[:50]}...")
                
            except Exception as e:
                print(f"Ошибка spontaneous: {e}")
            
            await asyncio.sleep(300)
    
    async def learning_loop():
        while True:
            try:
                await asyncio.sleep(600)
                
                if not memory_db:
                    continue
                
                analyze_model = config.get("analyze_model")
                if not analyze_model:
                    continue
                
                lessons_created = await process_pending_interactions(ai_client, analyze_model, memory_db)
                if lessons_created > 0:
                    print(f"[LEARNING] Создано {lessons_created} новых уроков")
                    
            except Exception as e:
                print(f"[LEARNING] Ошибка: {e}")
    
    asyncio.create_task(reminder_checker())
    asyncio.create_task(spontaneous_messages())
    asyncio.create_task(learning_loop())
    
    print("Бот запущен! Ожидание сообщений...")
    print("Нажмите Ctrl+C для остановки")
    
    try:
        await client.run_until_disconnected()
    finally:
        await db.close()
        print("\nБот остановлен")


async def keep_typing(client, chat_id):
    try:
        while True:
            await client(functions.messages.SetTypingRequest(
                peer=chat_id,
                action=SendMessageTypingAction()
            ))
            await asyncio.sleep(4)
    except asyncio.CancelledError:
        pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
