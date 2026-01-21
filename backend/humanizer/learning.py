import asyncio
from typing import Optional, Dict, List

LESSON_CATEGORIES = {
    "mistake": "Ошибка - не делай так",
    "success": "Успех - делай так",
    "style": "Стиль общения",
    "knowledge": "Знание/факт",
    "trigger": "Триггер - избегай",
    "preference": "Предпочтение юзеров"
}


async def analyze_interaction_for_lesson(
    ai_client,
    model: str,
    my_message: str,
    user_reaction: str,
    reaction_type: str
) -> Optional[Dict]:
    if reaction_type == "neutral":
        return None
    
    if reaction_type == "positive" and len(user_reaction) < 5:
        return None
    
    prompt = f"""Проанализируй взаимодействие и извлеки урок если есть.

МОЁ СООБЩЕНИЕ: {my_message[:300]}
РЕАКЦИЯ ЮЗЕРА: {user_reaction[:300]}
ТИП РЕАКЦИИ: {reaction_type}

ТИПЫ УРОКОВ:
- mistake: я сделала ошибку, надо запомнить
- success: это сработало хорошо
- correction: меня поправили, запомнить правильный ответ
- trigger: это вызвало негатив, избегать
- style: урок о стиле общения

ОТВЕТ В ФОРМАТЕ:
type: тип_урока или none
lesson: краткий урок (1 предложение)
trigger: ключевые слова когда применять

Если урока нет - пиши type: none"""

    try:
        result = await ai_client.chat(model, [
            {"role": "system", "content": "Извлекай уроки из взаимодействий. Будь кратким."},
            {"role": "user", "content": prompt}
        ], retries=2, max_tokens=100)
        
        response = result.get("content", "") if isinstance(result, dict) else str(result)
        
        if "type: none" in response.lower() or "none" == response.strip().lower():
            return None
        
        import re
        type_match = re.search(r'type:\s*(\w+)', response.lower())
        lesson_match = re.search(r'lesson:\s*(.+?)(?:\n|trigger:|$)', response, re.IGNORECASE)
        trigger_match = re.search(r'trigger:\s*(.+?)(?:\n|$)', response, re.IGNORECASE)
        
        if not type_match or not lesson_match:
            return None
        
        lesson_type = type_match.group(1)
        if lesson_type == "none":
            return None
        
        return {
            "category": lesson_type,
            "lesson": lesson_match.group(1).strip()[:200],
            "trigger_context": trigger_match.group(1).strip()[:100] if trigger_match else None
        }
        
    except Exception as e:
        print(f"[LEARNING] Ошибка анализа: {e}")
        return None


async def process_pending_interactions(ai_client, model: str, memory_db) -> int:
    interactions = await memory_db.get_unanalyzed_interactions(limit=10)
    
    if not interactions:
        return 0
    
    processed_ids = []
    lessons_created = 0
    
    for interaction in interactions:
        if interaction['reaction_type'] != 'neutral':
            lesson_data = await analyze_interaction_for_lesson(
                ai_client,
                model,
                interaction['my_message'],
                interaction['user_reaction'],
                interaction['reaction_type']
            )
            
            if lesson_data:
                await memory_db.add_lesson(
                    category=lesson_data['category'],
                    lesson=lesson_data['lesson'],
                    trigger_context=lesson_data.get('trigger_context'),
                    importance=2 if interaction['reaction_type'] == 'negative' else 1,
                    chat_id=interaction['chat_id'],
                    user_id=interaction['user_id']
                )
                lessons_created += 1
                print(f"[LEARNING] Новый урок: {lesson_data['lesson'][:50]}...")
        
        processed_ids.append(interaction['id'])
    
    await memory_db.mark_interactions_analyzed(processed_ids)
    
    return lessons_created


def format_lessons_for_prompt(lessons: List[Dict], max_chars: int = 500) -> str:
    if not lessons:
        return ""
    
    lines = ["ПОМНИ (уроки из опыта):"]
    total_chars = len(lines[0])
    
    for lesson in lessons:
        line = f"• {lesson['lesson']}"
        if total_chars + len(line) > max_chars:
            break
        lines.append(line)
        total_chars += len(line)
    
    if len(lines) == 1:
        return ""
    
    return "\n".join(lines)


async def get_contextual_lessons(memory_db, context: str, category: str = None, limit: int = 5) -> str:
    lessons = await memory_db.get_relevant_lessons(context=context, category=category, limit=limit)
    
    for lesson in lessons:
        await memory_db.mark_lesson_used(lesson['id'])
    
    return format_lessons_for_prompt(lessons)


async def quick_learn(memory_db, category: str, lesson: str, trigger: str = None, 
                      chat_id: int = None, user_id: int = None) -> int:
    return await memory_db.add_lesson(
        category=category,
        lesson=lesson,
        trigger_context=trigger,
        importance=3,
        chat_id=chat_id,
        user_id=user_id
    )

