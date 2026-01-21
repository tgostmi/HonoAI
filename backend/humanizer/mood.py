MOOD_DESCRIPTIONS = {
    -2: "раздражена, отвечает резко и коротко, может послать",
    -1: "немного недовольна, сдержанна, отвечает сухо",
    0: "нейтральное настроение, обычное общение",
    1: "в хорошем настроении, дружелюбна и открыта",
    2: "отличное настроение, игрива, флиртует, мила"
}

MOOD_ANALYZE_PROMPT = """Оцени настроение собеседника по его сообщению.

СООБЩЕНИЕ: {message}

Как собеседник относится к тебе? Выбери ОДНО число:
-2 = грубит, оскорбляет, хамит
-1 = недоволен, раздражён, холоден
0 = нейтрально, просто общается
1 = дружелюбен, позитивен, вежлив
2 = очень мил, флиртует, комплименты

Ответь ТОЛЬКО числом от -2 до 2:"""


async def analyze_mood_ai(ai_client, model: str, message: str) -> int:
    if not ai_client or not model:
        return 0
    
    try:
        prompt = MOOD_ANALYZE_PROMPT.format(message=message[:200])
        messages = [
            {"role": "system", "content": "Ты анализатор настроения. Отвечай только числом."},
            {"role": "user", "content": prompt}
        ]
        result = await ai_client.chat(model, messages, retries=5, max_tokens=2000)
        response = result.get("content", "0") if isinstance(result, dict) else str(result)
        
        response = response.strip().replace("+", "")
        for char in response:
            if char in "-0123456789":
                if char == "-" and len(response) > 1:
                    return max(-2, min(2, int(response[:2])))
                elif char.isdigit():
                    return max(-2, min(2, int(char)))
        return 0
    except:
        return 0


def get_mood_prompt(mood: int) -> str:
    mood = max(-2, min(2, mood))
    return MOOD_DESCRIPTIONS.get(mood, MOOD_DESCRIPTIONS[0])


def update_mood(current: int, change: int) -> int:
    new_mood = current + change
    return max(-2, min(2, new_mood))
