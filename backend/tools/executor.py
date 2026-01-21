import re
import time
import asyncio
from telethon import functions
from telethon.tl.types import Channel, Chat, User, InputPeerUser, ReactionCustomEmoji, MessageEntityMentionName
from telethon.tl.functions.messages import SendReactionRequest, GetCommonChatsRequest
from telethon.tl.functions.contacts import AddContactRequest, GetContactsRequest
from telethon.tl.functions.users import GetFullUserRequest
try:
    from telethon.tl.functions.payments import GetSavedStarGiftsRequest
    HAS_STAR_GIFTS = True
except ImportError:
    HAS_STAR_GIFTS = False
from telethon.errors import (
    UserAlreadyParticipantError,
    InviteHashExpiredError,
    InviteHashInvalidError,
    ChatAdminRequiredError,
    ChannelPrivateError,
    UsernameNotOccupiedError,
    FloodWaitError,
    UserPrivacyRestrictedError,
    PeerFloodError,
    UserIsBlockedError,
    InputUserDeactivatedError,
    MessageIdInvalidError,
    ReactionInvalidError
)

recent_groups = {}
known_dm_users = set()
pinned_cache = {}
my_messages_cache = {}


async def resolve_group_link(client, group_link: str, group_db=None) -> int:
    group_link = group_link.strip().lower()
    
    if group_link in ["last", "туда", "оттуда", "тут", "here"]:
        if "last" in recent_groups:
            entity = recent_groups["last"]
            return entity.id if hasattr(entity, 'id') else None
        if group_db:
            groups = await group_db.get_all_groups()
            if groups:
                groups.sort(key=lambda x: x.get('last_activity', 0), reverse=True)
                return groups[0]['group_id']
        return None
    
    if group_link in recent_groups:
        entity = recent_groups[group_link]
        return entity.id if hasattr(entity, 'id') else entity
    
    if group_db:
        groups = await group_db.get_all_groups()
        for g in groups:
            title = (g.get('title') or '').lower()
            username = (g.get('username') or '').lower()
            group_id = str(g.get('group_id', ''))
            
            if group_link == title or group_link == username or group_link == group_id:
                return g['group_id']
            
            if group_link in title or title in group_link:
                return g['group_id']
            
            search_words = group_link.replace('@', '').split()
            if all(word in title for word in search_words):
                return g['group_id']
    
    id_type, identifier = extract_group_identifier(group_link)
    if identifier:
        try:
            entity = await client.get_entity(identifier)
            if hasattr(entity, 'id'):
                return entity.id
        except:
            pass
    
    return None


async def smart_find_group(client, name: str, group_db=None, ai_client=None, analyze_model=None) -> dict:
    name = name.strip()
    name_lower = name.lower()
    
    if name_lower in ["last", "туда", "оттуда"]:
        if "last" in recent_groups:
            entity = recent_groups["last"]
            return {"found": True, "entity": entity, "group_id": entity.id, "title": getattr(entity, 'title', 'группа')}
        if group_db:
            groups = await group_db.get_all_groups()
            if groups:
                groups.sort(key=lambda x: x.get('last_activity', 0), reverse=True)
                g = groups[0]
                return {"found": True, "group_id": g['group_id'], "title": g.get('title', 'группа'), "from_db": True}
        return {"found": False, "error": "Не помню последнюю группу"}
    
    if name_lower in recent_groups:
        entity = recent_groups[name_lower]
        return {"found": True, "entity": entity, "group_id": entity.id, "title": getattr(entity, 'title', name)}
    
    if group_db:
        groups = await group_db.get_all_groups()
        best_match = None
        best_score = 0
        
        for g in groups:
            title = (g.get('title') or '').lower()
            username = (g.get('username') or '').lower()
            
            if name_lower == title or name_lower == username:
                return {"found": True, "group_id": g['group_id'], "title": g.get('title'), "from_db": True}
            
            score = 0
            if name_lower in title:
                score = len(name_lower) / len(title) * 100
            elif title in name_lower:
                score = len(title) / len(name_lower) * 80
            
            words = name_lower.split()
            matching_words = sum(1 for w in words if w in title)
            if matching_words > 0:
                word_score = (matching_words / len(words)) * 70
                score = max(score, word_score)
            
            if score > best_score and score > 30:
                best_score = score
                best_match = g
        
        if best_match:
            return {"found": True, "group_id": best_match['group_id'], "title": best_match.get('title'), "from_db": True, "confidence": best_score}
    
    id_type, identifier = extract_group_identifier(name)
    if identifier:
        try:
            entity = await client.get_entity(identifier)
            if isinstance(entity, (Channel, Chat)):
                recent_groups["last"] = entity
                recent_groups[entity.title.lower()] = entity
                return {"found": True, "entity": entity, "group_id": entity.id, "title": entity.title}
        except:
            pass
    
    return {"found": False, "error": f"Не нашла группу '{name}'"}


def extract_group_identifier(link: str) -> tuple:
    link = link.strip()
    
    invite_match = re.search(r't\.me/\+([a-zA-Z0-9_-]+)', link)
    if invite_match:
        return ("invite", invite_match.group(1))
    
    invite_match = re.search(r't\.me/joinchat/([a-zA-Z0-9_-]+)', link)
    if invite_match:
        return ("invite", invite_match.group(1))
    
    username_match = re.search(r't\.me/([a-zA-Z0-9_]+)', link)
    if username_match:
        return ("username", username_match.group(1))
    
    if link.startswith("@"):
        return ("username", link[1:])
    
    if re.match(r'^[a-zA-Z0-9_]+$', link):
        return ("username", link)
    
    return (None, None)


async def join_group(client, group_link: str, group_db=None) -> dict:
    try:
        link_lower = group_link.lower().strip()
        
        if link_lower in ["last", "туда", "обратно", "назад", "та группа"]:
            if "last" in recent_groups:
                entity = recent_groups["last"]
                title = getattr(entity, 'title', 'группа')
                return {"success": True, "message": f"Уже в {title}!", "group_title": title, "group_id": entity.id, "already_member": True}
            elif group_db:
                groups = await group_db.get_all_groups()
                if groups:
                    groups.sort(key=lambda x: x.get('last_activity', 0), reverse=True)
                    g = groups[0]
                    try:
                        entity = await client.get_entity(g['group_id'])
                        recent_groups["last"] = entity
                        return {"success": True, "message": f"Нашла {g['title']}!", "group_title": g['title'], "group_id": g['group_id'], "already_member": True}
                    except:
                        pass
            return {"success": False, "error": "Не помню последнюю группу, кинь ссылку"}
        
        if link_lower in recent_groups:
            entity = recent_groups[link_lower]
            title = getattr(entity, 'title', 'группа')
            return {"success": True, "message": f"Нашла {title}!", "group_title": title, "group_id": entity.id, "already_member": True}
        
        if group_db:
            found = await smart_find_group(client, group_link, group_db)
            if found.get("found"):
                if found.get("entity"):
                    entity = found["entity"]
                    recent_groups["last"] = entity
                    return {"success": True, "message": f"Нашла {found.get('title')}!", "group_title": found.get('title'), "group_id": entity.id, "already_member": True}
                elif found.get("group_id"):
                    try:
                        entity = await client.get_entity(found["group_id"])
                        recent_groups["last"] = entity
                        return {"success": True, "message": f"Нашла {found.get('title')} в памяти!", "group_title": found.get('title'), "group_id": found["group_id"], "already_member": True}
                    except:
                        pass
        
        id_type, identifier = extract_group_identifier(group_link)
        
        if not identifier:
            return {"success": False, "error": "Не могу распознать ссылку, кинь нормально"}
        
        if id_type == "invite":
            try:
                result = await client(functions.messages.ImportChatInviteRequest(hash=identifier))
                chat = result.chats[0] if result.chats else None
                title = chat.title if chat else "группа"
                if chat:
                    recent_groups["last"] = chat
                    recent_groups[title.lower()] = chat
                    if hasattr(chat, 'id'):
                        recent_groups[str(chat.id)] = chat
                return {"success": True, "message": f"Зашла в {title}!", "group_title": title, "group_id": chat.id if chat else None, "username": getattr(chat, 'username', None) if chat else None, "joined": True}
            except UserAlreadyParticipantError:
                try:
                    check = await client(functions.messages.CheckChatInviteRequest(hash=identifier))
                    if hasattr(check, 'chat'):
                        recent_groups["last"] = check.chat
                        recent_groups[check.chat.title.lower()] = check.chat
                except:
                    pass
                return {"success": True, "message": "Я уже в этой группе", "already_member": True}
            except InviteHashExpiredError:
                return {"success": False, "error": "Ссылка-приглашение устарела"}
            except InviteHashInvalidError:
                return {"success": False, "error": "Неверная ссылка-приглашение"}
        
        else:
            try:
                entity = await client.get_entity(identifier)
                
                if isinstance(entity, (Channel, Chat)):
                    try:
                        await client(functions.channels.JoinChannelRequest(entity))
                        recent_groups["last"] = entity
                        recent_groups[entity.title.lower()] = entity
                        return {"success": True, "message": f"Зашла в {entity.title}!", "group_title": entity.title, "group_id": entity.id, "username": getattr(entity, 'username', None), "joined": True}
                    except UserAlreadyParticipantError:
                        recent_groups["last"] = entity
                        recent_groups[entity.title.lower()] = entity
                        return {"success": True, "message": f"Я уже в {entity.title}", "already_member": True, "group_id": entity.id}
                else:
                    return {"success": False, "error": "Это не группа и не канал"}
                    
            except UsernameNotOccupiedError:
                return {"success": False, "error": f"Группа @{identifier} не найдена"}
            except ChannelPrivateError:
                return {"success": False, "error": "Это приватная группа, нужна ссылка-приглашение"}
                
    except FloodWaitError as e:
        return {"success": False, "error": f"Подожди {e.seconds} сек, Telegram ограничил"}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def leave_group(client, group_link: str, group_db=None) -> dict:
    try:
        link_lower = group_link.lower().strip()
        entity = None
        
        if link_lower in ["last", "эта", "эту", "оттуда", "та группа", "эта группа"]:
            if "last" in recent_groups:
                entity = recent_groups["last"]
        
        if not entity:
            for key in recent_groups:
                if key != "last" and link_lower in key:
                    entity = recent_groups[key]
                    break
        
        if not entity:
            try:
                async for dialog in client.iter_dialogs(limit=100):
                    if dialog.is_group or dialog.is_channel:
                        title = (dialog.title or "").lower()
                        if link_lower in title or title in link_lower:
                            entity = dialog.entity
                            print(f"[LEAVE] Нашёл группу через диалоги: {dialog.title}")
                            break
            except Exception as e:
                print(f"[LEAVE] Ошибка поиска диалогов: {e}")
        
        if not entity and group_db:
            found = await smart_find_group(client, group_link, group_db)
            if found.get("found") and found.get("group_id"):
                try:
                    entity = await client.get_entity(found["group_id"])
                except:
                    pass
        
        if not entity:
            id_type, identifier = extract_group_identifier(group_link)
            
            if identifier:
                if id_type == "invite":
                    if "last" in recent_groups:
                        entity = recent_groups["last"]
                else:
                    try:
                        entity = await client.get_entity(identifier)
                    except:
                        pass
        
        if not entity:
            return {"success": False, "error": f"Не нашла группу '{group_link}' ни в диалогах, ни в памяти"}
        
        if isinstance(entity, Channel):
            title = entity.title
            await client(functions.channels.LeaveChannelRequest(entity))
            if title.lower() in recent_groups:
                del recent_groups[title.lower()]
            return {"success": True, "message": f"Вышла из {title}"}
        elif isinstance(entity, Chat):
            title = entity.title
            await client(functions.messages.DeleteChatUserRequest(entity.id, await client.get_me()))
            if title.lower() in recent_groups:
                del recent_groups[title.lower()]
            return {"success": True, "message": f"Вышла из {title}"}
        else:
            return {"success": False, "error": "Это не группа"}
            
    except Exception as e:
        return {"success": False, "error": str(e)}


