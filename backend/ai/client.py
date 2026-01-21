import aiohttp
import asyncio
import base64
import json

BASE_URL = "https://openrouter.ai/api/v1"

EMOJI_TOOL = {
    "type": "function",
    "function": {
        "name": "get_emojis",
        "description": "Получить список доступных премиум эмодзи с их описаниями. Используй эту функцию чтобы узнать какие эмодзи можно использовать.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    }
}


class OpenRouterClient:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

    async def chat(self, model: str, messages: list, tools: list = None, tool_results: dict = None, retries: int = 20, max_tokens: int = 500, **kwargs) -> dict:
        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            **kwargs
        }
        
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        
        last_error = None
        for attempt in range(retries):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        f"{BASE_URL}/chat/completions",
                        headers=self.headers,
                        json=payload
                    ) as resp:
                        data = await resp.json()
                        
                        if "error" in data:
                            last_error = data['error'].get('message', 'Unknown error')
                            print(f"[API ERROR] {last_error}")
                            await asyncio.sleep(0.5)
                            continue
                        
                        if "choices" not in data or not data["choices"]:
                            print(f"[API] Нет choices в ответе: {str(data)[:200]}")
                            last_error = "No choices in response"
                            continue
                        
                        choice = data["choices"][0]
                        message = choice.get("message", {})
                        content = message.get("content", "")
                        
                        if not content and choice.get("finish_reason") == "length":
                            print(f"[API] Ответ обрезан по длине")
                        
                        return {
                            "content": content,
                            "tool_calls": message.get("tool_calls"),
                            "finish_reason": choice.get("finish_reason")
                        }
            except Exception as e:
                last_error = str(e)
                await asyncio.sleep(0.5)
        
        return {"content": f"Ошибка после {retries} попыток: {last_error}", "tool_calls": None, "finish_reason": "error"}

    async def chat_with_image(self, model: str, messages: list, image_data: bytes, retries: int = 20, max_tokens: int = 500, **kwargs) -> str:
        b64_image = base64.b64encode(image_data).decode('utf-8')
        
        last_msg = messages[-1]
        content = [
            {"type": "text", "text": last_msg["content"]},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_image}"}}
        ]
        
        messages_with_image = messages[:-1] + [{"role": "user", "content": content}]
        
        payload = {
            "model": model,
            "messages": messages_with_image,
            "max_tokens": max_tokens,
            **kwargs
        }
        
        last_error = None
        for attempt in range(retries):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        f"{BASE_URL}/chat/completions",
                        headers=self.headers,
                        json=payload
                    ) as resp:
                        data = await resp.json()
                        if "error" in data:
                            last_error = data['error'].get('message', 'Unknown error')
                            await asyncio.sleep(0.5)
                            continue
                        return data["choices"][0]["message"]["content"]
            except Exception as e:
                last_error = str(e)
                await asyncio.sleep(0.5)
        
        return f"Ошибка после {retries} попыток: {last_error}"

    async def get_models(self) -> list:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{BASE_URL}/models",
                headers=self.headers
            ) as resp:
                data = await resp.json()
                return data.get("data", [])

    async def get_popular_models(self, free_only: bool = False) -> list:
        url = "https://openrouter.ai/api/frontend/models/find?order=most-popular&supported_parameters=tools"
        if free_only:
            url += "&max_price=0"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=self.headers) as resp:
                data = await resp.json()
                models = data.get("data", {}).get("models", [])
                return [m["slug"] for m in models]

    async def get_vision_models(self, free_only: bool = False) -> list:
        url = "https://openrouter.ai/api/frontend/models/find?order=most-popular&input_modalities=image%2Ctext&supported_parameters=tools"
        if free_only:
            url += "&max_price=0"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=self.headers) as resp:
                data = await resp.json()
                models = data.get("data", {}).get("models", [])
                return models

    async def get_credits(self) -> dict:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{BASE_URL}/credits",
                headers=self.headers
            ) as resp:
                data = await resp.json()
                credits_data = data.get("data", {})
                total = credits_data.get("total_credits", 0)
                usage = credits_data.get("total_usage", 0)
                return {"total": total, "usage": usage, "balance": total - usage}
