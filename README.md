# Hono AI

**Hono (炎)** — Telegram userbot с AI-персоной и характером.

Работает через OpenRouter API (Gemini, Claude, GPT и др.)

---

## Установка

```bash
git clone https://github.com/tgostmi/HonoAI.git
cd HonoAI
pip install -r requirements.txt
```

## Настройка

Заполни `config.json`:

| Поле | Откуда взять |
|------|--------------|
| `api_id`, `api_hash` | [my.telegram.org](https://my.telegram.org) |
| `api_key` | [openrouter.ai/keys](https://openrouter.ai/keys) |
| `admins_ids` | Твой Telegram ID |

Отредактируй `data/prompt.txt` под свою персону (опционально)

## Запуск

```bash
python bot.py
```

При первом запуске введи номер телефона и код из Telegram.

---

Для списка команд напиши `/help` в ЛС боту.

---

*"Ore wa Hono da. Yoroshiku."*
