TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "join_group",
            "description": "Зайти/присоединиться к группе. Используй когда просят зайти, заглянуть, присоединиться к группе/чату.",
            "parameters": {
                "type": "object",
                "properties": {
                    "group_link": {
                        "type": "string",
                        "description": "Ссылка (t.me/...), юзернейм (@name), название группы из памяти, или 'last'/'туда'"
                    }
                },
                "required": ["group_link"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_group_info",
            "description": "Получить информацию о группе (название, количество участников). Используй чтобы узнать что за группа.",
            "parameters": {
                "type": "object",
                "properties": {
                    "group_link": {
                        "type": "string",
                        "description": "Ссылка на группу или юзернейм"
                    }
                },
                "required": ["group_link"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_group_rules",
            "description": "Получить сохранённые правила группы из памяти.",
            "parameters": {
                "type": "object",
                "properties": {
                    "group_link": {
                        "type": "string",
                        "description": "Ссылка, юзернейм или 'current' для текущей группы"
                    }
                },
                "required": ["group_link"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_group_staff",
            "description": "Получить сохранённый список админов группы из памяти.",
            "parameters": {
                "type": "object",
                "properties": {
                    "group_link": {
                        "type": "string",
                        "description": "Ссылка, юзернейм или 'current' для текущей группы"
                    }
                },
                "required": ["group_link"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_group_rules",
            "description": "Запросить правила группы командой /rules. Используй если правил нет в памяти или нужно обновить.",
            "parameters": {
                "type": "object",
                "properties": {
                    "group_link": {
                        "type": "string",
                        "description": "Группа где запросить правила, или 'current' для текущей"
                    }
                },
                "required": ["group_link"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_group_staff",
            "description": "Запросить список админов командой /staff. Используй если стаффа нет в памяти или нужно обновить.",
            "parameters": {
                "type": "object",
                "properties": {
                    "group_link": {
                        "type": "string",
                        "description": "Группа где запросить стафф, или 'current' для текущей"
                    }
                },
                "required": ["group_link"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "unmute_user",
            "description": "Размутить пользователя. ТОЛЬКО если владелец группы попросил!",
            "parameters": {
                "type": "object",
                "properties": {
                    "username": {
                        "type": "string",
                        "description": "Username или имя пользователя которого нужно размутить"
                    },
                    "group_link": {
                        "type": "string",
                        "description": "Группа где размутить, или 'current' для текущей"
                    }
                },
                "required": ["username"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_user_memory",
            "description": "Получить информацию о пользователе из памяти (факты, интересы, даты). Используй когда хочешь вспомнить что знаешь о человеке.",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_identifier": {
                        "type": "string",
                        "description": "Username (@username), имя или ID пользователя"
                    }
                },
                "required": ["user_identifier"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_chat_history",
            "description": "Поиск сообщений в истории чата по ключевым словам. Используй когда хочешь найти что обсуждали раньше.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Ключевые слова для поиска"
                    },
                    "group_link": {
                        "type": "string",
                        "description": "Группа где искать, или 'last'/'here' для текущей"
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function", 
        "function": {
            "name": "get_chat_context",
            "description": "Получить последние сообщения из чата для понимания контекста беседы.",
            "parameters": {
                "type": "object",
                "properties": {
                    "group_link": {
                        "type": "string",
                        "description": "Группа откуда взять контекст, или 'last'/'here' для текущей"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Количество сообщений (по умолчанию 15)"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "remember_this",
            "description": "Запомнить важный факт о человеке или событии. Используй когда узнаёшь что-то важное.",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_identifier": {
                        "type": "string",
                        "description": "О ком запомнить (@username или имя)"
                    },
                    "fact": {
                        "type": "string",
                        "description": "Что запомнить (кратко, 1 предложение)"
                    },
                    "category": {
                        "type": "string",
                        "enum": ["fact", "interest", "date", "opinion"],
                        "description": "Тип информации"
                    }
                },
                "required": ["user_identifier", "fact"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "set_my_reminder",
            "description": "Поставить себе напоминание написать кому-то или сделать что-то.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "Что напомнить"
                    },
                    "delay_minutes": {
                        "type": "integer",
                        "description": "Через сколько минут напомнить"
                    },
                    "target": {
                        "type": "string",
                        "description": "Кому написать (user_id, @username, или 'group:название')"
                    }
                },
                "required": ["text", "delay_minutes"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "express_thought",
            "description": "Выразить свою мысль или реакцию (для внутренних процессов). Используй когда хочешь что-то сделать по своей инициативе.",
            "parameters": {
                "type": "object",
                "properties": {
                    "thought": {
                        "type": "string",
                        "description": "Твоя мысль или что хочешь сделать"
                    },
                    "action": {
                        "type": "string",
                        "enum": ["say_later", "change_topic", "ask_about", "share_opinion", "ignore"],
                        "description": "Что сделать с этой мыслью"
                    }
                },
                "required": ["thought"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_knowledge",
            "description": "Поиск в базе знаний по куки/Roblox тематике. Используй когда спрашивают про куки, робуксы, трейды и т.д.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Что искать (вопрос или ключевые слова)"
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_tone",
            "description": "Проанализировать тон сообщения (сарказм, ирония, шутка, серьёзно). Используй если не уверена как понимать сообщение.",
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "Сообщение для анализа"
                    },
                    "context": {
                        "type": "string",
                        "description": "Контекст разговора (опционально)"
                    }
                },
                "required": ["message"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_user_info",
            "description": "Найти и получить информацию о пользователе. Умный поиск по ID, username, имени или любым ключевым словам из профиля.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Поисковый запрос: ID, @username, имя, фамилия или любое слово для поиска (пример: 'Саша', '@gostmi', 'из Москвы')"
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_extended_history",
            "description": "Получить расширенную историю чата. Используй ТОЛЬКО если не хватает контекста для понимания разговора.",
            "parameters": {
                "type": "object",
                "properties": {
                    "count": {
                        "type": "integer",
                        "description": "Количество сообщений (макс 50)"
                    }
                },
                "required": ["count"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_skupki",
            "description": "Найти скупщиков/продавцов в чате. Используй когда спрашивают 'кто скупает X', 'где купить Y', 'кто продаёт Z'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Что ищем: robux, korblox, headless, cookie, limited, account и т.д."
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_current_chat_info",
            "description": "Получить полную информацию о ТЕКУЩЕМ чате: атмосфера, темы, стиль общения, ключевые участники, правила, заметки. Используй когда нужно вспомнить контекст этого чата.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "remember_about_group",
            "description": "Запомнить что-то важное о текущей группе/чате. Используй когда узнала что-то новое о чате.",
            "parameters": {
                "type": "object",
                "properties": {
                    "atmosphere": {
                        "type": "string",
                        "description": "Атмосфера чата (дружелюбный, токсичный, деловой и т.д.)"
                    },
                    "topics": {
                        "type": "string",
                        "description": "Основные темы обсуждений"
                    },
                    "style": {
                        "type": "string",
                        "description": "Стиль общения в чате"
                    },
                    "members": {
                        "type": "string",
                        "description": "Ключевые/активные участники"
                    },
                    "note": {
                        "type": "string",
                        "description": "Любая другая важная заметка о чате"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "send_reaction",
            "description": "Поставить реакцию (ПРЕМИУМ EMOJI) на сообщение. Используй вместо текстового ответа когда достаточно просто отреагировать.",
            "parameters": {
                "type": "object",
                "properties": {
                    "emoji_id": {
                        "type": "integer",
                        "description": "ID премиум emoji для реакции (из доступных)"
                    },
                    "message_offset": {
                        "type": "integer",
                        "description": "На какое сообщение: 0 = текущее (по умолчанию), -1 = предыдущее, -2 = позапрошлое"
                    }
                },
                "required": ["emoji_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "delete_my_message",
            "description": "Удалить СВОЁ сообщение. Используй если ошиблась или нужно убрать своё сообщение.",
            "parameters": {
                "type": "object",
                "properties": {
                    "message_offset": {
                        "type": "integer",
                        "description": "Какое моё сообщение удалить: -1 = последнее моё (по умолчанию), -2 = предпоследнее моё"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_pinned_messages",
            "description": "Получить закреплённые сообщения в текущем чате. Часто там важная информация (правила, ссылки, контакты).",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "schedule_message",
            "description": "Запланировать отправку сообщения позже. Используй когда просят напомнить или отправить что-то в определённое время.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "Текст сообщения"
                    },
                    "delay_minutes": {
                        "type": "integer",
                        "description": "Через сколько минут отправить (от 1 до 1440)"
                    }
                },
                "required": ["text", "delay_minutes"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "forward_message",
            "description": "Переслать сообщение из текущего чата в другой чат/ЛС.",
            "parameters": {
                "type": "object",
                "properties": {
                    "to_chat": {
                        "type": "string",
                        "description": "Куда переслать: @username, chat_id, или 'owner' для владельца"
                    },
                    "message_offset": {
                        "type": "integer",
                        "description": "Какое сообщение: 0 = текущее, -1 = предыдущее"
                    }
                },
                "required": ["to_chat"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "reply_to_message",
            "description": "Ответить на КОНКРЕТНОЕ сообщение из истории (не текущее). Используй когда нужно ответить на старое сообщение.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "Текст ответа"
                    },
                    "message_offset": {
                        "type": "integer",
                        "description": "На какое сообщение ответить: -1 = предыдущее, -2 = позапрошлое, и т.д. (от -1 до -20)"
                    },
                    "search_text": {
                        "type": "string",
                        "description": "Или найти сообщение по тексту (часть текста сообщения на которое нужно ответить)"
                    }
                },
                "required": ["text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "send_dm",
            "description": "Написать пользователю в личные сообщения. ВАЖНО: можно писать только тем, кто УЖЕ писал тебе раньше, иначе спам-бан!",
            "parameters": {
                "type": "object",
                "properties": {
                    "user": {
                        "type": "string",
                        "description": "Кому написать: @username или user_id"
                    },
                    "text": {
                        "type": "string",
                        "description": "Текст сообщения"
                    }
                },
                "required": ["user", "text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "add_contact",
            "description": "Добавить пользователя в контакты. Нужно если у пользователя спам-бан и он просит добавить в КН, чтобы могли переписываться.",
            "parameters": {
                "type": "object",
                "properties": {
                    "user": {
                        "type": "string",
                        "description": "Кого добавить: @username или user_id"
                    },
                    "first_name": {
                        "type": "string",
                        "description": "Имя для контакта (можно взять из профиля или придумать)"
                    }
                },
                "required": ["user"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "check_can_dm",
            "description": "Проверить можно ли написать пользователю в ЛС (писал ли он раньше, есть ли спам-бан, платные сообщения). Используй ПЕРЕД send_dm если не уверена.",
            "parameters": {
                "type": "object",
                "properties": {
                    "user": {
                        "type": "string",
                        "description": "Кого проверить: @username или user_id"
                    }
                },
                "required": ["user"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "click_button",
            "description": "Нажать на inline-кнопку в сообщении. Кнопки видны в контексте как [🔘 текст]. Можно нажать по тексту кнопки или по её номеру.",
            "parameters": {
                "type": "object",
                "properties": {
                    "button": {
                        "type": "string",
                        "description": "Текст кнопки или её номер (1, 2, 3...)"
                    },
                    "message_offset": {
                        "type": "integer",
                        "description": "На сколько сообщений назад (0 = текущее, 1 = предыдущее). По умолчанию 0"
                    }
                },
                "required": ["button"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "resolve_user",
            "description": "Умный поиск пользователя. Найти user_id по @username, имени, фамилии или части ника. Возвращает ID, имя и username.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "@username, имя, часть ника или user_id"
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_common_chats",
            "description": "Получить список общих групп/каналов с пользователем.",
            "parameters": {
                "type": "object",
                "properties": {
                    "user": {
                        "type": "string",
                        "description": "@username или user_id"
                    }
                },
                "required": ["user"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_profile_gifts",
            "description": "Получить NFT подарки/коллекционные предметы из профиля. Без параметров - свои подарки, с user - подарки пользователя.",
            "parameters": {
                "type": "object",
                "properties": {
                    "user": {
                        "type": "string",
                        "description": "@username или user_id. Пусто = свой профиль"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_full_profile",
            "description": "Получить полную информацию о профиле: bio, premium статус, фото, общие чаты и т.д.",
            "parameters": {
                "type": "object",
                "properties": {
                    "user": {
                        "type": "string",
                        "description": "@username или user_id"
                    }
                },
                "required": ["user"]
            }
        }
    }
]

TOOL_NAMES = [t["function"]["name"] for t in TOOLS]