async def get_group_info(client, group_link: str) -> dict:
    try:
        id_type, identifier = extract_group_identifier(group_link)
        
        if not identifier:
            return {"success": False, "error": "Не могу распознать группу"}
        
        if id_type == "invite":
            try:
                result = await client(functions.messages.CheckChatInviteRequest(hash=identifier))
                if hasattr(result, 'chat'):
                    chat = result.chat
                    return {
                        "success": True,
                        "title": chat.title,
                        "members": getattr(chat, 'participants_count', '?'),
                        "is_channel": getattr(chat, 'broadcast', False),
                        "already_member": True
                    }
                else:
                    return {
                        "success": True,
                        "title": result.title,
                        "members": result.participants_count,
                        "is_channel": result.broadcast if hasattr(result, 'broadcast') else False,
                        "already_member": False
                    }
            except InviteHashExpiredError:
                return {"success": False, "error": "Ссылка устарела"}
            except InviteHashInvalidError:
                return {"success": False, "error": "Неверная ссылка"}
        
        entity = await client.get_entity(identifier)
        
        if isinstance(entity, (Channel, Chat)):
            full = await client(functions.channels.GetFullChannelRequest(entity))
            return {
                "success": True,
                "title": entity.title,
                "members": full.full_chat.participants_count,
                "is_channel": getattr(entity, 'broadcast', False),
                "username": getattr(entity, 'username', None)
            }
        else:
            return {"success": False, "error": "Это не группа"}
            
    except ChannelPrivateError:
        return {"success": False, "error": "Приватная группа, нужна ссылка"}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def send_message_to_group(client, group_link: str, message: str, send_func=None, group_db=None) -> dict:
    try:
        entity = None
        
        found = await smart_find_group(client, group_link, group_db)
        
        if found.get("found"):
            if found.get("entity"):
                entity = found["entity"]
            elif found.get("group_id"):
                try:
                    entity = await client.get_entity(found["group_id"])
                    recent_groups["last"] = entity
                    recent_groups[found.get("title", "").lower()] = entity
                except Exception as e:
                    return {"success": False, "error": f"Нашла группу в памяти, но не могу подключиться: {e}"}
        
        if not entity:
            return {"success": False, "error": found.get("error", "Не могу найти группу")}
        
        if not isinstance(entity, (Channel, Chat)):
            return {"success": False, "error": "Это не группа"}
        
        if send_func:
            await send_func(entity, message)
        else:
            await client.send_message(entity, message)
        
        return {"success": True, "message": f"Отправила в {entity.title}", "group_title": entity.title}
        
    except ChatAdminRequiredError:
        return {"success": False, "error": "Нет прав писать в этой группе"}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def get_group_rules(client, group_link: str, group_db=None) -> dict:
    if not group_db:
        return {"success": False, "error": "Нет доступа к базе данных"}
    
    link_lower = group_link.lower().strip()
    group_id = None
    
    if link_lower in ["last", "эта", "эту", "та группа"]:
        if "last" in recent_groups:
            group_id = recent_groups["last"].id
    
    if not group_id:
        for key in recent_groups:
            if key != "last" and link_lower in key:
                group_id = recent_groups[key].id
                break
    
    if not group_id:
        id_type, identifier = extract_group_identifier(group_link)
        if identifier and id_type == "username":
            try:
                entity = await client.get_entity(identifier)
                group_id = entity.id
            except:
                pass
    
    if not group_id:
        return {"success": False, "error": "Не могу найти эту группу в памяти"}
    
    group_info = await group_db.get_group(group_id)
    if not group_info:
        return {"success": False, "error": "Нет информации об этой группе"}
    
    rules = group_info.get("rules")
    if not rules:
        return {"success": True, "rules": None, "message": "Правила не установлены или я их не получила"}
    
    return {"success": True, "rules": rules, "group_title": group_info.get("title")}


def parse_staff_text(text: str) -> str:
    import re
    lines = text.strip().split('\n')
    result = []
    current_role = None
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        clean_line = re.sub(r'^[\U0001F300-\U0001F9FF\U00002600-\U000027BF\s]+', '', line)
        clean_line = re.sub(r'\s*\(https?://[^)]+\)', '', clean_line)
        clean_line = clean_line.strip()
        
        if not clean_line:
            continue
        
        has_username = '@' in line or re.search(r't\.me/\w+', line)
        
        if not has_username and len(clean_line) < 30:
            current_role = clean_line
            continue
        
        if current_role:
            result.append(f"{current_role}: {clean_line}")
        else:
            result.append(clean_line)
    
    return "\n".join(result) if result else text[:300]


async def get_group_staff(client, group_link: str, group_db=None) -> dict:
    if not group_db:
        return {"success": False, "error": "Нет доступа к базе данных"}
    
    link_lower = group_link.lower().strip()
    group_id = None
    
    if link_lower in ["last", "эта", "эту", "та группа"]:
        if "last" in recent_groups:
            group_id = recent_groups["last"].id
    
    if not group_id:
        for key in recent_groups:
            if key != "last" and link_lower in key:
                group_id = recent_groups[key].id
                break
    
    if not group_id:
        id_type, identifier = extract_group_identifier(group_link)
        if identifier and id_type == "username":
            try:
                entity = await client.get_entity(identifier)
                group_id = entity.id
            except:
                pass
    
    if not group_id:
        return {"success": False, "error": "Не могу найти эту группу в памяти"}
    
    group_info = await group_db.get_group(group_id)
    if not group_info:
        return {"success": False, "error": "Нет информации об этой группе"}
    
    staff = group_info.get("staff")
    if not staff:
        return {"success": True, "staff": None, "message": "Список стаффа не получен"}
    
    parsed_staff = parse_staff_text(staff)
    
    return {"success": True, "staff": parsed_staff, "raw_staff": staff[:300], "group_title": group_info.get("title")}


