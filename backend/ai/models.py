from .client import OpenRouterClient


async def get_models(client: OpenRouterClient) -> tuple[list, list, list]:
    models = await client.get_models()
    popular_paid = await client.get_popular_models(free_only=False)
    popular_free = await client.get_popular_models(free_only=True)
    return models, popular_paid, popular_free


async def get_vision_models(client: OpenRouterClient) -> tuple[list, list]:
    free_models = await client.get_vision_models(free_only=True)
    paid_models = await client.get_vision_models(free_only=False)
    
    free_slugs = {m["slug"] for m in free_models}
    paid_only = [m for m in paid_models if m["slug"] not in free_slugs]
    
    return free_models, paid_only


def get_price(model: dict) -> float:
    pricing = model.get("pricing", {})
    prompt = float(pricing.get("prompt", 0))
    completion = float(pricing.get("completion", 0))
    return prompt + completion


def is_free(model: dict) -> bool:
    return get_price(model) == 0


def sort_models(models: list, popular_paid: list, popular_free: list) -> tuple[list, list]:
    paid_rank = {slug: i for i, slug in enumerate(popular_paid)}
    free_rank = {slug: i for i, slug in enumerate(popular_free)}
    
    free = []
    paid = []
    
    for m in models:
        if is_free(m):
            free.append(m)
        else:
            paid.append(m)
    
    free.sort(key=lambda m: free_rank.get(m["id"], len(free_rank)))
    paid.sort(key=lambda m: paid_rank.get(m["id"], len(paid_rank)))
    
    return free, paid


def format_price(price: float) -> str:
    price_per_m = price * 1_000_000
    if price_per_m == 0:
        return "free"
    if price_per_m < 0.01:
        return f"${price_per_m:.4f}"
    return f"${price_per_m:.2f}"
