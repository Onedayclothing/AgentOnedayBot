import asyncio
import json
import os
import random
from datetime import datetime, timedelta, timezone

from pyrogram import Client, enums, filters
from pyrogram.errors import (
    FloodWait,
    PeerFlood,
    UserAlreadyParticipant,
    UserNotMutualContact,
    UserPrivacyRestricted,
    UserRestricted,
    UsernameInvalid,
    UsernameNotOccupied,
    ChatWriteForbidden,
    UserBannedInChannel,
    ChatAdminRequired,
    ChannelPrivate,
    ChannelInvalid,
    PeerIdInvalid,
    MessageIdInvalid,
)
from pyrogram.types import ChatJoinRequest, ChatMemberUpdated, Message

# ------------------------------------------------------------------------------
# ENVIRONMENT VARIABLES & CONFIG
# ------------------------------------------------------------------------------
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
ALERT_CHAT_ID = os.environ.get("ALERT_CHAT_ID", "").strip()

def parse_chats(chat_str):
    if not chat_str or chat_str.strip().lower() in ("no", "off", "false", "0"):
        return []
    chats = []
    for c in chat_str.split(","):
        c = c.strip()
        if not c or c.lower() in ("no", "off", "false", "0"):
            continue
        if c.startswith("-") or c.isdigit():
            try:
                chats.append(int(c))
                continue
            except ValueError:
                pass
        if not c.startswith("@"):
            c = "@" + c
        chats.append(c)
    return chats

accounts_config = []

# Session 1 (Primary)
s1 = (os.environ.get("SESSION_STRING") or os.environ.get("SESSION_STRING_1", "")).strip()
t1 = (os.environ.get("TARGET_CHAT_1") or os.environ.get("TARGET_CHAT", "")).strip()

if s1:
    accounts_config.append({
        "index": 1,
        "session": s1,
        "targets": parse_chats(t1)
    })

# Session 2 រហូតដល់ 9
for i in range(2, 10):
    s_str = os.environ.get(f"SESSION_STRING_{i}", "").strip()
    t_chat = os.environ.get(f"TARGET_CHAT_{i}", "").strip()
    
    if s_str:
        accounts_config.append({
            "index": i,
            "session": s_str,
            "targets": parse_chats(t_chat)
        })

SOURCE_CHAT = os.environ.get("SOURCE_CHAT", "")
SLEEP_TIME = int(os.environ.get("SLEEP_TIME", 9000))

RECORD_JOIN = os.environ.get("Record_Join", "")
CHAT_TO_USER = os.environ.get("Chat_ToUser", "No").strip()

WELCOME_ENABLED = CHAT_TO_USER.lower() not in ("no", "off", "false", "0", "")

ACCEPT_REQUEST = os.environ.get("Accept_Request", "")
ACCEPT_TF = os.environ.get("Accept_TF", "False").strip().lower() in ("true", "1", "yes", "on")

ADD_TO_GROUP = os.environ.get("Add_To_Group", "")

ADD_ACCOUNTS_STR = os.environ.get("ADD_ACCOUNTS", "").strip()
allowed_add_accounts = []
if ADD_ACCOUNTS_STR:
    for x in ADD_ACCOUNTS_STR.split(","):
        x = x.strip()
        if x.isdigit():
            allowed_add_accounts.append(int(x))

CUSTOM_LIMITS_STR = os.environ.get("CUSTOM_LIMITS", "").strip()
account_custom_limits = {}
if CUSTOM_LIMITS_STR:
    for item in CUSTOM_LIMITS_STR.split(","):
        if ":" in item:
            try:
                k, v = item.split(":")
                account_custom_limits[int(k.strip())] = int(v.strip())
            except ValueError:
                pass

WELCOME_MESSAGES_LIST = [msg.strip() for msg in CHAT_TO_USER.split(",") if msg.strip()]

MAX_RETRIES = 3
ICT = timezone(timedelta(hours=7))

blocked_accounts = {}
welcomed_users = set()

# ------------------------------------------------------------------------------
# FILES & STORAGE (Mounted to Railway Volume /data)
# ------------------------------------------------------------------------------
DATA_DIR = "/data"
if not os.path.exists(DATA_DIR):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
    except Exception:
        DATA_DIR = "."