async def fetch_group_rules(client, group_link: str, group_db=None, ai_client=None, analyze_model=None) -> dict:
    import asyncio
    
    link_lower = group_link.lower().strip()
    group_id = None
    
    if link_lower in ["current", "текущая", "эта", "here"]:
        if "last" in recent_groups:
            group_id = recent_groups["last"].id
    
    if not group_id:
        group_id = await resolve_group_link(client, group_link, group_db)
    
    if not group_id:
        return {"success": False, "error": "Не могу найти эту группу"}
    
    try:
        sent_msg = await client.send_message(group_id, "/rules")
        print(f"[FETCH] Отправил /rules в {group_id}")
        
        end_time = asyncio.get_event_loop().time() + 30
        last_checked_id = sent_msg.id
        
        while asyncio.get_event_loop().time() < end_time:
            await asyncio.sleep(2)
            
            messages = await client.get_messages(group_id, limit=5, min_id=last_checked_id)
            
            for msg in messages:
                if msg.id <= sent_msg.id:
                    continue
                
                if msg.sender_id and msg.sender_id != (await client.get_me()).id:
                    sender = await msg.get_sender()
                    if sender and getattr(sender, 'bot', False) and msg.message:
                        rules_text = msg.message
                        print(f"[FETCH] Получил ответ на /rules: {rules_text[:100]}...")
                        
                        if group_db:
                            await group_db.update_rules(group_id, rules_text[:2000])
                        
                        return {"success": True, "rules": rules_text[:2000], "saved": True}
                
                last_checked_id = max(last_checked_id, msg.id)
        
        return {"success": False, "error": "Бот не ответил на /rules в течение 30 секунд"}
        
    except Exception as e:
        return {"success": False, "error": f"Ошибка: {e}"}


async def fetch_group_staff(client, group_link: str, group_db=None, ai_client=None, analyze_model=None) -> dict:
    import asyncio
    
    link_lower = group_link.lower().strip()
    group_id = None
    
    if link_lower in ["current", "текущая", "эта", "here"]:
        if "last" in recent_groups:
            group_id = recent_groups["last"].id
    
    if not group_id:
        group_id = await resolve_group_link(client, group_link, group_db)
    
    if not group_id:
        return {"success": False, "error": "Не могу найти эту группу"}
    
    try:
        sent_msg = await client.send_message(group_id, "/staff")
        print(f"[FETCH] Отправил /staff в {group_id}")
        
        end_time = asyncio.get_event_loop().time() + 30
        last_checked_id = sent_msg.id
        
        while asyncio.get_event_loop().time() < end_time:
            await asyncio.sleep(2)
            
            messages = await client.get_messages(group_id, limit=5, min_id=last_checked_id)
            
            for msg in messages:
                if msg.id <= sent_msg.id:
                    continue
                
                if msg.sender_id and msg.sender_id != (await client.get_me()).id:
                    sender = await msg.get_sender()
                    if sender and getattr(sender, 'bot', False) and msg.message:
                        staff_text = msg.message
                        print(f"[FETCH] Получил ответ на /staff: {staff_text[:100]}...")
                        
                        if group_db:
                            await group_db.update_staff(group_id, staff_text[:1000])
                        
                        return {"success": True, "staff": staff_text[:1000], "saved": True}
                
                last_checked_id = max(last_checked_id, msg.id)
        
        return {"success": False, "error": "Бот не ответил на /staff в течение 30 секунд"}
        
    except Exception as e:
        return {"success": False, "error": f"Ошибка: {e}"}


async def unmute_user(client, username: str, group_link: str = "current", group_db=None, sender_role: str = None) -> dict:
    if sender_role != "owner":
        return {"success": False, "error": "Только владелец группы может просить размутить!"}
    
    link_lower = group_link.lower().strip()
    group_id = None
    
    if link_lower in ["current", "текущая", "эта", "here"]:
        if "last" in recent_groups:
            group_id = recent_groups["last"].id
    
    if not group_id:
        group_id = await resolve_group_link(client, group_link, group_db)
    
    if not group_id:
        return {"success": False, "error": "Не могу найти группу"}
    
    username = username.strip()
    if not username.startswith('@'):
        username = f"@{username}"
    
    try:
        unmute_cmd = f"/unmute {username}"
        await client.send_message(group_id, unmute_cmd)
        print(f"[UNMUTE] Отправил: {unmute_cmd}")
        return {"success": True, "message": f"Отправила команду размута для {username}"}
    except Exception as e:
        return {"success": False, "error": f"Ошибка: {e}"}


_knowledge_cache = {}

async def search_knowledge(client, query: str, ai_client=None, analyze_model=None, **kwargs) -> dict:
    import os
    global _knowledge_cache
    
    cache_key = query.lower().strip()[:100]
    if cache_key in _knowledge_cache:
        cached = _knowledge_cache[cache_key]
        if time.time() - cached['time'] < 3600:
            return {**cached['result'], "cached": True}
    
    knowledge_path = "data/knowledge.txt"
    if not os.path.exists(knowledge_path):
        return {"success": False, "error": "База знаний не найдена"}
    
    try:
        with open(knowledge_path, "r", encoding="utf-8") as f:
            knowledge_text = f.read()
    except Exception as e:
        return {"success": False, "error": f"Ошибка чтения базы: {e}"}
    
    if len(knowledge_text) < 50:
        return {"success": False, "error": "База знаний пустая"}
    
    if not ai_client or not analyze_model:
        sections = knowledge_text.split("\n## ")
        query_lower = query.lower()
        relevant = []
        for section in sections:
            if any(word in section.lower() for word in query_lower.split()):
                relevant.append(section[:500])
        
        if relevant:
            result = {"success": True, "answer": "\n\n".join(relevant[:3]), "method": "keyword"}
            _knowledge_cache[cache_key] = {'result': result, 'time': time.time()}
            return result
        return {"success": False, "error": "Ничего не найдено по запросу"}
    
    prompt = f"""БАЗА ЗНАНИЙ:
{knowledge_text}

ВОПРОС: {query}

ИНСТРУКЦИЯ:
1. Найди в базе знаний ТОЧНЫЙ раздел который отвечает на вопрос
2. Если спрашивают про "гейм чекер" - ищи именно "game checker", а не просто "чекер"
3. Если спрашивают про конкретную вещь - найди именно её, не путай с похожими
4. Процитируй найденную информацию ПОЛНОСТЬЮ, не сокращай
5. Если точной информации нет - скажи что нет

ОТВЕТ:"""

    try:
        result = await ai_client.chat(analyze_model, [
            {"role": "system", "content": "Ты точный поисковик по базе знаний. Находи КОНКРЕТНУЮ информацию, не путай похожие термины. Отвечай полно."},
            {"role": "user", "content": prompt}
        ], retries=2, max_tokens=350)
        
        response = result.get("content", "") if isinstance(result, dict) else str(result)
        
        if response:
            print(f"[KNOWLEDGE] Запрос: {query[:50]}, Ответ: {response[:100]}...")
            result = {"success": True, "answer": response, "method": "ai"}
            _knowledge_cache[cache_key] = {'result': result, 'time': time.time()}
            if len(_knowledge_cache) > 200:
                old = sorted(_knowledge_cache.items(), key=lambda x: x[1]['time'])[:50]
                for k, _ in old:
                    _knowledge_cache.pop(k, None)
            return result
        
        return {"success": False, "error": "AI не смог найти ответ"}
        
    except Exception as e:
        return {"success": False, "error": f"Ошибка AI: {e}"}


async def get_user_memory(client, user_identifier: str, user_db=None, **kwargs) -> dict:
    if not user_db:
        return {"success": False, "error": "База данных недоступна"}
    
    user_identifier = user_identifier.strip().lower()
    if user_identifier.startswith('@'):
        user_identifier = user_identifier[1:]
    
    all_profiles = await user_db.get_all_profiles()
    
    for profile in all_profiles:
        username = (profile.get('username') or '').lower()
        name = (profile.get('name') or '').lower()
        user_id = str(profile.get('user_id', ''))
        
        if user_identifier in [username, name, user_id] or user_identifier in name:
            return {
                "success": True,
                "user_id": profile.get('user_id'),
                "username": profile.get('username'),
                "name": profile.get('name'),
                "facts": profile.get('profile'),
                "interests": profile.get('topics'),
                "dates": profile.get('dates'),
                "relationship": profile.get('relationship', 0),
                "mood": profile.get('mood', 0)
            }
    
    return {"success": False, "error": f"Не нашла информацию о {user_identifier}"}


