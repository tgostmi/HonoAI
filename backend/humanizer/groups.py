import re
import asyncio
import random
import time

chat_model_index = 0
chat_model_lock = asyncio.Lock()
_skip_cache = {}
_last_ai_call = {}
AI_COOLDOWN = 3


def _should_skip_fast(text: str, context: list, my_username: str) -> tuple:
    text_lower = text.lower().strip()
    
    if len(text_lower) < 3:
        return (True, "too_short")
    
    skip_patterns = [
        r'^\.+$', r'^\?+$', r'^!+$', r'^[а-яa-z]{1,2}$',
        r'^(ок|окей|да|нет|норм|хз|ну|ага|угу|лан|ясно|понял|кек|лол|хах|ахах)$',
        r'^[😂🤣😭💀😎🔥👍👎❤️]+$',
    ]
    for pattern in skip_patterns:
        if re.match(pattern, text_lower):
            return (True, "trivial")
    
    if context and my_username:
        my_count = sum(1 for m in context[-8:] if (m.get('username') or '').lower() == my_username.lower())
        if my_count >= 3:
            return (True, "spam_protection")
    
    return (False, None)


def should_respond_quick(text: str, my_username: str, my_id: int, reply_to_me: bool, mentioned_ids: list = None) -> tuple:
    text_lower = text.lower()
    
    if reply_to_me:
        return (True, "reply")
    
    if mentioned_ids and my_id in mentioned_ids:
        return (True, "mention_id")
    
    if my_username:
        if f"@{my_username.lower()}" in text_lower:
            return (True, "mention_username")
    
    name_patterns = [r'\bхоно\b', r'\bхоночка\b', r'\bhono\b']
    for pattern in name_patterns:
        if re.search(pattern, text_lower):
            return (True, "mention_name")
    
    return (None, None)


