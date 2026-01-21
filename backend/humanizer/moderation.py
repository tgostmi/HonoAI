import re
import asyncio
from typing import Optional, Tuple

mod_analysis_lock = asyncio.Lock()


async def check_promotion(
    ai_client,
    model: str,
    message_text: str,
    sender_role: str,
    reply_to_bot: bool,
    bot_mentioned: bool
) -> Tuple[bool, int]:
    if sender_role not in ['owner', 'admin']:
        return (False, 0)
    
    if not reply_to_bot and not bot_mentioned:
        return (False, 0)
    
    text_lower = message_text.lower().strip()
    
    patterns = [
        r'повыс(?:ить|ь)\s*(?:@?\w+\s+)?(\d+)',
        r'права\s+(\d+)',
        r'уровень\s+(\d+)',
        r'level\s+(\d+)',
        r'promote\s+(\d+)',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text_lower)
        if match:
            level = int(match.group(1))
            if level >= 1:
                return (True, min(level, 3))
    
    prompt = f"""Сообщение от {sender_role}: "{message_text}"

Это команда на повышение бота до модератора/админа?
Если да - какой уровень (1-3)?

Формат ответа:
- "нет" если это не команда повышения
- "да X" где X = уровень 1-3

Ответ:"""

    try:
        result = await ai_client.chat(model, [
            {"role": "system", "content": "Отвечай кратко: нет или да X"},
            {"role": "user", "content": prompt}
        ], retries=2, max_tokens=20)
        
        response = result.get("content", "").lower().strip() if isinstance(result, dict) else str(result).lower().strip()
        
        if response.startswith("да"):
            match = re.search(r'(\d+)', response)
            if match:
                level = int(match.group(1))
                if level >= 1:
                    return (True, min(level, 3))
    except:
        pass
    
    return (False, 0)


async def analyze_violation(
    ai_client,
    model: str,
    message_text: str,
    sender_name: str,
    sender_role: str,
    context: list,
    rules: str,
    warnings_count: int,
    mod_level: int,
    reply_context: dict = None
) -> dict:
    if sender_role in ['owner', 'admin']:
        return {'action': 'none', 'reason': '', 'confidence': 0}
    
    if mod_level == 0:
        return {'action': 'none', 'reason': '', 'confidence': 0}
    
    if len(message_text.strip()) < 10:
        return {'action': 'none', 'reason': '', 'confidence': 0}
    
    rules_text = rules[:800] if rules else "Нет правил"
    
    reply_info = ""
    if reply_context:
        reply_from = "бота" if reply_context.get("is_me") else reply_context.get('from', 'user')
        reply_info = f" (ответ на сообщение {reply_from})"
        if reply_context.get("is_me"):
            return {'action': 'none', 'reason': '', 'confidence': 0}
    
    prompt = f"""**Задача**: Проверить сообщение на нарушение правил чата.
Если нарушение не явное или есть сомнения - нарушения нету!

**Правила чата**:
{rules_text}

**Сообщение**{reply_info}: {message_text}

**Требуемый ответ в JSON**:
{{"is_violation": bool, "rule_number": int или null, "reason": "кратко", "punishment": {{"type": "мут" или "бан", "duration_minutes": int}}}}

Если нарушения нет: {{"is_violation": false, "rule_number": null, "reason": "", "punishment": null}}

ВАЖНО:
- Вопросы ("кто скупает?", "есть чекер?") = НЕ нарушение
- Одно слово без контекста = НЕ нарушение  
- Грубость/оскорбления = НЕ нарушение (если не в правилах явно)
- Нужна 100% уверенность для наказания"""

    try:
        result = await ai_client.chat(model, [
            {"role": "system", "content": "Отвечай ТОЛЬКО валидным JSON. При любых сомнениях is_violation: false"},
            {"role": "user", "content": prompt}
        ], retries=3, max_tokens=150)
        
        response = result.get("content", "") if isinstance(result, dict) else str(result)
        print(f"[MOD AI] {response[:200]}")
        
        import json
        json_match = re.search(r'\{[^{}]*\}', response.replace('\n', ' '))
        if not json_match:
            return {'action': 'none', 'reason': '', 'confidence': 0, 'duration': ''}
        
        try:
            data = json.loads(json_match.group())
        except:
            return {'action': 'none', 'reason': '', 'confidence': 0, 'duration': ''}
        
        if not data.get('is_violation', False):
            return {'action': 'none', 'reason': '', 'confidence': 0, 'duration': ''}
        
        punishment = data.get('punishment') or {}
        action_type = punishment.get('type', 'мут').lower()
        duration_min = punishment.get('duration_minutes', 60)
        reason = data.get('reason', 'Нарушение правил')
        rule_num = data.get('rule_number')
        
        reason = re.sub(r'[^\w\s\.,!?()-]', '', str(reason), flags=re.UNICODE)[:100]
        
        if 'бан' in action_type:
            action = 'ban'
        else:
            action = 'mute'
        
        if duration_min <= 10:
            duration = f"{duration_min}м"
        elif duration_min < 60:
            duration = f"{duration_min}м"
        elif duration_min < 1440:
            duration = f"{duration_min // 60}ч"
        else:
            duration = f"{duration_min // 1440}д"
        
        if mod_level == 1 and action in ['kick', 'ban']:
            action = 'mute'
        elif mod_level == 2 and action == 'ban':
            action = 'kick'
        
        return {
            'action': action,
            'confidence': 100,
            'reason': reason,
            'duration': duration,
            'rule_number': rule_num
        }
        
    except Exception as e:
        print(f"[MODERATION] Ошибка: {e}")
        return {'action': 'none', 'reason': '', 'confidence': 0, 'duration': ''}