async def search_chat_history(client, query: str, group_link: str = "last", group_db=None, **kwargs) -> dict:
    if not group_db:
        return {"success": False, "error": "База данных недоступна"}
    
    group_id = None
    
    if group_link.lower() in ["last", "here", "тут", "здесь"]:
        groups = await group_db.get_all_groups()
        if groups:
            groups.sort(key=lambda x: x.get('last_activity', 0), reverse=True)
            group_id = groups[0]['group_id']
    else:
        group_id = await resolve_group_link(client, group_link, group_db)
    
    if not group_id:
        return {"success": False, "error": "Не нашла эту группу"}
    
    messages = await group_db.search_messages(group_id, query, limit=15)
    
    if not messages:
        return {"success": True, "found": 0, "message": f"Ничего не нашла по запросу '{query}'"}
    
    results = []
    for msg in messages:
        results.append({
            "from": msg.get('username', 'user'),
            "text": msg.get('message', '')[:200],
            "time": msg.get('timestamp')
        })
    
    return {"success": True, "found": len(results), "messages": results}


async def get_chat_context(client, group_link: str = "last", limit: int = 15, group_db=None, **kwargs) -> dict:
    if not group_db:
        return {"success": False, "error": "База данных недоступна"}
    
    group_id = None
    
    if group_link.lower() in ["last", "here", "тут", "здесь", ""]:
        groups = await group_db.get_all_groups()
        if groups:
            groups.sort(key=lambda x: x.get('last_activity', 0), reverse=True)
            group_id = groups[0]['group_id']
    else:
        group_id = await resolve_group_link(client, group_link, group_db)
    
    if not group_id:
        return {"success": False, "error": "Не нашла эту группу"}
    
    limit = min(max(limit or 15, 5), 30)
    context = await group_db.get_context(group_id, limit=limit)
    
    if not context:
        return {"success": True, "messages": [], "message": "История чата пуста"}
    
    results = []
    for msg in context:
        results.append({
            "from": msg.get('username', 'user'),
            "text": msg.get('message', '')[:300]
        })
    
    group_info = await group_db.get_group(group_id)
    
    return {
        "success": True, 
        "group": group_info.get('title') if group_info else None,
        "count": len(results),
        "messages": results
    }


async def remember_this(client, user_identifier: str, fact: str, category: str = "fact", user_db=None, **kwargs) -> dict:
    if not user_db:
        return {"success": False, "error": "База данных недоступна"}
    
    user_identifier = user_identifier.strip()
    if user_identifier.startswith('@'):
        user_identifier = user_identifier[1:]
    
    all_profiles = await user_db.get_all_profiles()
    target_user = None
    
    for profile in all_profiles:
        username = (profile.get('username') or '').lower()
        name = (profile.get('name') or '').lower()
        
        if user_identifier.lower() in [username, name] or user_identifier.lower() in name:
            target_user = profile
            break
    
    if not target_user:
        return {"success": False, "error": f"Не знаю кто такой {user_identifier}"}
    
    user_id = target_user['user_id']
    fact = fact.strip()[:200]
    
    if category == "interest":
        old_topics = target_user.get('topics', '') or ''
        new_topics = f"{old_topics}; {fact}" if old_topics else fact
        await user_db.update_topics(user_id, new_topics[-500:])
    elif category == "date":
        old_dates = target_user.get('dates', '') or ''
        new_dates = f"{old_dates}; {fact}" if old_dates else fact
        await user_db.update_dates(user_id, new_dates[-500:])
    else:
        old_profile = target_user.get('profile', '') or ''
        new_profile = f"{old_profile}; {fact}" if old_profile else fact
        await user_db.update_profile(user_id, new_profile[-1000:])
    
    return {"success": True, "remembered": fact, "about": user_identifier, "category": category}


async def set_my_reminder(client, text: str, delay_minutes: int, target: str = None, reminder_db=None, current_chat_id=None, **kwargs) -> dict:
    if not reminder_db:
        return {"success": False, "error": "Напоминания недоступны"}
    
    import time
    remind_at = int(time.time()) + (delay_minutes * 60)
    
    chat_id = current_chat_id or 0
    
    if target:
        if target.startswith("group:"):
            pass
        elif target.isdigit():
            chat_id = int(target)
    
    await reminder_db.add(
        user_id=0,
        chat_id=chat_id,
        message=f"[HONO_SELF] {text}",
        send_at=remind_at
    )
    
    return {
        "success": True,
        "reminder_set": True,
        "in_minutes": delay_minutes,
        "text": text,
        "target": target or "себе"
    }


async def express_thought(client, thought: str, action: str = None, **kwargs) -> dict:
    return {
        "success": True,
        "thought_processed": True,
        "thought": thought,
        "action": action or "noted",
        "note": "Мысль зафиксирована, можешь действовать по ней"
    }


async def analyze_tone(client, message: str, context: str = None, ai_client=None, analyze_model=None, **kwargs) -> dict:
    if not ai_client or not analyze_model:
        indicators = {
            "sarcasm": ["конечно", "ну да", "как же", "ага щас", "ну-ну"],
            "irony": ["самая умная", "гений", "молодец какой", "браво"],
            "joke": ["хаха", "лол", "😂", "🤣", "ржу", "угар"],
            "angry": ["блин", "чёрт", "задолбал", "достал", "бесит"],
            "flirt": ["красотка", "милая", "малыш", "котик", "зая"]
        }
        
        message_lower = message.lower()
        detected = []
        
        for tone, words in indicators.items():
            if any(w in message_lower for w in words):
                detected.append(tone)
        
        if not detected:
            detected = ["neutral"]
        
        return {
            "success": True,
            "detected_tones": detected,
            "likely_sarcasm": "sarcasm" in detected or "irony" in detected,
            "message": message[:100]
        }
    
    prompt = f"""Проанализируй тон сообщения. Ответь ТОЛЬКО JSON:
{{"tone": "sarcasm/irony/joke/serious/angry/sad/happy/flirt/neutral", "confidence": 0.0-1.0, "meaning": "что реально имеет в виду"}}

Сообщение: {message}
{"Контекст: " + context if context else ""}"""
    
    try:
        result = await ai_client.chat(analyze_model, [
            {"role": "system", "content": "Ты анализатор тона. Отвечай только JSON."},
            {"role": "user", "content": prompt}
        ], max_tokens=150)
        
        import json
        content = result.get("content", "") if isinstance(result, dict) else str(result)
        
        try:
            data = json.loads(content)
            return {"success": True, **data}
        except:
            return {"success": True, "tone": "neutral", "raw": content[:100]}
    except:
        return {"success": False, "tone": "unknown"}


async def get_user_info(client, query: str = None, user_id: int = None, username: str = None, user_db=None, **kwargs) -> dict:
    if not user_db:
        return {"success": False, "error": "БД пользователей недоступна"}
    
    if not query and not user_id and not username:
        return {"success": False, "error": "Нужен запрос для поиска"}
    
    search = (query or username or "").strip().lstrip("@").lower()
    
    if user_id:
        profile = await user_db.get_profile(user_id)
        if profile:
            return format_user_profile(profile)
        return {"success": False, "error": f"Пользователь {user_id} не найден"}
    
    if search.isdigit():
        profile = await user_db.get_profile(int(search))
        if profile:
            return format_user_profile(profile)
    
    all_profiles = await user_db.get_all_profiles()
    if not all_profiles:
        return {"success": False, "error": "Нет сохранённых пользователей"}
    
    matches = []
    for p in all_profiles:
        score = 0
        uname = (p.get("username") or "").lower()
        name = (p.get("name") or "").lower()
        facts = (p.get("profile") or "").lower()
        topics = (p.get("topics") or "").lower()
        
        if search == uname:
            score = 100
        elif search == name:
            score = 90
        elif search in uname:
            score = 70
        elif search in name:
            score = 60
        elif search in facts:
            score = 40
        elif search in topics:
            score = 30
        
        name_parts = name.split()
        for part in name_parts:
            if search == part:
                score = max(score, 80)
            elif search in part or part in search:
                score = max(score, 50)
        
        if score > 0:
            matches.append((score, p))
    
    if not matches:
        return {"success": False, "error": f"Никого не нашёл по запросу '{query}'", "hint": "Попробуй другой запрос"}
    
    matches.sort(key=lambda x: -x[0])
    
    if len(matches) == 1 or matches[0][0] >= 70:
        return format_user_profile(matches[0][1])
    
    results = []
    for score, p in matches[:5]:
        uname = p.get("username") or "нет"
        name = p.get("name") or "?"
        uid = p.get("user_id")
        results.append(f"• @{uname} ({name}) - ID: {uid}")
    
    return {
        "success": True,
        "multiple_matches": True,
        "message": f"Найдено несколько ({len(matches)}). Уточни запрос или используй ID:",
        "results": results
    }


def format_user_profile(profile: dict) -> dict:
    from backend.database.users import RELATIONSHIP_LEVELS
    
    rel_level = profile.get("relationship", 0)
    rel_name, rel_desc = RELATIONSHIP_LEVELS.get(rel_level, RELATIONSHIP_LEVELS[0])
    
    return {
        "success": True,
        "user_id": profile.get("user_id"),
        "username": profile.get("username"),
        "name": profile.get("name"),
        "relationship": f"{rel_name} (уровень {rel_level})",
        "how_to_behave": rel_desc,
        "facts": profile.get("profile", "") or "нет данных",
        "interests": profile.get("topics", "") or "нет данных",
        "important_dates": profile.get("dates", "") or "нет",
        "mood": profile.get("mood", 0)
    }