async def should_respond_ai(ai_client, models: list, text: str, context: list, my_username: str, sender_username: str = None, chat_id: int = 0) -> tuple:
    global chat_model_index, _skip_cache, _last_ai_call
    
    if not models or not ai_client:
        return (False, None)
    
    if sender_username and sender_username.lower() == my_username.lower():
        return (False, "self_message")
    
    skip, reason = _should_skip_fast(text, context, my_username)
    if skip:
        return (False, reason)
    
    now = time.time()
    if chat_id:
        last_call = _last_ai_call.get(chat_id, 0)
        if now - last_call < AI_COOLDOWN:
            return (False, "cooldown")
        _last_ai_call[chat_id] = now
        
        cache_key = f"{chat_id}_{hash(text[:50])}"
        cached = _skip_cache.get(cache_key)
        if cached and now - cached < 60:
            return (False, "cached_skip")
    
    async with chat_model_lock:
        model = models[chat_model_index % len(models)]
        chat_model_index += 1
    
    context_lines = []
    hono_spoke_last = False
    hono_was_in_chat = False
    last_hono_idx = -1
    
    if context:
        recent = context[-12:]
        for i, m in enumerate(recent):
            username = m.get('username')
            if not username or username == 'None':
                username = f"user_{m.get('user_id', '?')}"
            username = str(username)
            msg = m.get('message', '').replace('\n', ' ')[:100]
            is_hono = username and my_username and username.lower() == my_username.lower()
            if is_hono:
                context_lines.append(f"[Я]: {msg}")
                hono_was_in_chat = True
                last_hono_idx = i
                if i == len(recent) - 1:
                    hono_spoke_last = True
            else:
                context_lines.append(f"[{username}]: {msg}")
    
    context_text = "\n".join(context_lines)
    clean_text = text.replace('\n', ' ')[:150]
    
    hono_count = sum(1 for line in context_lines if line.startswith("[Я]:"))
    recent_5 = context_lines[-5:] if len(context_lines) >= 5 else context_lines
    hono_in_recent = sum(1 for line in recent_5 if line.startswith("[Я]:"))
    
    if hono_in_recent >= 2:
        print(f"[CHAT AI] Много моих сообщений ({hono_in_recent}/5), молчу")
        return (False, "spam_prevention")
    
    msgs_after_hono = len(context_lines) - last_hono_idx - 1 if last_hono_idx >= 0 else 999
    
    system_prompt = """Ты анализируешь нужно ли отвечать. [Я] = твои сообщения.
Отвечай СТРОГО: да или нет"""

    prompt = f"""КОНТЕКСТ ЧАТА:
{context_text}

НОВОЕ СООБЩЕНИЕ от {sender_username or 'user'}: "{clean_text}"

ОТВЕЧАЮ ТОЛЬКО ЕСЛИ:
- Меня НАПРЯМУЮ зовут по имени (Хоно/Hono) или тегают
- Вопрос/просьба АДРЕСОВАНЫ МНЕ лично
- Отвечают НАПРЯМУЮ на моё сообщение и ждут продолжения

НЕ ОТВЕЧАЮ:
- Люди общаются между собой (даже если задают вопросы друг другу)
- Обсуждение где я не участник
- Меня не звали и не спрашивали

Это обычный чат. Если меня не позвали - я молчу.

ОТВЕТ (да/нет):"""

    print(f"[CHAT AI] Контекст ({len(context)} сообщ.):")
    for line in context_text.split('\n')[-6:]:
        print(f"  {line[:120]}")
    print(f"[CHAT AI] Сообщение: {clean_text[:150]}")
    
    response = ""
    attempt = 0
    max_attempts = 50
    current_model_idx = chat_model_index - 1
    
    while attempt < max_attempts:
        current_model = models[current_model_idx % len(models)]
        print(f"[CHAT AI] Модель: {current_model}, попытка {attempt + 1}")
        
        try:
            result = await ai_client.chat(current_model, [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ], retries=1, max_tokens=50)
            
            print(f"[CHAT AI] RAW результат: {repr(result)[:200]}")
            
            if isinstance(result, dict):
                response = result.get("content", "")
                if not response:
                    print(f"[CHAT AI] ОШИБКА: content пустой в dict!")
                    attempt += 1
                    current_model_idx += 1
                    await asyncio.sleep(1)
                    continue
                response = response.lower().strip()
            else:
                response = str(result).lower().strip()
            
            if "prohibited_content" in response or "prohibited content" in response:
                print(f"[CHAT AI] PROHIBITED_CONTENT, пропускаю сообщение")
                return (False, "prohibited")
            
            if "rate limit" in response or "ошибка" in response or "error" in response:
                print(f"[CHAT AI] Rate limit в ответе, меняю модель...")
                current_model_idx += 1
                await asyncio.sleep(2)
                continue
            
            if response and len(response) > 0:
                break
                
            print(f"[CHAT AI] Пустой ответ: '{response}', меняю модель...")
            attempt += 1
            current_model_idx += 1
            await asyncio.sleep(1)
                
        except Exception as e:
            error_str = str(e).lower()
            print(f"[CHAT AI] EXCEPTION: {e}")
            
            if "rate limit" in error_str:
                print(f"[CHAT AI] Rate limit exception, жду 3 сек и меняю модель...")
                current_model_idx += 1
                await asyncio.sleep(3)
                continue
            
            attempt += 1
            current_model_idx += 1
            await asyncio.sleep(1)
    
    print(f"[CHAT AI] Ответ: {response}")
    
    if "да" in response or response == "yes":
        return (True, "ai_decision")
    
    if chat_id:
        cache_key = f"{chat_id}_{hash(text[:50])}"
        _skip_cache[cache_key] = time.time()
        if len(_skip_cache) > 1000:
            old_keys = [k for k, v in _skip_cache.items() if time.time() - v > 300]
            for k in old_keys:
                _skip_cache.pop(k, None)
    
    return (False, "ai_skip")


def get_group_system_prompt(group_info: dict, context: list) -> str:
    prompt_parts = [
        "ТЫ В ГРУППОВОМ ЧАТЕ!",
        "",
        "ПРАВИЛА ПОВЕДЕНИЯ В ГРУППЕ:",
        "- Отвечай КОРОТКО, 1-2 предложения",
        "- Не доминируй, дай другим говорить",
        "- Будь частью беседы, не центром внимания",
        "- Если не знаешь ответ — честно скажи",
        "- Не повторяй то что уже сказали другие",
        "- Следи за темой разговора",
    ]
    
    if group_info:
        prompt_parts.append("")
        prompt_parts.append(f"ГРУППА: {group_info.get('title', '?')}")
        
        if group_info.get('rules'):
            prompt_parts.append(f"ПРАВИЛА ЧАТА: {group_info['rules'][:500]}")
            prompt_parts.append("СТРОГО СОБЛЮДАЙ ПРАВИЛА ЧАТА!")
        
        if group_info.get('staff'):
            prompt_parts.append(f"АДМИНЫ: {group_info['staff'][:200]}")
        
        if group_info.get('topics'):
            prompt_parts.append(f"ТЕМЫ ЧАТА: {group_info['topics']}")
    
    if context:
        prompt_parts.append("")
        prompt_parts.append("НЕДАВНИЕ СООБЩЕНИЯ В ЧАТЕ:")
        for msg in context[-10:]:
            username = msg.get('username', 'user')
            text = msg.get('message', '')[:100]
            prompt_parts.append(f"@{username}: {text}")
    
    return "\n".join(prompt_parts)