QUEUE_FILE = os.path.join(DATA_DIR, "welcome_queue.json")
ADD_QUEUE_FILE = os.path.join(DATA_DIR, "add_member_queue.json")
ADD_DAILY_STATE_FILE = os.path.join(DATA_DIR, "add_daily_state.json")
BROADCASTER_STATE_FILE = os.path.join(DATA_DIR, "broadcaster_state.json")
SOURCE_MESSAGES_FILE = os.path.join(DATA_DIR, "source_messages.json")

file_lock = asyncio.Lock()

def safe_load_json(filename, default_val):
    if os.path.exists(filename):
        try:
            with open(filename, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            try:
                os.replace(filename, filename + ".bak")
            except Exception:
                pass
            return default_val
    return default_val

def safe_save_json(filename, data):
    tmp_file = filename + ".tmp"
    try:
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        os.replace(tmp_file, filename)
    except Exception:
        if os.path.exists(tmp_file):
            try:
                os.remove(tmp_file)
            except Exception:
                pass

def is_chat_matched(chat_obj, target_list):
    if not target_list:
        return False
    chat_id_str = str(chat_obj.id)
    chat_username = str(chat_obj.username).lower() if chat_obj.username else ""

    for t in target_list:
        t_str = str(t)
        if t_str == chat_id_str:
            return True
        if t_str.replace("-100", "") == chat_id_str.replace("-100", ""):
            return True
        if chat_username and t_str.replace("@", "").lower() == chat_username:
            return True
    return False

target_welcome_groups = parse_chats(RECORD_JOIN)
accept_request_groups = parse_chats(ACCEPT_REQUEST)
add_to_groups = parse_chats(ADD_TO_GROUP)

parsed_sources = parse_chats(SOURCE_CHAT)
source_chat_parsed = parsed_sources[0] if parsed_sources else None

# ------------------------------------------------------------------------------
# INITIALIZE CLIENTS & BOT
# ------------------------------------------------------------------------------
clients = []
clients_configs = []

for idx, acc_info in enumerate(accounts_config, start=1):
    is_primary = (acc_info['index'] == 1)
    cli = Client(
        f"telegram_client_{acc_info['index']}",
        api_id=API_ID,
        api_hash=API_HASH,
        session_string=acc_info["session"],
        no_updates=not is_primary
    )
    clients.append(cli)
    clients_configs.append(acc_info)

primary_client = clients[0] if clients else None

bot_client = None
if BOT_TOKEN:
    bot_client = Client(
        "notification_bot_session",
        api_id=API_ID,
        api_hash=API_HASH,
        bot_token=BOT_TOKEN
    )

async def send_admin_alert(text: str):
    if not bot_client or not ALERT_CHAT_ID:
        return
    try:
        chat_target = int(ALERT_CHAT_ID) if ALERT_CHAT_ID.startswith("-") or ALERT_CHAT_ID.isdigit() else ALERT_CHAT_ID
        await bot_client.send_message(chat_target, text)
    except Exception as e:
        print(f"⚠️ Bot មិនអាចផ្ញើ Alert ទៅកាន់ Group បានទេ: {e}")


# ------------------------------------------------------------------------------
# EVENT HANDLERS (PRIMARY CLIENT)
# ------------------------------------------------------------------------------
if primary_client:

    @primary_client.on_message(filters.private & ~filters.me & filters.reply)
    async def auto_delete_on_reply(client: Client, message: Message):
        try:
            await message.delete()
            if message.reply_to_message:
                await message.reply_to_message.delete()
        except Exception:
            pass

    @primary_client.on_chat_join_request()
    async def auto_accept_join_requests_handler(
        client: Client, chat_join_request: ChatJoinRequest
    ):
        if not ACCEPT_TF:
            return
        chat = chat_join_request.chat
        user = chat_join_request.from_user

        if not is_chat_matched(chat, accept_request_groups):
            return

        try:
            await client.approve_chat_join_request(chat_id=chat.id, user_id=user.id)
            await asyncio.sleep(random.uniform(3, 5))
        except Exception as ex:
            await send_admin_alert(f"🚨 **Error in Auto Accept Request:**\n`{ex}`")

    @primary_client.on_message()
    async def real_time_join_listener(client: Client, message: Message):
        try:
            chat = message.chat
            if not chat or not is_chat_matched(chat, target_welcome_groups):
                return
            
            users_to_add = []
            if message.new_chat_members:
                for u in message.new_chat_members:
                    users_to_add.append(u)
            if message.from_user:
                users_to_add.append(message.from_user)

            for user in users_to_add:
                if user.is_self or user.is_bot or user.is_deleted:
                    continue
                
                async with file_lock:
                    if target_welcome_groups:
                        add_queue = safe_load_json(ADD_QUEUE_FILE, [])
                        if not any(u["id"] == user.id for u in add_queue):
                            add_queue.append(
                                {
                                    "id": user.id,
                                    "username": user.username,
                                    "first_name": user.first_name or "",
                                    "source_group": str(chat.title or chat.id)
                                }
                            )
                            safe_save_json(ADD_QUEUE_FILE, add_queue)
        except Exception as ex:
            pass

    @primary_client.on_chat_member_updated()
    async def chat_member_update_tracker(client: Client, cms: ChatMemberUpdated):
        if cms.new_chat_member and cms.new_chat_member.status == enums.ChatMemberStatus.MEMBER:
            if cms.old_chat_member is None or cms.old_chat_member.status in (
                enums.ChatMemberStatus.LEFT,
                enums.ChatMemberStatus.BANNED,
                enums.ChatMemberStatus.RESTRICTED,
            ):
                chat = cms.chat
                user = cms.new_chat_member.user

                if user.is_self or user.is_bot:
                    return

                if not is_chat_matched(chat, target_welcome_groups):
                    return

                if user.id not in welcomed_users:
                    welcomed_users.add(user.id)

                    async with file_lock:
                        if WELCOME_ENABLED:
                            current_queue = safe_load_json(QUEUE_FILE, [])
                            current_queue.append(
                                {
                                    "id": user.id,
                                    "username": user.username,
                                    "first_name": user.first_name or "",
                                    "group_title": chat.title or "",
                                }
                            )
                            safe_save_json(QUEUE_FILE, current_queue)

                        if target_welcome_groups:
                            add_queue = safe_load_json(ADD_QUEUE_FILE, [])
                            if not any(u["id"] == user.id for u in add_queue):
                                add_queue.append(
                                    {
                                        "id": user.id,
                                        "username": user.username,
                                        "first_name": user.first_name or "",
                                        "source_group": str(chat.title or chat.id)
                                    }
                                )
                                safe_save_json(ADD_QUEUE_FILE, add_queue)


# ------------------------------------------------------------------------------
# WORKER FUNCTIONS
# ------------------------------------------------------------------------------

async def source_chat_poller_worker(client: Client):
    await asyncio.sleep(5)
    while True:
        if source_chat_parsed:
            try:
                fetched_msgs = []
                async for message in client.get_chat_history(source_chat_parsed, limit=30):
                    if not message.service and (message.text or message.caption or message.media):
                        fetched_msgs.append({
                            "id": message.id,
                            "chat_id": message.chat.id,
                            "text": message.text or message.caption or "Media/Post",
                        })
                fetched_msgs.reverse()

                async with file_lock:
                    msgs = safe_load_json(SOURCE_MESSAGES_FILE, [])
                    existing_ids = {m["id"] for m in msgs}
                    new_added = False
                    for m in fetched_msgs:
                        if m["id"] not in existing_ids:
                            msgs.append(m)
                            new_added = True
                    if new_added:
                        safe_save_json(SOURCE_MESSAGES_FILE, msgs)
            except Exception as ex:
                await send_admin_alert(f"🚨 **Error in Source Poller:**\n`{ex}`")
        await asyncio.sleep(5)


async def scrape_members_worker(client: Client):
    await asyncio.sleep(15)
    while True:
        try:
            if not target_welcome_groups:
                await asyncio.sleep(30)
                continue

            for g in target_welcome_groups:
                try:
                    async for message in client.get_chat_history(g, limit=300):
                        users_to_add_list = []
                        if message.from_user:
                            users_to_add_list.append(message.from_user)
                        if message.new_chat_members:
                            for u in message.new_chat_members:
                                users_to_add_list.append(u)

                        for user in users_to_add_list:
                            if user.is_self or user.is_bot or user.is_deleted:
                                continue

                            async with file_lock:
                                add_queue = safe_load_json(ADD_QUEUE_FILE, [])
                                if not any(u["id"] == user.id for u in add_queue):
                                    add_queue.append(
                                        {
                                            "id": user.id,
                                            "username": user.username,
                                            "first_name": user.first_name or "",
                                            "source_group": str(g)
                                        }
                                    )
                                    safe_save_json(ADD_QUEUE_FILE, add_queue)
                        await asyncio.sleep(0.01)

                except FloodWait as e:
                    await asyncio.sleep(e.value + 5)
                except Exception as ex:
                    await send_admin_alert(f"🚨 **Error Scraping Group ({g}):**\n`{ex}`")

                await asyncio.sleep(60)
            await asyncio.sleep(3600)
        except Exception as ex:
            await send_admin_alert(f"🚨 **Error in scrape_members_worker:**\n`{ex}`")
            await asyncio.sleep(30)


async def queue_status_reporter_task():
    while True:
        await asyncio.sleep(3600)
        try:
            async with file_lock:
                queue = safe_load_json(ADD_QUEUE_FILE, [])
            
            total_queue = len(queue)
            group_counts = {}
            for item in queue:
                g_name = item.get("source_group", "Unknown Group")
                group_counts[g_name] = group_counts.get(g_name, 0) + 1

            report_msg = "📊 **QUEUE STATUS REPORT** 📊\n\n"
            report_msg += f"📌 **Total Queue សរុប:** `{total_queue}` នាក់\n\n"
            report_msg += "📂 **ចំនួន Queue តាម Group នីមួយៗ:**\n"
            
            if group_counts:
                for g_name, count in group_counts.items():
                    report_msg += f"- `{g_name}`: `{count}` នាក់\n"
            else:
                report_msg += "- គ្មានទិន្នន័យ trong Queue ទេ។\n"

            await send_admin_alert(report_msg)
        except Exception as ex:
            print(f"Error sending queue report: {ex}")


async def welcome_queue_worker(client: Client):
    while True:
        try:
            async with file_lock:
                current_queue = safe_load_json(QUEUE_FILE, [])

            if not current_queue or not WELCOME_ENABLED:
                await asyncio.sleep(15)
                continue

            user_data = current_queue[0]
            member_id = user_data["id"]

            try:
                await client.get_users(member_id)
                await asyncio.sleep(2)
                chosen_welcome_msg = random.choice(WELCOME_MESSAGES_LIST)
                sent_msg = await client.send_message(chat_id=member_id, text=chosen_welcome_msg)

                async with file_lock:
                    cq = safe_load_json(QUEUE_FILE, [])
                    if cq:
                        cq.pop(0)
                        safe_save_json(QUEUE_FILE, cq)

                await asyncio.sleep(60)
                try:
                    await sent_msg.delete(revoke=False)
                except Exception:
                    pass
                await asyncio.sleep(600)

            except FloodWait as e:
                await asyncio.sleep(e.value + 2)
            except Exception:
                async with file_lock:
                    cq = safe_load_json(QUEUE_FILE, [])
                    if cq:
                        cq.pop(0)
                        safe_save_json(QUEUE_FILE, cq)
                await asyncio.sleep(5)
        except Exception:
            await asyncio.sleep(10)


async def add_member_manager_task(allowed_clients_tuples):
    current_acc_index = 0
    total_clients = len(allowed_clients_tuples)
    if total_clients == 0:
        return

    while True:
        try:
            if not add_to_groups:
                await asyncio.sleep(30)
                continue

            today_str = datetime.now(ICT).strftime("%Y-%m-%d")
            user_data = None
            
            async with file_lock:
                queue = safe_load_json(ADD_QUEUE_FILE, [])
                if queue:
                    user_data = queue.pop(0)
                    safe_save_json(ADD_QUEUE_FILE, queue)

            if not user_data:
                await asyncio.sleep(15)
                continue

            user_id = user_data["id"]
            username = user_data.get("username")
            first_name = user_data.get("first_name", "")
            target_user = f"@{username}" if username else user_id

            added_success = False
            skip_user_permanently = False

            for attempt in range(total_clients):
                acc_idx = (current_acc_index + attempt) % total_clients
                cli, acc_info = allowed_clients_tuples[acc_idx]
                acc_num = acc_info['index']
                account_key = f"acc_{acc_num}"

                async with file_lock:
                    states = safe_load_json(ADD_DAILY_STATE_FILE, {})
                    acc_state = states.get(account_key, {"date": today_str, "count": 0})
                    if acc_state.get("date") != today_str:
                        acc_state = {"date": today_str, "count": 0}
                        states[account_key] = acc_state
                        safe_save_json(ADD_DAILY_STATE_FILE, states)

                current_acc_limit = account_custom_limits.get(acc_num, 30)
                if acc_state["count"] >= current_acc_limit:
                    continue

                if acc_num in blocked_accounts:
                    if datetime.now(ICT) < blocked_accounts[acc_num]:
                        continue
                    else:
                        del blocked_accounts[acc_num]

                try:
                    user_obj = await cli.get_users(target_user)
                    user_to_add = user_obj.id

                    for g in add_to_groups:
                        await cli.add_chat_members(g, user_to_add)
                        added_success = True
                        t_now = datetime.now(ICT).strftime("%I:%M:%S %p")
                        print(f"[{t_now}] ✅ Acc #{acc_num} បានទាញ {first_name} ({target_user}) ចូល {g}")

                    if added_success:
                        async with file_lock:
                            states = safe_load_json(ADD_DAILY_STATE_FILE, {})
                            acc_st = states.get(account_key, {"date": today_str, "count": 0})
                            acc_st["count"] += 1
                            states[account_key] = acc_st
                            safe_save_json(ADD_DAILY_STATE_FILE, states)

                        current_acc_index = (acc_idx + 1) % total_clients
                        break

                except (PeerFlood, Exception) as ex:
                    ex_str = str(ex)
                    if "PEER_FLOOD" in ex_str or "400 PEER_FLOOD" in ex_str or isinstance(ex, PeerFlood):
                        blocked_accounts[acc_num] = datetime.now(ICT) + timedelta(seconds=3600)
                        continue
                    elif isinstance(ex, (UserPrivacyRestricted, UserRestricted, UserNotMutualContact, UserAlreadyParticipant)):
                        skip_user_permanently = True
                        break
                    else:
                        continue

            if not added_success and not skip_user_permanently:
                async with file_lock:
                    q = safe_load_json(ADD_QUEUE_FILE, [])
                    q.insert(0, user_data)
                    safe_save_json(ADD_QUEUE_FILE, q)
                await asyncio.sleep(600)
            else:
                delay = random.randint(250, 400)
                await asyncio.sleep(delay)

        except Exception as ex:
            await send_admin_alert(f"🚨 **Error in Add Member Manager:**\n`{ex}`")
            await asyncio.sleep(10)


async def single_message_broadcaster_task(client: Client, acc_index: int, targets: list):
    st = safe_load_json(BROADCASTER_STATE_FILE, {})
    acc_st = st.get(f"acc_{acc_index}", {})

    if isinstance(acc_st, int):
        msg_counter = acc_st
        saved_target_index = 0
        wake_up_iso = None
    else:
        msg_counter = acc_st.get("msg_counter", 0)
        saved_target_index = acc_st.get("target_index", 0)
        wake_up_iso = acc_st.get("wake_up_time", None)

    if wake_up_iso:
        try:
            wake_up_dt = datetime.fromisoformat(wake_up_iso)
            now_dt = datetime.now(ICT)
            if now_dt < wake_up_dt:
                await asyncio.sleep((wake_up_dt - now_dt).total_seconds())
        except Exception:
            pass

    if not targets:
        return

    while True:
        if not source_chat_parsed:
            await asyncio.sleep(30)
            continue

        try:
            async with file_lock:
                messages_to_send = safe_load_json(SOURCE_MESSAGES_FILE, [])

            if not messages_to_send:
                await asyncio.sleep(60)
                continue

            msg_counter = msg_counter % len(messages_to_send)
            target_msg_data = messages_to_send[msg_counter]
            total_targets = len(targets)

            start_t_index = saved_target_index + 1
            if start_t_index > total_targets:
                start_t_index = 1
                saved_target_index = 0

            t_index = start_t_index
            skip_current_message = False

            while t_index <= len(targets):
                target = targets[t_index - 1]
                success = False
                attempts = 0
                while not success and attempts < MAX_RETRIES:
                    try:
                        await client.copy_message(
                            chat_id=target,
                            from_chat_id=source_chat_parsed,
                            message_id=target_msg_data["id"],
                        )
                        success = True
                        async with file_lock:
                            curr_st = safe_load_json(BROADCASTER_STATE_FILE, {})
                            curr_st[f"acc_{acc_index}"] = {
                                "msg_counter": msg_counter,
                                "target_index": t_index,
                                "wake_up_time": None
                            }
                            safe_save_json(BROADCASTER_STATE_FILE, curr_st)

                        await asyncio.sleep(random.randint(120, 150))

                    except FloodWait as e:
                        attempts += 1
                        await asyncio.sleep(e.value + 2)
                    except MessageIdInvalid:
                        skip_current_message = True
                        success = True
                        break
                    except Exception as ex:
                        break

                if skip_current_message:
                    break

                if target in targets and success:
                    if t_index % 3 == 0 and t_index < len(targets):
                        await asyncio.sleep(random.randint(130, 150))
                    t_index += 1

            if not skip_current_message:
                msg_counter += 1

            saved_target_index = 0
            async with file_lock:
                curr_st = safe_load_json(BROADCASTER_STATE_FILE, {})
                curr_st[f"acc_{acc_index}"] = {
                    "msg_counter": msg_counter,
                    "target_index": 0,
                    "wake_up_time": None
                }
                safe_save_json(BROADCASTER_STATE_FILE, curr_st)

        except Exception as ex:
            await send_admin_alert(f"🚨 **Error in Broadcaster (Acc #{acc_index}):**\n`{ex}`")
            await asyncio.sleep(10)

        wake_up_time = datetime.now(ICT) + timedelta(seconds=SLEEP_TIME)
        async with file_lock:
            curr_st = safe_load_json(BROADCASTER_STATE_FILE, {})
            curr_st[f"acc_{acc_index}"] = {
                "msg_counter": msg_counter,
                "target_index": saved_target_index,
                "wake_up_time": wake_up_time.isoformat()
            }
            safe_save_json(BROADCASTER_STATE_FILE, curr_st)

        await asyncio.sleep(SLEEP_TIME)


# ------------------------------------------------------------------------------
# MAIN ENTRYPOINT
# ------------------------------------------------------------------------------
async def main():
    if bot_client:
        try:
            await bot_client.start()
            me_bot = await bot_client.get_me()
            print(f"🤖 Notification Bot Connected: @{me_bot.username}")
        except Exception as e:
            print(f"❌ បរាជ័យក្នុងការ Login Bot: {e}")

    if not clients:
        print("❌ សូមបញ្ចូល SESSION_STRING ឬ SESSION_STRING_{i} ក្នុង Environment Variables!")
        return

    # ប្រមូលគ្រប់ Chat IDs / Usernames ទាំងអស់មក Pre-cache ទុកមុន
    chats_to_cache = []
    if target_welcome_groups:
        chats_to_cache.extend(target_welcome_groups)
    if accept_request_groups:
        chats_to_cache.extend(accept_request_groups)
    if add_to_groups:
        chats_to_cache.extend(add_to_groups)
    if source_chat_parsed:
        chats_to_cache.append(source_chat_parsed)
    for cfg in accounts_config:
        if cfg.get('targets'):
            chats_to_cache.extend(cfg['targets'])
    chats_to_cache = list(set(chats_to_cache))

    valid_clients = []
    for idx, (cli, cfg) in enumerate(clients, start=1):
        try:
            await cli.start()
            me = await cli.get_me()
            valid_clients.append((cli, cfg))
            print(f"✅ Client #{cfg['index']} Logged in: {me.first_name}")

            # 🛠️ បង្ខំឱ្យ Client Resolve និង Cache Peer ID របស់ Groups ទាំងអស់ទុកមុន
            for chat in chats_to_cache:
                try:
                    await cli.get_chat(chat)
                except Exception:
                    pass

            try:
                async for dialog in cli.get_dialogs(limit=200):
                    pass
            except Exception as e:
                print(f"⚠️ Warning loading dialogs for Client #{cfg['index']}: {e}")

        except Exception as e:
            print(f"❌ បរាជ័យក្នុងការ Login Client #{cfg['index']}: {e}")

    if not valid_clients:
        print("❌ គ្មាន Client ណាមួយអាច Login ได้ឡើយ! កម្មវិធីត្រូវបានបិទ។")
        return

    t_now = datetime.now(ICT).strftime("%Y-%m-%d %I:%M:%S %p")
    print(f"\n[{t_now}] 🤖 ប្រព័ន្ធដំណើរការជាមួយ Accounts ទាំងអស់ដោយរលូន!")

    if valid_clients:
        first_cli = valid_clients[0][0]
        asyncio.create_task(source_chat_poller_worker(first_cli))
        asyncio.create_task(scrape_members_worker(first_cli))
        asyncio.create_task(welcome_queue_worker(first_cli))
        asyncio.create_task(queue_status_reporter_task())

        adder_clients_tuples = []
        for cli, cfg in valid_clients:
            acc_num = cfg['index']
            if not allowed_add_accounts or acc_num in allowed_add_accounts:
                adder_clients_tuples.append((cli, cfg))

        if adder_clients_tuples:
            asyncio.create_task(add_member_manager_task(adder_clients_tuples))

        for cli, cfg in valid_clients:
            asyncio.create_task(single_message_broadcaster_task(cli, cfg["index"], cfg["targets"]))

    await asyncio.Event().wait()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("\n👋 បិទកម្មវិធីដោយជោគជ័យ!")