async def get_extended_history(client, count: int = 20, group_db=None, current_chat_id=None, **kwargs) -> dict:
    if not current_chat_id:
        return {"success": False, "error": "Нет текущего чата"}
    
    count = min(max(5, count), 50)
    
    messages = []
    try:
        async for msg in client.iter_messages(current_chat_id, limit=count):
            if not msg.message:
                continue
            
            sender = await msg.get_sender()
            sender_name = "?"
            if sender:
                if sender.username:
                    sender_name = sender.username
                elif sender.first_name:
                    sender_name = f"{sender.first_name} {sender.last_name or ''}".strip()
                else:
                    sender_name = f"user_{sender.id}"
            
            messages.append({
                "from": sender_name,
                "text": msg.message[:200],
                "user_id": msg.sender_id
            })
        
        messages.reverse()
        
        formatted = []
        for m in messages:
            formatted.append(f"[{m['from']}]: {m['text']}")
        
        return {
            "success": True,
            "count": len(messages),
            "history": "\n".join(formatted)
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


async def search_skupki(client, query: str, group_db=None, current_chat_id=None, **kwargs) -> dict:
    if not group_db or not current_chat_id:
        return {"success": False, "error": "Недоступно вне группы"}
    
    try:
        from backend.humanizer.skupki import format_skupka_for_user
        
        skupki = await group_db.search_skupki(current_chat_id, query)
        
        if not skupki:
            all_skupki = await group_db.get_all_skupki(current_chat_id, limit=10)
            if all_skupki:
                results = [format_skupka_for_user(s) for s in all_skupki]
                return {
                    "success": True,
                    "found": False,
                    "message": f"По запросу '{query}' ничего не найдено",
                    "all_skupki": results
                }
            return {"success": True, "found": False, "message": "В этом чате пока нет скупок"}
        
        results = [format_skupka_for_user(s) for s in skupki]
        
        return {
            "success": True,
            "found": True,
            "count": len(results),
            "results": results
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


async def get_current_chat_info(client, group_db=None, current_chat_id=None, **kwargs) -> dict:
    if not current_chat_id:
        return {"success": False, "error": "Не в групповом чате"}
    
    if not group_db:
        return {"success": False, "error": "БД групп недоступна"}
    
    try:
        info = await group_db.get_full_group_info(current_chat_id)
        
        if not info:
            return {"success": False, "error": "Информация о чате не найдена"}
        
        result = {
            "success": True,
            "chat_id": current_chat_id,
            "title": info.get("title"),
            "username": info.get("username"),
            "message_count": info.get("message_count", 0),
            "my_messages": info.get("my_messages", 0),
            "mod_level": info.get("mod_level", 0)
        }
        
        if info.get("rules"):
            result["rules"] = info["rules"][:500]
        
        if info.get("staff"):
            result["staff"] = info["staff"][:300]
        
        if info.get("atmosphere"):
            result["atmosphere"] = info["atmosphere"]
        
        if info.get("main_topics"):
            result["main_topics"] = info["main_topics"]
        
        if info.get("communication_style"):
            result["communication_style"] = info["communication_style"]
        
        if info.get("key_members"):
            result["key_members"] = info["key_members"]
        
        if info.get("notes"):
            result["notes"] = info["notes"]
        
        return result
        
    except Exception as e:
        return {"success": False, "error": str(e)}


async def remember_about_group(client, atmosphere: str = None, topics: str = None, style: str = None,
                               members: str = None, note: str = None, group_db=None, current_chat_id=None, **kwargs) -> dict:
    if not current_chat_id:
        return {"success": False, "error": "Не в групповом чате"}
    
    if not group_db:
        return {"success": False, "error": "БД групп недоступна"}
    
    if not any([atmosphere, topics, style, members, note]):
        return {"success": False, "error": "Нужно указать хотя бы один параметр"}
    
    try:
        await group_db.update_group_profile(
            group_id=current_chat_id,
            atmosphere=atmosphere,
            main_topics=topics,
            communication_style=style,
            key_members=members,
            notes=note
        )
        
        saved = []
        if atmosphere:
            saved.append(f"атмосфера: {atmosphere[:30]}")
        if topics:
            saved.append(f"темы: {topics[:30]}")
        if style:
            saved.append(f"стиль: {style[:30]}")
        if members:
            saved.append(f"участники: {members[:30]}")
        if note:
            saved.append(f"заметка: {note[:30]}")
        
        return {
            "success": True,
            "message": f"Запомнила о чате: {', '.join(saved)}"
        }
        
    except Exception as e:
        return {"success": False, "error": str(e)}


async def send_reaction(client, emoji_id: int, message_offset: int = 0, 
                        current_chat_id=None, current_msg_id=None, group_db=None, **kwargs) -> dict:
    if not current_chat_id:
        return {"success": False, "error": "Не в чате"}
    
    try:
        target_msg_id = current_msg_id
        
        if message_offset < 0 and group_db:
            context = await group_db.get_context(current_chat_id, limit=abs(message_offset) + 5)
            if context and len(context) >= abs(message_offset):
                target_msg = context[message_offset]
                target_msg_id = target_msg.get('msg_id')
        
        if not target_msg_id:
            return {"success": False, "error": "Не найдено сообщение для реакции"}
        
        reaction = ReactionCustomEmoji(document_id=emoji_id)
        
        await client(SendReactionRequest(
            peer=current_chat_id,
            msg_id=target_msg_id,
            reaction=[reaction]
        ))
        
        return {"success": True, "message": "Реакция поставлена"}
        
    except ReactionInvalidError:
        return {"success": False, "error": "Недопустимый emoji для реакции"}
    except MessageIdInvalidError:
        return {"success": False, "error": "Сообщение не найдено"}
    except Exception as e:
        error_msg = str(e)
        if "REACTION_INVALID" in error_msg:
            return {"success": False, "error": "Этот emoji нельзя использовать как реакцию"}
        if "MSG_ID_INVALID" in error_msg:
            return {"success": False, "error": "Сообщение не найдено или удалено"}
        return {"success": False, "error": f"Ошибка: {error_msg[:100]}"}


async def delete_my_message(client, message_offset: int = -1, 
                            current_chat_id=None, **kwargs) -> dict:
    if not current_chat_id:
        return {"success": False, "error": "Не в чате"}
    
    try:
        me = await client.get_me()
        my_id = me.id
        
        my_messages = []
        async for msg in client.iter_messages(current_chat_id, limit=30, from_user=my_id):
            my_messages.append(msg)
        
        if not my_messages:
            return {"success": False, "error": "Не нашла своих сообщений"}
        
        offset = abs(message_offset) - 1
        if offset >= len(my_messages):
            return {"success": False, "error": f"У меня только {len(my_messages)} сообщений в истории"}
        
        target_msg = my_messages[offset]
        
        await client.delete_messages(current_chat_id, [target_msg.id])
        
        return {
            "success": True,
            "message": f"Удалила сообщение: {target_msg.text[:50] if target_msg.text else '[медиа]'}..."
        }
        
    except Exception as e:
        error_msg = str(e)
        if "MESSAGE_DELETE_FORBIDDEN" in error_msg:
            return {"success": False, "error": "Нет прав на удаление сообщения"}
        return {"success": False, "error": f"Ошибка: {error_msg[:100]}"}


async def get_pinned_messages(client, current_chat_id=None, group_db=None, **kwargs) -> dict:
    if not current_chat_id:
        return {"success": False, "error": "Не в чате"}
    
    cache_key = str(current_chat_id)
    now = time.time()
    
    if cache_key in pinned_cache:
        cached_time, cached_data = pinned_cache[cache_key]
        if now - cached_time < 300:
            return cached_data
    
    try:
        pinned = []
        async for msg in client.iter_messages(current_chat_id, filter='pinned', limit=10):
            sender_name = "?"
            if msg.sender:
                sender_name = msg.sender.username or msg.sender.first_name or str(msg.sender_id)
            
            pinned.append({
                "id": msg.id,
                "from": sender_name,
                "text": msg.text[:300] if msg.text else "[медиа/стикер]",
                "date": msg.date.strftime("%d.%m.%Y") if msg.date else "?"
            })
        
        if not pinned:
            result = {"success": True, "pinned": [], "message": "Нет закреплённых сообщений"}
        else:
            result = {"success": True, "count": len(pinned), "pinned": pinned}
        
        pinned_cache[cache_key] = (now, result)
        
        if group_db and pinned:
            pinned_text = "\n".join([f"• {p['text'][:100]}" for p in pinned[:3]])
            await group_db.update_group_profile(current_chat_id, notes=f"Закреплено: {pinned_text[:300]}")
        
        return result
        
    except Exception as e:
        return {"success": False, "error": f"Ошибка: {str(e)[:100]}"}


async def schedule_message(client, text: str, delay_minutes: int,
                           current_chat_id=None, reminder_db=None, **kwargs) -> dict:
    if not current_chat_id:
        return {"success": False, "error": "Не в чате"}
    
    if delay_minutes < 1:
        return {"success": False, "error": "Минимальная задержка — 1 минута"}
    
    if delay_minutes > 1440:
        return {"success": False, "error": "Максимальная задержка — 24 часа (1440 минут)"}
    
    if not text or len(text.strip()) < 1:
        return {"success": False, "error": "Пустое сообщение"}
    
    try:
        if reminder_db:
            from backend.humanizer.reminders import get_msk_now
            send_time = int(time.time()) + (delay_minutes * 60)
            
            await reminder_db.add(
                user_id=current_chat_id,
                topic=text[:200],
                send_at=send_time
            )
            
            hours = delay_minutes // 60
            mins = delay_minutes % 60
            time_str = f"{hours}ч {mins}м" if hours > 0 else f"{mins}м"
            
            return {
                "success": True,
                "message": f"Сообщение запланировано через {time_str}",
                "scheduled_text": text[:50] + "..." if len(text) > 50 else text
            }
        
        return {"success": False, "error": "Система напоминаний недоступна"}
        
    except Exception as e:
        return {"success": False, "error": f"Ошибка: {str(e)[:100]}"}


async def forward_message(client, to_chat: str, message_offset: int = 0,
                          current_chat_id=None, current_msg_id=None, owner_id=None, **kwargs) -> dict:
    if not current_chat_id:
        return {"success": False, "error": "Не в чате"}
    
    try:
        if to_chat.lower() == "owner":
            if not owner_id:
                return {"success": False, "error": "Владелец не определён"}
            target_chat = owner_id
        elif to_chat.startswith("@"):
            target_chat = to_chat
        elif to_chat.lstrip("-").isdigit():
            target_chat = int(to_chat)
        else:
            return {"success": False, "error": "Укажи @username или chat_id"}
        
        source_msg_id = current_msg_id
        
        if message_offset < 0:
            messages = []
            async for msg in client.iter_messages(current_chat_id, limit=abs(message_offset) + 1):
                messages.append(msg)
            
            if len(messages) > abs(message_offset):
                source_msg_id = messages[abs(message_offset)].id
        
        if not source_msg_id:
            return {"success": False, "error": "Сообщение для пересылки не найдено"}
        
        await client.forward_messages(target_chat, source_msg_id, current_chat_id)
        
        return {"success": True, "message": f"Сообщение переслано в {to_chat}"}
        
    except UserPrivacyRestrictedError:
        return {"success": False, "error": "Пользователь ограничил пересылку"}
    except ChannelPrivateError:
        return {"success": False, "error": "Нет доступа к целевому чату"}
    except Exception as e:
        return {"success": False, "error": f"Ошибка: {str(e)[:100]}"}


async def reply_to_message(client, text: str, message_offset: int = None, search_text: str = None,
                           current_chat_id=None, group_db=None, send_func=None, **kwargs) -> dict:
    if not current_chat_id:
        return {"success": False, "error": "Не в чате"}
    
    if not text:
        return {"success": False, "error": "Пустой текст ответа"}
    
    try:
        target_msg_id = None
        target_preview = None
        
        if search_text:
            search_lower = search_text.lower()
            async for msg in client.iter_messages(current_chat_id, limit=50):
                if msg.text and search_lower in msg.text.lower():
                    target_msg_id = msg.id
                    target_preview = msg.text[:50]
                    break
            
            if not target_msg_id:
                return {"success": False, "error": f"Не нашла сообщение с текстом '{search_text[:30]}'"}
        
        elif message_offset is not None and message_offset < 0:
            messages = []
            async for msg in client.iter_messages(current_chat_id, limit=abs(message_offset) + 1):
                messages.append(msg)
            
            if len(messages) >= abs(message_offset):
                target_msg = messages[abs(message_offset) - 1]
                target_msg_id = target_msg.id
                target_preview = target_msg.text[:50] if target_msg.text else "[медиа]"
        
        if not target_msg_id:
            return {"success": False, "error": "Укажи message_offset (-1, -2...) или search_text"}
        
        if send_func:
            await send_func(current_chat_id, text, reply_to=target_msg_id)
        else:
            await client.send_message(current_chat_id, text, reply_to=target_msg_id)
        
        return {
            "success": True,
            "message": f"Ответила на: {target_preview}..."
        }
        
    except MessageIdInvalidError:
        return {"success": False, "error": "Сообщение не найдено или удалено"}
    except Exception as e:
        return {"success": False, "error": f"Ошибка: {str(e)[:100]}"}


async def send_dm(client, user: str, text: str, user_db=None, **kwargs) -> dict:
    if not text or len(text.strip()) < 1:
        return {"success": False, "error": "Пустое сообщение"}
    
    try:
        if user.startswith("@"):
            target_user = await client.get_entity(user)
        elif user.lstrip("-").isdigit():
            target_user = await client.get_entity(int(user))
        else:
            return {"success": False, "error": "Укажи @username или user_id"}
        
        user_id = target_user.id
        
        can_write = user_id in known_dm_users
        
        if not can_write and user_db:
            profile = await user_db.get_profile(user_id)
            if profile and profile.get('last_seen'):
                can_write = True
                known_dm_users.add(user_id)
        
        if not can_write:
            try:
                messages = await client.get_messages(user_id, limit=1)
                if messages:
                    can_write = True
                    known_dm_users.add(user_id)
            except:
                pass
        
        if not can_write:
            return {
                "success": False,
                "error": "Этот пользователь мне раньше не писал. Не могу написать первой — будет спам-бан!",
                "suggestion": "Попроси его написать мне первым или добавить в контакты"
            }
        
        await client.send_message(user_id, text)
        
        return {
            "success": True,
            "message": f"Написала в ЛС @{target_user.username or user_id}"
        }
        
    except UserPrivacyRestrictedError:
        return {
            "success": False,
            "error": "У пользователя закрыты ЛС",
            "suggestion": "Попроси его добавить меня в контакты или включить сообщения"
        }
    except UserIsBlockedError:
        return {"success": False, "error": "Пользователь меня заблокировал"}
    except PeerFloodError:
        return {"success": False, "error": "Telegram ограничил отправку сообщений. Подожди немного"}
    except InputUserDeactivatedError:
        return {"success": False, "error": "Аккаунт пользователя удалён"}
    except Exception as e:
        error_msg = str(e)
        if "USER_ID_INVALID" in error_msg:
            return {"success": False, "error": "Пользователь не найден"}
        if "PEER_ID_INVALID" in error_msg:
            return {"success": False, "error": "Неверный ID пользователя"}
        return {"success": False, "error": f"Ошибка: {error_msg[:100]}"}


async def add_contact(client, user: str, first_name: str = None, **kwargs) -> dict:
    try:
        if user.startswith("@"):
            target_user = await client.get_entity(user)
        elif user.lstrip("-").isdigit():
            target_user = await client.get_entity(int(user))
        else:
            return {"success": False, "error": "Укажи @username или user_id"}
        
        user_id = target_user.id
        
        if not first_name:
            first_name = target_user.first_name or target_user.username or "Contact"
        
        phone = target_user.phone or ""
        
        await client(AddContactRequest(
            id=target_user,
            first_name=first_name,
            last_name=target_user.last_name or "",
            phone=phone,
            add_phone_privacy_exception=True
        ))
        
        known_dm_users.add(user_id)
        
        return {
            "success": True,
            "message": f"Добавила @{target_user.username or user_id} в контакты как '{first_name}'",
            "note": "Теперь мы можем переписываться даже если у кого-то спам-бан"
        }
        
    except Exception as e:
        error_msg = str(e)
        if "CONTACT_ID_INVALID" in error_msg:
            return {"success": False, "error": "Не могу добавить этого пользователя"}
        return {"success": False, "error": f"Ошибка: {error_msg[:100]}"}


async def check_can_dm(client, user: str, user_db=None, **kwargs) -> dict:
    try:
        if user.startswith("@"):
            target_user = await client.get_entity(user)
        elif user.lstrip("-").isdigit():
            target_user = await client.get_entity(int(user))
        else:
            return {"success": False, "error": "Укажи @username или user_id"}
        
        user_id = target_user.id
        username = target_user.username or "нет"
        
        result = {
            "success": True,
            "user_id": user_id,
            "username": username,
            "first_name": target_user.first_name or "?",
            "can_dm": False,
            "reason": None,
            "has_paid_messages": False,
            "wrote_before": False,
            "is_contact": False
        }
        
        if user_id in known_dm_users:
            result["can_dm"] = True
            result["wrote_before"] = True
            result["reason"] = "Писал мне раньше"
            return result
        
        if user_db:
            profile = await user_db.get_profile(user_id)
            if profile and profile.get('last_seen'):
                result["can_dm"] = True
                result["wrote_before"] = True
                result["reason"] = "Есть в моей базе"
                known_dm_users.add(user_id)
                return result
        
        try:
            full = await client(GetFullUserRequest(target_user))
            
            if hasattr(full, 'full_user'):
                full_user = full.full_user
                
                if hasattr(full_user, 'contact') and full_user.contact:
                    result["is_contact"] = True
                    result["can_dm"] = True
                    result["reason"] = "В контактах"
                    return result
                
                if hasattr(full_user, 'business_intro') and full_user.business_intro:
                    result["has_paid_messages"] = True
                    result["reason"] = "Включены платные сообщения"
                    return result
                    
        except Exception:
            pass
        
        try:
            messages = await client.get_messages(user_id, limit=1)
            if messages:
                result["can_dm"] = True
                result["wrote_before"] = True
                result["reason"] = "Есть история переписки"
                known_dm_users.add(user_id)
                return result
        except:
            pass
        
        result["reason"] = "Никогда не писал мне. Могу получить спам-бан если напишу первой"
        result["suggestion"] = "Попроси его написать мне первым или добавить меня в контакты"
        
        return result
        
    except UsernameNotOccupiedError:
        return {"success": False, "error": "Пользователь не найден"}
    except Exception as e:
        return {"success": False, "error": f"Ошибка: {str(e)[:100]}"}


messages_with_buttons = {}


async def click_button(client, button: str, message_offset: int = 0, current_chat_id: int = None, current_msg_id: int = None, **kwargs) -> dict:
    if not current_chat_id:
        return {"success": False, "error": "Не определён текущий чат"}
    
    try:
        target_msg_id = None
        if current_msg_id and message_offset == 0:
            target_msg_id = current_msg_id
        
        if not target_msg_id:
            messages = await client.get_messages(current_chat_id, limit=message_offset + 5)
            if not messages or len(messages) <= message_offset:
                return {"success": False, "error": "Сообщение не найдено"}
            
            msg = messages[message_offset]
            target_msg_id = msg.id
        else:
            msg = await client.get_messages(current_chat_id, ids=target_msg_id)
        
        if not msg:
            return {"success": False, "error": "Сообщение не найдено"}
        
        reply_markup = msg.reply_markup
        if not reply_markup:
            return {"success": False, "error": "У сообщения нет кнопок"}
        
        rows = getattr(reply_markup, 'rows', None)
        if not rows:
            return {"success": False, "error": "У сообщения нет кнопок"}
        
        all_buttons = []
        for row in rows:
            for btn in row.buttons:
                all_buttons.append(btn)
        
        if not all_buttons:
            return {"success": False, "error": "Кнопки не найдены"}
        
        target_button = None
        
        if button.isdigit():
            idx = int(button) - 1
            if 0 <= idx < len(all_buttons):
                target_button = all_buttons[idx]
            else:
                return {"success": False, "error": f"Кнопка #{button} не найдена. Всего кнопок: {len(all_buttons)}"}
        else:
            button_lower = button.lower().strip()
            for btn in all_buttons:
                btn_text = getattr(btn, 'text', '').lower()
                if button_lower in btn_text or btn_text in button_lower:
                    target_button = btn
                    break
            
            if not target_button:
                available = ", ".join([f"'{getattr(b, 'text', '?')}'" for b in all_buttons[:5]])
                return {"success": False, "error": f"Кнопка '{button}' не найдена. Доступные: {available}"}
        
        btn_url = getattr(target_button, 'url', None)
        if btn_url:
            return {
                "success": True,
                "action": "url",
                "url": btn_url,
                "text": getattr(target_button, 'text', ''),
                "message": "Это ссылка. Можешь поделиться ей с пользователем."
            }
        
        await msg.click(data=target_button.data)
        
        await asyncio.sleep(0.5)
        
        return {
            "success": True,
            "action": "clicked",
            "text": getattr(target_button, 'text', ''),
            "message": f"Нажала на кнопку '{getattr(target_button, 'text', '')}'"
        }
        
    except Exception as e:
        return {"success": False, "error": f"Ошибка: {str(e)[:100]}"}


async def resolve_user(client, query: str, current_chat_id: int = None, group_db=None, **kwargs) -> dict:
    query = query.strip()
    
    if query.lstrip("-").isdigit():
        try:
            user = await client.get_entity(int(query))
            return {
                "success": True,
                "user_id": user.id,
                "username": user.username,
                "first_name": user.first_name,
                "last_name": user.last_name or "",
                "is_bot": getattr(user, 'bot', False),
                "is_premium": getattr(user, 'premium', False)
            }
        except:
            return {"success": False, "error": "Пользователь с таким ID не найден"}
    
    if query.startswith("@"):
        try:
            user = await client.get_entity(query)
            return {
                "success": True,
                "user_id": user.id,
                "username": user.username,
                "first_name": user.first_name,
                "last_name": user.last_name or "",
                "is_bot": getattr(user, 'bot', False),
                "is_premium": getattr(user, 'premium', False)
            }
        except UsernameNotOccupiedError:
            return {"success": False, "error": f"Username {query} не существует"}
        except:
            pass
    
    query_lower = query.lower().replace("@", "")
    
    if current_chat_id and group_db:
        try:
            context = await group_db.get_context(current_chat_id, limit=100)
            for msg in context:
                username = msg.get('username', '')
                if username and query_lower in username.lower():
                    uid = msg.get('user_id')
                    if uid:
                        try:
                            user = await client.get_entity(uid)
                            return {
                                "success": True,
                                "user_id": user.id,
                                "username": user.username,
                                "first_name": user.first_name,
                                "last_name": user.last_name or "",
                                "found_by": "context_search"
                            }
                        except:
                            pass
        except:
            pass
    
    if current_chat_id:
        try:
            async for user in client.iter_participants(current_chat_id, search=query, limit=5):
                if query_lower in (user.first_name or "").lower() or \
                   query_lower in (user.last_name or "").lower() or \
                   (user.username and query_lower in user.username.lower()):
                    return {
                        "success": True,
                        "user_id": user.id,
                        "username": user.username,
                        "first_name": user.first_name,
                        "last_name": user.last_name or "",
                        "found_by": "participant_search"
                    }
        except:
            pass
    
    try:
        user = await client.get_entity(f"@{query_lower}")
        return {
            "success": True,
            "user_id": user.id,
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name or ""
        }
    except:
        pass
    
    return {"success": False, "error": f"Не удалось найти пользователя '{query}'. Попробуй @username или ID."}


async def get_common_chats(client, user: str, **kwargs) -> dict:
    try:
        if user.startswith("@"):
            target = await client.get_entity(user)
        elif user.lstrip("-").isdigit():
            target = await client.get_entity(int(user))
        else:
            return {"success": False, "error": "Укажи @username или user_id"}
        
        result = await client(GetCommonChatsRequest(user_id=target, max_id=0, limit=100))
        
        chats = []
        for chat in result.chats:
            chat_info = {
                "id": chat.id,
                "title": getattr(chat, 'title', 'Unknown'),
                "type": "channel" if isinstance(chat, Channel) else "group"
            }
            if hasattr(chat, 'username') and chat.username:
                chat_info["username"] = f"@{chat.username}"
            chats.append(chat_info)
        
        return {
            "success": True,
            "user_id": target.id,
            "username": target.username,
            "common_chats_count": len(chats),
            "chats": chats[:20]
        }
        
    except UsernameNotOccupiedError:
        return {"success": False, "error": "Пользователь не найден"}
    except Exception as e:
        return {"success": False, "error": f"Ошибка: {str(e)[:100]}"}


async def get_profile_gifts(client, user: str = None, **kwargs) -> dict:
    if not HAS_STAR_GIFTS:
        return {"success": False, "error": "Функция получения подарков недоступна в этой версии"}
    
    try:
        if user:
            if user.startswith("@"):
                target = await client.get_entity(user)
            elif user.lstrip("-").isdigit():
                target = await client.get_entity(int(user))
            else:
                return {"success": False, "error": "Укажи @username или user_id"}
        else:
            target = await client.get_me()
        
        try:
            result = await client(GetSavedStarGiftsRequest(peer=target, offset="", limit=50))
            
            gifts = []
            total_stars = 0
            
            for gift in result.gifts:
                g = getattr(gift, 'gift', None)
                stars = getattr(g, 'stars', 0) if g else 0
                if stars:
                    total_stars += stars
                
                from_id = None
                if hasattr(gift, 'from_id') and gift.from_id:
                    from_id = gift.from_id.user_id if hasattr(gift.from_id, 'user_id') else None
                
                msg = ""
                if hasattr(gift, 'message') and gift.message:
                    msg = gift.message.text[:50] if hasattr(gift.message, 'text') else ""
                
                limited = getattr(g, 'limited', False) if g else False
                
                gift_str = f"⭐{stars}" if stars else "NFT"
                if limited:
                    gift_str += "🔥"
                if msg:
                    gift_str += f" «{msg}»"
                if from_id:
                    gift_str += f" (от {from_id})"
                
                gifts.append(gift_str)
            
            return {
                "success": True,
                "user": f"@{target.username}" if target.username else target.id,
                "total": getattr(result, 'count', len(gifts)),
                "total_stars": total_stars,
                "gifts": gifts[:20]
            }
            
        except Exception as e:
            if "USER_GIFTS_HIDDEN" in str(e) or "privacy" in str(e).lower():
                return {"success": False, "error": "Подарки пользователя скрыты настройками приватности"}
            
            return {
                "success": True,
                "user_id": target.id,
                "username": target.username,
                "gifts_count": 0,
                "gifts": [],
                "note": "Подарки недоступны или их нет"
            }
        
    except UsernameNotOccupiedError:
        return {"success": False, "error": "Пользователь не найден"}
    except Exception as e:
        return {"success": False, "error": f"Ошибка: {str(e)[:100]}"}


async def get_full_profile(client, user: str, **kwargs) -> dict:
    try:
        if user.startswith("@"):
            target = await client.get_entity(user)
        elif user.lstrip("-").isdigit():
            target = await client.get_entity(int(user))
        else:
            return {"success": False, "error": "Укажи @username или user_id"}
        
        full = await client(GetFullUserRequest(target))
        full_user = full.full_user
        user_obj = full.users[0] if full.users else target
        
        profile = {
            "success": True,
            "user_id": target.id,
            "username": target.username,
            "first_name": target.first_name,
            "last_name": target.last_name or "",
            "phone": target.phone if hasattr(target, 'phone') and target.phone else None,
            "is_bot": getattr(target, 'bot', False),
            "is_premium": getattr(target, 'premium', False),
            "is_verified": getattr(target, 'verified', False),
            "is_restricted": getattr(target, 'restricted', False)
        }
        
        if hasattr(full_user, 'about') and full_user.about:
            profile["bio"] = full_user.about
        
        if hasattr(full_user, 'common_chats_count'):
            profile["common_chats_count"] = full_user.common_chats_count
        
        if hasattr(full_user, 'profile_photo') and full_user.profile_photo:
            profile["has_photo"] = True
        else:
            profile["has_photo"] = False
        
        if hasattr(full_user, 'bot_info') and full_user.bot_info:
            profile["bot_description"] = full_user.bot_info.description if hasattr(full_user.bot_info, 'description') else None
        
        from backend.humanizer.context_utils import get_online_status_from_user
        online = get_online_status_from_user(user_obj)
        if online:
            profile["online_status"] = online
        
        return profile
        
    except UsernameNotOccupiedError:
        return {"success": False, "error": "Пользователь не найден"}
    except Exception as e:
        return {"success": False, "error": f"Ошибка: {str(e)[:100]}"}


TOOL_FUNCTIONS = {
    "join_group": join_group,
    "get_group_info": get_group_info,
    "get_group_rules": get_group_rules,
    "get_group_staff": get_group_staff,
    "fetch_group_rules": fetch_group_rules,
    "fetch_group_staff": fetch_group_staff,
    "unmute_user": unmute_user,
    "search_knowledge": search_knowledge,
    "get_user_memory": get_user_memory,
    "search_chat_history": search_chat_history,
    "get_chat_context": get_chat_context,
    "remember_this": remember_this,
    "set_my_reminder": set_my_reminder,
    "express_thought": express_thought,
    "analyze_tone": analyze_tone,
    "get_user_info": get_user_info,
    "get_extended_history": get_extended_history,
    "search_skupki": search_skupki,
    "get_current_chat_info": get_current_chat_info,
    "remember_about_group": remember_about_group,
    "send_reaction": send_reaction,
    "delete_my_message": delete_my_message,
    "get_pinned_messages": get_pinned_messages,
    "schedule_message": schedule_message,
    "forward_message": forward_message,
    "reply_to_message": reply_to_message,
    "send_dm": send_dm,
    "add_contact": add_contact,
    "check_can_dm": check_can_dm,
    "click_button": click_button,
    "resolve_user": resolve_user,
    "get_common_chats": get_common_chats,
    "get_profile_gifts": get_profile_gifts,
    "get_full_profile": get_full_profile
}


async def execute_tool(client, tool_name: str, arguments: dict, send_func=None, group_db=None, user_db=None, reminder_db=None, ai_client=None, analyze_model=None, current_chat_id=None, sender_role=None, current_msg_id=None, owner_id=None) -> dict:
    if tool_name not in TOOL_FUNCTIONS:
        return {"success": False, "error": f"Неизвестный инструмент: {tool_name}"}
    
    func = TOOL_FUNCTIONS[tool_name]
    
    if tool_name == "send_message_to_group":
        if send_func:
            arguments["send_func"] = send_func
        if group_db:
            arguments["group_db"] = group_db
    
    if tool_name in ["join_group", "leave_group"] and group_db:
        arguments["group_db"] = group_db
    
    if tool_name in ["get_group_rules", "get_group_staff", "search_chat_history", "get_chat_context"] and group_db:
        arguments["group_db"] = group_db
    
    if tool_name in ["fetch_group_rules", "fetch_group_staff"]:
        if group_db:
            arguments["group_db"] = group_db
        if current_chat_id:
            if "current" in arguments.get("group_link", "").lower():
                arguments["group_link"] = str(current_chat_id)
                recent_groups["last"] = type('obj', (object,), {'id': current_chat_id})()
    
    if tool_name == "unmute_user":
        if group_db:
            arguments["group_db"] = group_db
        arguments["sender_role"] = sender_role
        if current_chat_id:
            if "current" in arguments.get("group_link", "").lower() or not arguments.get("group_link"):
                arguments["group_link"] = str(current_chat_id)
                recent_groups["last"] = type('obj', (object,), {'id': current_chat_id})()
    
    if tool_name in ["get_user_memory", "remember_this"] and user_db:
        arguments["user_db"] = user_db
    
    if tool_name == "set_my_reminder":
        if reminder_db:
            arguments["reminder_db"] = reminder_db
        if current_chat_id:
            arguments["current_chat_id"] = current_chat_id
    
    if tool_name == "analyze_tone":
        arguments["ai_client"] = ai_client
        arguments["analyze_model"] = analyze_model
    
    if tool_name == "search_knowledge":
        arguments["ai_client"] = ai_client
        arguments["analyze_model"] = analyze_model
    
    if tool_name == "search_skupki":
        if group_db:
            arguments["group_db"] = group_db
        if current_chat_id:
            arguments["current_chat_id"] = current_chat_id
    
    if tool_name == "get_user_info":
        if user_db:
            arguments["user_db"] = user_db
    
    if tool_name == "get_extended_history":
        if group_db:
            arguments["group_db"] = group_db
        if current_chat_id:
            arguments["current_chat_id"] = current_chat_id
    
    if tool_name in ["get_current_chat_info", "remember_about_group"]:
        if group_db:
            arguments["group_db"] = group_db
        if current_chat_id:
            arguments["current_chat_id"] = current_chat_id
    
    if tool_name == "send_reaction":
        if current_chat_id:
            arguments["current_chat_id"] = current_chat_id
        if current_msg_id:
            arguments["current_msg_id"] = current_msg_id
        if group_db:
            arguments["group_db"] = group_db
    
    if tool_name == "delete_my_message":
        if current_chat_id:
            arguments["current_chat_id"] = current_chat_id
    
    if tool_name == "get_pinned_messages":
        if current_chat_id:
            arguments["current_chat_id"] = current_chat_id
        if group_db:
            arguments["group_db"] = group_db
    
    if tool_name == "schedule_message":
        if current_chat_id:
            arguments["current_chat_id"] = current_chat_id
        if reminder_db:
            arguments["reminder_db"] = reminder_db
    
    if tool_name == "forward_message":
        if current_chat_id:
            arguments["current_chat_id"] = current_chat_id
        if current_msg_id:
            arguments["current_msg_id"] = current_msg_id
        if owner_id:
            arguments["owner_id"] = owner_id
    
    if tool_name == "reply_to_message":
        if current_chat_id:
            arguments["current_chat_id"] = current_chat_id
        if group_db:
            arguments["group_db"] = group_db
        if send_func:
            arguments["send_func"] = send_func
    
    if tool_name in ["send_dm", "check_can_dm"]:
        if user_db:
            arguments["user_db"] = user_db
    
    if tool_name == "click_button":
        if current_chat_id:
            arguments["current_chat_id"] = current_chat_id
        if current_msg_id:
            arguments["current_msg_id"] = current_msg_id
    
    if tool_name == "resolve_user":
        if current_chat_id:
            arguments["current_chat_id"] = current_chat_id
        if group_db:
            arguments["group_db"] = group_db
    
    return await func(client, **arguments)