async def parse_rules_ai(ai_client, model: str, text: str) -> str:
    if not text or len(text) < 15:
        return None
    
    try:
        check_prompt = f"""Это правила чата? ТЕКСТ: {text[:500]}
Ответь да или нет:"""

        check = await ai_client.chat(model, [
            {"role": "system", "content": "Отвечай только да или нет"},
            {"role": "user", "content": check_prompt}
        ], retries=2, max_tokens=10)
        
        check_response = check.get("content", "").lower().strip() if isinstance(check, dict) else str(check).lower().strip()
        
        if "нет" in check_response or check_response == "no":
            return None
        
        normalize_prompt = f"""Преобразуй правила чата в список с наказаниями.

ИСХОДНЫЙ ТЕКСТ:
{text[:1500]}

ФОРМАТ ОТВЕТА:
1. Правило - наказание (мут/бан/варн + время если есть)
2. Правило - наказание
и т.д.

ПРАВИЛА:
- Сохраняй смысл, но пиши кратко
- Допустимые наказания: мут, бан, варн (можно с временем: мут 1ч, мут 10м, бан 1д)
- Если наказание не указано - пиши "мут"
- Только правила с нарушениями, без общих фраз

ОТВЕТ:"""

        result = await ai_client.chat(model, [
            {"role": "system", "content": "Преобразуй правила в список. Формат: 1. Правило - наказание"},
            {"role": "user", "content": normalize_prompt}
        ], retries=3, max_tokens=500)
        
        response = result.get("content", "") if isinstance(result, dict) else str(result)
        
        if response and len(response) > 20 and not response.startswith("Ошибка"):
            return response[:2000]
        return text[:2000]
    except:
        return text[:2000] if len(text) > 50 else None


async def parse_staff_ai(ai_client, model: str, text: str) -> str:
    if not text or len(text) < 10:
        return None
    
    try:
        prompt = f"""Это список админов/модераторов чата или что-то другое?

ТЕКСТ:
{text[:1000]}

Если это список стаффа (админы, модеры, владельцы с юзернеймами) — ответь "да".
Если это не список стаффа — ответь "нет".
Ответь ОДНИМ словом:"""

        result = await ai_client.chat(model, [
            {"role": "system", "content": "Определи это список стаффа или нет. Отвечай только 'да' или 'нет'."},
            {"role": "user", "content": prompt}
        ], retries=2, max_tokens=10)
        
        response = result.get("content", "").lower().strip() if isinstance(result, dict) else str(result).lower().strip()
        
        if "да" in response or response == "yes":
            return text[:1000]
        return None
    except:
        return text[:1000] if "@" in text else None


def parse_rules_response(text: str) -> str:
    if not text or len(text) < 20:
        return None
    
    text_lower = text.lower()
    
    rule_indicators = [
        'правил', 'запрещ', 'нельзя', 'разреш', 'можно', 'обязат',
        'rules', 'rule', 'бан', 'мут', 'варн', 'kick', 'предупрежд'
    ]
    
    if not any(ind in text_lower for ind in rule_indicators):
        return None
    
    return text[:2000]


def parse_staff_response(text: str) -> str:
    if not text or len(text) < 10:
        return None
    
    text_lower = text.lower()
    
    staff_indicators = [
        'владел', 'админ', 'модер', 'owner', 'admin', 'staff',
        'создател', 'основател', 'глав', '@'
    ]
    
    if not any(ind in text_lower for ind in staff_indicators):
        return None
    
    return text[:1000]


async def wait_for_bot_response(client, chat_id: int, trigger_msg_id: int, timeout: int = 70) -> str:
    end_time = asyncio.get_event_loop().time() + timeout
    last_checked_id = trigger_msg_id
    
    while asyncio.get_event_loop().time() < end_time:
        await asyncio.sleep(3)
        
        try:
            messages = await client.get_messages(chat_id, limit=10, min_id=last_checked_id)
            
            for msg in messages:
                if msg.id <= trigger_msg_id:
                    continue
                    
                if msg.sender_id and msg.sender_id != (await client.get_me()).id:
                    sender = await msg.get_sender()
                    if sender and getattr(sender, 'bot', False):
                        return msg.message
                
                last_checked_id = max(last_checked_id, msg.id)
                
        except Exception as e:
            print(f"Ошибка ожидания ответа: {e}")
            break
    
    return None


def get_join_greeting() -> str:
    greetings = [
        "прив всем",
        "хей",
        "привет",
        "здаров",
        "приветики",
        "о, привет всем",
    ]
    return random.choice(greetings)