def format_mod_command(action: str, duration: str, reason: str, user_mention: str = None) -> str:
    duration_ru = duration.replace('h', 'ч').replace('m', 'м').replace('d', 'д').replace('min', 'мин').replace('hour', 'ч').replace('day', 'д')
    
    if action == 'warn':
        cmd = f"варн"
        if user_mention:
            cmd += f" {user_mention}"
        cmd += f"\n{reason}"
        return cmd
    
    elif action == 'mute':
        cmd = f"мут {duration_ru}"
        if user_mention:
            cmd = f"мут {user_mention} {duration_ru}"
        cmd += f"\n{reason}"
        return cmd
    
    elif action == 'kick':
        cmd = f"кик"
        if user_mention:
            cmd += f" {user_mention}"
        cmd += f"\n{reason}"
        return cmd
    
    elif action == 'ban':
        cmd = f"бан"
        if user_mention:
            cmd += f" {user_mention}"
        cmd += f"\n{reason}"
        return cmd
    
    return ""


def get_mute_duration(warnings_count: int, severity: int) -> str:
    if warnings_count == 0:
        durations = {1: "5 мин", 2: "15 мин", 3: "1 час"}
    elif warnings_count == 1:
        durations = {1: "15 мин", 2: "1 час", 3: "3 часа"}
    elif warnings_count == 2:
        durations = {1: "1 час", 2: "3 часа", 3: "12 часов"}
    else:
        durations = {1: "3 часа", 2: "12 часов", 3: "1 день"}
    
    return durations.get(severity, "1 час")


async def decide_action(
    ai_client,
    model: str,
    violation_data: dict,
    group_info: dict,
    warnings_count: int,
    mod_level: int
) -> dict:
    action = violation_data.get('action', 'none')
    reason = violation_data.get('reason', '')
    rules_duration = violation_data.get('duration', '')
    
    if action == 'none':
        return {'action': 'none', 'execute': False}
    
    if rules_duration:
        duration = rules_duration
    else:
        duration = get_mute_duration(warnings_count, 2)
    
    return {
        'action': action,
        'execute': True,
        'duration': duration,
        'reason': reason,
        'confidence': confidence
    }


async def process_moderation(
    ai_client,
    analyze_model: str,
    message_text: str,
    sender_id: int,
    sender_name: str,
    sender_role: str,
    group_id: int,
    group_db,
    context: list,
    reply_context: dict = None
) -> Optional[str]:
    async with mod_analysis_lock:
        mod_info = await group_db.get_mod_info(group_id)
        mod_level = mod_info.get('mod_level', 0) if mod_info else 0
        
        print(f"[MOD] group_id={group_id}, mod_level={mod_level}, sender={sender_name}, role={sender_role}")
        
        if mod_level == 0:
            print(f"[MOD] Модерация выключена")
            return None
        
        group_info = await group_db.get_group(group_id)
        rules = group_info.get('rules', '') if group_info else ''
        
        if not rules:
            print(f"[MOD] Правил нет в памяти, пропуск модерации")
            return None
        
        print(f"[MOD] Правила: {rules[:100]}...")
        
        warnings_count = await group_db.get_warnings_count(group_id, sender_id)
        
        violation = await analyze_violation(
            ai_client,
            analyze_model,
            message_text,
            sender_name,
            sender_role,
            context,
            rules,
            warnings_count,
            mod_level,
            reply_context
        )
        
        print(f"[MOD] Violation: {violation}")
        
        if violation['action'] == 'none':
            return None
        
        decision = await decide_action(
            ai_client,
            analyze_model,
            violation,
            group_info or {},
            warnings_count,
            mod_level
        )
        
        if not decision.get('execute'):
            return None
        
        if decision['action'] == 'ping_admin':
            return decision['message']
        
        if decision['action'] == 'warn':
            await group_db.add_warning(group_id, sender_id, sender_name, decision['reason'])
            await group_db.update_mod_stats(group_id, 'warn')
        
        cmd = format_mod_command(
            decision['action'],
            decision.get('duration', ''),
            decision['reason']
        )
        
        if cmd:
            await group_db.update_mod_stats(group_id, decision['action'])
        
        return cmd


async def track_admin_action(
    ai_client,
    model: str,
    message_text: str,
    sender_id: int,
    sender_name: str,
    sender_role: str,
    group_id: int,
    group_db
):
    if sender_role not in ['owner', 'admin']:
        return
    
    admin_actions = ['/warn', '/mute', '/kick', '/ban', '/unmute', '/unban']
    
    text_lower = message_text.lower()
    action_found = None
    
    for action in admin_actions:
        if text_lower.startswith(action):
            action_found = action.replace('/', '')
            break
    
    if action_found:
        await group_db.update_admin_performance(group_id, sender_id, sender_name, action_found)

