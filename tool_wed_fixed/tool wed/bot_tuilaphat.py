import os
import sys
import json
import asyncio
import random
import time
from datetime import datetime, timezone

import aiohttp
from colorama import init, Fore, Style

# Khởi tạo màu sắc cho Terminal
init(autoreset=True)

# ─────────────────────────────────────────────────────────────────
# CONFIG & CONSTANTS
# ─────────────────────────────────────────────────────────────────
QUEST_API = "https://discord.com/api/v9"
QUEST_HEARTBEAT_INTERVAL = 20
QUEST_SUPPORTED_TASKS = [
    "WATCH_VIDEO", "PLAY_ON_DESKTOP", "STREAM_ON_DESKTOP",
    "PLAY_ACTIVITY", "WATCH_VIDEO_ON_MOBILE",
]
TOKEN_FILE = "tokens.txt"
CONFIG_FILE = "config.json"

# ĐƯỜNG DẪN WEB NETLIFY CỦA BẠN (Hãy thay thế link của bạn vào đây)
BACKEND_URL = "https://fanciful-entremet-6a2e8e.netlify.app/.netlify/functions/backend_x_l_ph_n_b"

# ─────────────────────────────────────────────────────────────────
# HELPERS DISCORD API
# ─────────────────────────────────────────────────────────────────
def _make_quest_headers(token):
    import base64 as _b64, json as _json
    sp = _b64.b64encode(_json.dumps({
        "os": "Windows", "browser": "Discord Client",
        "release_channel": "stable", "client_version": "1.0.9175",
        "os_version": "10.0.26100", "os_arch": "x64", "app_arch": "x64",
        "system_locale": "en-US",
        "browser_user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) discord/1.0.9175 Chrome/128.0.6613.186 Electron/32.2.7 Safari/537.36",
        "browser_version": "32.2.7",
        "client_build_number": 504649,
        "native_build_number": 59498,
        "client_event_source": None,
    }).encode()).decode()
    return {
        "Authorization": token.strip(),
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) discord/1.0.9175 Chrome/128.0.6613.186 Electron/32.2.7 Safari/537.36",
        "X-Super-Properties": sp,
        "X-Discord-Locale": "en-US",
        "Origin": "https://discord.com",
        "Referer": "https://discord.com/channels/@me",
    }

async def check_token(session, token):
    try:
        async with session.get(f"{QUEST_API}/users/@me", headers=_make_quest_headers(token)) as r:
            if r.status == 200:
                data = await r.json()
                return data.get("username", "Unknown")
    except: pass
    return None

def _quest_get(d, *keys):
    if d is None: return None
    for k in keys:
        if k in d: return d[k]
    return None

def _quest_name(quest):
    cfg = quest.get("config", {})
    msgs = cfg.get("messages", {})
    name = _quest_get(msgs, "questName", "quest_name") or _quest_get(msgs, "gameTitle", "game_title")
    return name.strip() if name else f"Quest#{quest.get('id','?')}"

def _quest_task_type(quest):
    cfg = quest.get("config", {})
    tc = _quest_get(cfg, "taskConfig", "task_config", "taskConfigV2", "task_config_v2")
    if not tc or "tasks" not in tc: return None
    for t in QUEST_SUPPORTED_TASKS:
        if tc["tasks"].get(t) is not None: return t
    return None

def _quest_seconds_needed(quest):
    cfg = quest.get("config", {})
    tc = _quest_get(cfg, "taskConfig", "task_config", "taskConfigV2", "task_config_v2")
    task_type = _quest_task_type(quest)
    if not tc or not task_type: return 0
    return tc["tasks"][task_type].get("target", 0)

def _quest_seconds_done(quest):
    task_type = _quest_task_type(quest)
    if not task_type: return 0
    us = _quest_get(quest, "userStatus", "user_status") or {}
    return us.get("progress", {}).get(task_type, {}).get("value", 0)

def _quest_is_enrolled(quest):
    us = _quest_get(quest, "userStatus", "user_status") or {}
    return bool(_quest_get(us, "enrolledAt", "enrolled_at"))

def _quest_is_completed(quest):
    us = _quest_get(quest, "userStatus", "user_status") or {}
    return bool(_quest_get(us, "completedAt", "completed_at"))

def _quest_enrolled_at(quest):
    us = _quest_get(quest, "userStatus", "user_status") or {}
    return _quest_get(us, "enrolledAt", "enrolled_at")

def _quest_is_expired(quest):
    cfg = quest.get("config", {})
    expires = _quest_get(cfg, "expiresAt", "expires_at")
    if not expires: return False
    try:
        exp_dt = datetime.fromisoformat(expires.replace("Z", "+00:00"))
        return exp_dt <= datetime.now(timezone.utc)
    except:
        return False

async def _quest_fetch(session, token):
    try:
        async with session.get(f"{QUEST_API}/quests/@me", headers=_make_quest_headers(token)) as r:
            if r.status == 200:
                data = await r.json()
                if isinstance(data, list): return data
                return data.get("quests", [])
    except: pass
    return []

async def _quest_enroll(session, token, qid, quest):
    try:
        async with session.post(
            f"{QUEST_API}/quests/{qid}/enroll",
            headers=_make_quest_headers(token),
            json={"location": 11, "is_targeted": False, "metadata_raw": None, "metadata_sealed": None,
                  "traffic_metadata_raw": quest.get("traffic_metadata_raw"),
                  "traffic_metadata_sealed": quest.get("traffic_metadata_sealed")}
        ) as r:
            return r.status in (200, 201, 204)
    except: return False

async def _quest_video_progress(session, token, qid, timestamp):
    try:
        async with session.post(f"{QUEST_API}/quests/{qid}/video-progress",
            headers=_make_quest_headers(token), json={"timestamp": timestamp}) as r:
            if r.status == 200: return await r.json()
    except: pass
    return {}

async def _quest_heartbeat(session, token, qid, stream_key, terminal=False):
    try:
        async with session.post(f"{QUEST_API}/quests/{qid}/heartbeat",
            headers=_make_quest_headers(token), json={"stream_key": stream_key, "terminal": terminal}) as r:
            if r.status == 200: return await r.json()
    except: pass
    return {}

# ─────────────────────────────────────────────────────────────────
# ĐỒNG BỘ LOG HOẠT ĐỘNG LÊN WEB CỦA BẠN (add_log action)
# ─────────────────────────────────────────────────────────────────
async def send_web_log(session, key, message):
    if not key: return
    try:
        await session.post(BACKEND_URL, json={
            "action": "add_log",
            "key": key,
            "log": message
        })
    except:
        pass

# ─────────────────────────────────────────────────────────────────
# TIẾN TRÌNH: HYPESQUAD
# ─────────────────────────────────────────────────────────────────
async def set_hypesquad(session, token, house_id, index, username, key=None):
    url = f"{QUEST_API}/hypesquad/online"
    payload = {"house_id": house_id}
    headers = _make_quest_headers(token)
    try:
        async with session.post(url, json=payload, headers=headers) as r:
            house_name = {1: "Bravery (Tím)", 2: "Brilliance (Đỏ)", 3: "Balance (Xanh lục)"}.get(house_id, "Unknown")
            if r.status == 204:
                msg = f"[Acc {index}] ✅ {username}: Đã tham gia {house_name}!"
                print(f"{Fore.GREEN}{msg}")
                if key: await send_web_log(session, key, msg)
            else:
                msg = f"[Acc {index}] ❌ Lỗi {username}: {r.status} (Không thể đổi)"
                print(f"{Fore.RED}{msg}")
                if key: await send_web_log(session, key, msg)
    except Exception as e:
        print(f"{Fore.RED}[Acc {index}] ❌ Lỗi kết nối {username}: {str(e)}")

async def run_hypesquad(tokens, house_id, key=None):
    print(f"\n{Fore.CYAN}[*] Bắt đầu set HypeSquad cho {len(tokens)} account...")
    connector = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = []
        for i, token in enumerate(tokens, 1):
            user = await check_token(session, token)
            if user:
                tasks.append(set_hypesquad(session, token, house_id, i, user, key))
            else:
                print(f"{Fore.RED}[Acc {i}] ❌ Token lỗi hoặc đã bị khóa.")
        if tasks:
            await asyncio.gather(*tasks)

# ─────────────────────────────────────────────────────────────────
# TIẾN TRÌNH: AUTO QUEST
# ─────────────────────────────────────────────────────────────────
async def process_account(token, index, key=None):
    connector = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        username = await check_token(session, token)
        if not username:
            msg = f"[Acc {index}] ❌ Token lỗi hoặc đã bị khóa."
            print(f"{Fore.RED}{msg}")
            if key: await send_web_log(session, key, msg)
            return

        msg_start = f"[Acc {index}] 👤 Đang chạy cho: {username}"
        print(f"{Fore.CYAN}{msg_start}")
        if key: await send_web_log(session, key, msg_start)

        quests = await _quest_fetch(session, token)

        if not quests:
            msg_warn = f"[Acc {index}] ⚠️ Không tìm thấy quest nào của {username}."
            print(f"{Fore.YELLOW}{msg_warn}")
            if key: await send_web_log(session, key, msg_warn)
            return

        for q in quests:
            if _quest_is_expired(q): continue
            if not _quest_is_enrolled(q) and not _quest_is_completed(q):
                qid = q["id"]
                msg_enroll = f"[Acc {index}] 📋 Đang nhận quest: {_quest_name(q)}..."
                print(f"{Fore.CYAN}{msg_enroll}")
                if key: await send_web_log(session, key, msg_enroll)
                await _quest_enroll(session, token, qid, q)
                await asyncio.sleep(3)

        quests = await _quest_fetch(session, token)

        for q in quests:
            if _quest_is_expired(q) or not _quest_is_enrolled(q) or _quest_is_completed(q): 
                continue
            
            qid = q["id"]
            name = _quest_name(q)
            task_type = _quest_task_type(q)
            if not task_type: continue
            
            seconds_needed = _quest_seconds_needed(q)
            seconds_done = _quest_seconds_done(q)
            
            msg_task = f"[Acc {index}] ▶️ Bắt đầu: {name} | {seconds_done}/{seconds_needed}s"
            print(f"{Fore.YELLOW}{msg_task}")
            if key: await send_web_log(session, key, msg_task)

            if task_type in ("WATCH_VIDEO", "WATCH_VIDEO_ON_MOBILE"):
                enrolled_at = _quest_enrolled_at(q)
                enrolled_ts = datetime.fromisoformat(enrolled_at.replace("Z", "+00:00")).timestamp() if enrolled_at else time.time()
                speed = 7
                
                while seconds_done < seconds_needed:
                    max_allowed = (time.time() - enrolled_ts) + 10
                    if (max_allowed - seconds_done) >= speed:
                        timestamp = min(seconds_needed, seconds_done + speed + random.random())
                        body = await _quest_video_progress(session, token, qid, timestamp)
                        
                        if body.get("completed_at"):
                            seconds_done = seconds_needed
                            break
                            
                        seconds_done = min(seconds_needed, timestamp)
                        
                    pct = int((seconds_done / seconds_needed) * 100) if seconds_needed else 0
                    print(f"{Fore.LIGHTBLACK_EX}[Acc {index}] ⏳ {name}: {pct}% ({int(seconds_done)}/{seconds_needed}s)")
                    
                    if seconds_done >= seconds_needed: break
                    await asyncio.sleep(1)
                    
                await _quest_video_progress(session, token, qid, seconds_needed)

            elif task_type in ("PLAY_ON_DESKTOP", "STREAM_ON_DESKTOP", "PLAY_ACTIVITY"):
                pid = random.randint(1000, 30000)
                stream_key = f"call:0:{pid}"
                
                while seconds_done < seconds_needed:
                    body = await _quest_heartbeat(session, token, qid, stream_key, terminal=False)
                    progress = body.get("progress", {})
                    
                    if progress and task_type in progress:
                        seconds_done = progress[task_type].get("value", seconds_done)
                        
                    pct = int((seconds_done / seconds_needed) * 100) if seconds_needed else 0
                    print(f"{Fore.LIGHTBLACK_EX}[Acc {index}] ⏳ {name}: {pct}% ({int(seconds_done)}/{seconds_needed}s)")
                    
                    if body.get("completed_at") or seconds_done >= seconds_needed: break
                    await asyncio.sleep(QUEST_HEARTBEAT_INTERVAL)
                    
                await _quest_heartbeat(session, token, qid, stream_key, terminal=True)

            msg_done = f"[Acc {index}] ✅ Xong quest: {name} cho {username}"
            print(f"{Fore.GREEN}{msg_done}")
            if key: await send_web_log(session, key, msg_done)
            await asyncio.sleep(3)

        msg_finish = f"[Acc {index}] 🎉 Hoàn thành nhiệm vụ nick: {username}!"
        print(f"{Fore.GREEN}{msg_finish}")
        if key: await send_web_log(session, key, msg_finish)

async def run_auto_quest(tokens, key=None):
    print(f"\n{Fore.CYAN}[*] Bắt đầu chạy Auto Quest cho {len(tokens)} account...")
    tasks = [process_account(token, i, key) for i, token in enumerate(tokens, 1)]
    await asyncio.gather(*tasks)

# ─────────────────────────────────────────────────────────────────
# QUẢN LÝ CẤU HÌNH LOG CỤC BỘ (LOCAL FILE DATA)
# ─────────────────────────────────────────────────────────────────
def load_config():
    if not os.path.exists(CONFIG_FILE):
        return {"key": ""}
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {"key": ""}

def save_config(config):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4)

def get_tokens():
    if not os.path.exists(TOKEN_FILE):
        open(TOKEN_FILE, "w").close()
    with open(TOKEN_FILE, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]

def save_tokens(tokens):
    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
        for t in tokens:
            f.write(t + "\n")

# ─────────────────────────────────────────────────────────────────
# ĐỒNG BỘ TOKENS TỪ CLOUD CỦA WEB BẠN (Hành động validate)
# ─────────────────────────────────────────────────────────────────
async def sync_from_cloud(key):
    connector = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        try:
            async with session.post(BACKEND_URL, json={"action": "validate", "key": key}) as r:
                data = await r.json()
                if data.get("valid") and data.get("tokens"):
                    tkn = data["tokens"]
                    # Đọc đúng cấu trúc token phân bổ trên web panel gốc của bạn
                    quest = tkn.get("quest") or []
                    hs_1 = tkn.get("hs_1") or []
                    hs_2 = tkn.get("hs_2") or []
                    hs_3 = tkn.get("hs_3") or []
                    return quest, hs_1, hs_2, hs_3
        except Exception as e:
            print(f"{Fore.RED}[!] Thất bại khi kết nối máy chủ Cloud: {str(e)}")
    return None

# ─────────────────────────────────────────────────────────────────
# GIAO DIỆN TERMINAL ĐIỀU KHIỂN
# ─────────────────────────────────────────────────────────────────
async def loc_token():
    tokens = get_tokens()
    if not tokens:
        print(f"{Fore.RED}[!] Không có token nào trong file tokens.txt.")
        input("Nhấn Enter để quay lại...")
        return
    print(f"\n{Fore.CYAN}[*] Đang lọc token...")
    connector = aiohttp.TCPConnector(ssl=False)
    live_tokens = []
    async with aiohttp.ClientSession(connector=connector) as session:
        for t in tokens:
            user = await check_token(session, t)
            if user:
                print(f"{Fore.GREEN}[+] LIVE: {user}")
                live_tokens.append(t)
            else:
                print(f"{Fore.RED}[-] DEAD: Token đã chết")

    save_tokens(live_tokens)
    print(f"\n{Fore.GREEN}[!] Đã lọc sạch và lưu lại {len(live_tokens)} token còn hoạt động.")
    input("Nhấn Enter để quay lại...")

def print_menu(key, total_local):
    os.system("cls" if os.name == "nt" else "clear")
    banner = f"""
{Fore.CYAN}======================================================================
{Fore.MAGENTA} _____ _   _ ___ _      _    ____  _   _    _  _____ 
{Fore.MAGENTA}|_   _| | | |_ _| |    / \\  |  _ \\| | | |  / \\|_   _|
{Fore.YELLOW}  | | | | | || || |   / _ \\ | |_) | |_| | / _ \\ | |  
{Fore.YELLOW}  | | | |_| || || |__/ ___ \\|  __/|  _  |/ ___ \\| |  
{Fore.GREEN}  |_|  \\___/|___|____/_/   \\_\\_|  |_| |_/_/   \\_\\_|  
{Fore.CYAN}                    --- TUILAPHAT TOOL BOT ---                      
{Fore.CYAN}======================================================================
{Fore.RED} >>> BOT ĐỒNG BỘ AUTO QUEST & HYPESQUAD DISCORD 24/7 <<<
{Fore.CYAN}----------------------------------------------------------------------
{Fore.YELLOW} Key đang liên kết: {key if key else "CHƯA ĐĂNG NHẬP"}
{Fore.YELLOW} Token cục bộ trong file (TXT): {total_local}
{Fore.CYAN}----------------------------------------------------------------------
{Fore.GREEN}[1] Bắt đầu Treo Auto Quest (Dùng Token trong file TXT)
{Fore.GREEN}[2] Tham gia HypeSquad (Dùng Token trong file TXT)
{Fore.GREEN}[3] Thêm Token mới vào Database TXT
{Fore.GREEN}[4] Quản lý Danh sách & Lọc sạch Token Dead
{Fore.GREEN}[5] Đổi Key đăng nhập / Đồng bộ Cloud
{Fore.CYAN}----------------------------------------------------------------------
{Fore.RED}[6] CHẠY CHẾ ĐỘ BOT AUTO 24/7 (Tự động cày tất cả từ Web Panel)
{Fore.RED}[7] Thoát công cụ (Exit)
{Fore.CYAN}======================================================================
"""
    print(banner)

async def start_bot_auto_loop(key):
    if not key:
        print(f"{Fore.RED}[!] Vui lòng kết nối Key web của bạn ở mục [5] trước khi chạy chế độ tự động!")
        await asyncio.sleep(2)
        return
    print(f"\n{Fore.GREEN}[🚀] ĐÃ KÍCH HOẠT CHẾ ĐỘ BOT TỰ ĐỘNG 24/7!")
    print(f"{Fore.CYAN}[*] Bot đang theo dõi và chạy nhiệm vụ phân bổ từ Key: {key}")
    print(f"{Fore.YELLOW}[*] Hệ thống tự động đồng bộ & cày Quest/HypeSquad liên tục 24/7.")
    print(f"{Fore.LIGHTBLACK_EX}[*] Bạn có thể ném token và lưu phân bổ trên web bất kỳ lúc nào!")
    print(f"{Fore.LIGHTBLACK_EX}[*] Nhấn Ctrl+C để tắt bot chạy tự động và về menu.")

    await asyncio.sleep(3)

    connector = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        await send_web_log(session, key, "🤖 BOT SYSTEM: Máy chủ chạy ngầm đã khởi chạy thành công!")

    cycle_count = 1
    while True:
        try:
            print(f"\n{Fore.MAGENTA}[Chu kỳ #{cycle_count}] — Đang đồng bộ phân bổ từ Website...")
            cloud_data = await sync_from_cloud(key)
            
            if cloud_data is None:
                print(f"{Fore.RED}[!] Lỗi đồng bộ dữ liệu đám mây. Thử lại sau 30 giây.")
                await asyncio.sleep(30)
                continue
            
            quest_tokens, hs_1, hs_2, hs_3 = cloud_data
            total_cloud = len(quest_tokens) + len(hs_1) + len(hs_2) + len(hs_3)
            print(f"{Fore.GREEN}[✓] Đồng bộ thành công! Tìm thấy {total_cloud} tokens trên Web.")

            connector = aiohttp.TCPConnector(ssl=False)
            async with aiohttp.ClientSession(connector=connector) as session:
                # 1. Chạy Auto Quest
                if quest_tokens:
                    print(f"\n{Fore.YELLOW}[*] Chạy nhóm Auto Quest ({len(quest_tokens)} nick)...")
                    await send_web_log(session, key, f"⚙️ BOT SYSTEM: Tiến hành cày Quest cho {len(quest_tokens)} tài khoản...")
                    await run_auto_quest(quest_tokens, key)
                
                # 2. Chạy HypeSquad Tím
                if hs_1:
                    print(f"\n{Fore.YELLOW}[*] Chạy HypeSquad Bravery - Tím ({len(hs_1)} nick)...")
                    await send_web_log(session, key, f"🔮 BOT SYSTEM: Cập nhật HypeSquad Bravery cho {len(hs_1)} tài khoản...")
                    await run_hypesquad(hs_1, 1, key)
                
                # 3. Chạy HypeSquad Đỏ
                if hs_2:
                    print(f"\n{Fore.YELLOW}[*] Chạy HypeSquad Brilliance - Đỏ ({len(hs_2)} nick)...")
                    await send_web_log(session, key, f"🔥 BOT SYSTEM: Cập nhật HypeSquad Brilliance cho {len(hs_2)} tài khoản...")
                    await run_hypesquad(hs_2, 2, key)
                
                # 4. Chạy HypeSquad Xanh
                if hs_3:
                    print(f"\n{Fore.YELLOW}[*] Chạy HypeSquad Balance - Xanh ({len(hs_3)} nick)...")
                    await send_web_log(session, key, f"🌿 BOT SYSTEM: Cập nhật HypeSquad Balance cho {len(hs_3)} tài khoản...")
                    await run_hypesquad(hs_3, 3, key)

                # Kết thúc chu kỳ
                cycle_msg = f"💤 BOT SYSTEM: Chu kỳ #{cycle_count} hoàn tất. Đợi 15 phút đến chu kỳ tiếp theo..."
                print(f"\n{Fore.GREEN}{cycle_msg}")
                await send_web_log(session, key, cycle_msg)

            cycle_count += 1
            
            # Đếm ngược thời gian chờ chu kỳ tiếp theo (15 phút)
            for countdown in range(900, 0, -30):
                print(f"{Fore.LIGHTBLACK_EX}[Chờ] Bắt đầu chu kỳ tiếp theo sau {countdown} giây...", end="\r")
                await asyncio.sleep(30)

        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"\n{Fore.RED}[❌] Lỗi đột xuất trong luồng chạy: {str(e)}")
            await asyncio.sleep(30)

async def main_loop():
    config = load_config()
    current_key = config.get("key", "")
    while True:
        tokens_local = get_tokens()
        print_menu(current_key, len(tokens_local))
        choice = input(f"{Fore.GREEN}Nhập lựa chọn của bạn (1-7): {Style.RESET_ALL}").strip()
        
        if choice == '1':
            if not tokens_local:
                print(f"\n{Fore.RED}[!] File tokens.txt trống. Chọn mục [3] để nạp token!")
                input("Nhấn Enter để quay lại...")
            else:
                await run_auto_quest(tokens_local)
                
        elif choice == '2':
            if not tokens_local:
                print(f"\n{Fore.RED}[!] File tokens.txt trống. Chọn mục [3] để nạp token!")
                input("Nhấn Enter để quay lại...")
            else:
                print(f"\n{Fore.CYAN}[*] Chọn nhà HypeSquad bạn muốn tham gia:")
                print(f"{Fore.MAGENTA}[1] Bravery (Tím)")
                print(f"{Fore.RED}[2] Brilliance (Đỏ)")
                print(f"{Fore.GREEN}[3] Balance (Xanh lục)")
                hs_choice = input(f"{Fore.YELLOW}Nhập ID nhà (1-3): {Style.RESET_ALL}").strip()
                
                if hs_choice in ['1', '2', '3']:
                    await run_hypesquad(tokens_local, int(hs_choice))
                else:
                    print(f"{Fore.RED}[!] Lựa chọn không hợp lệ!")
                    await asyncio.sleep(1)
                
        elif choice == '3':
            print(f"\n{Fore.CYAN}[*] Nhập danh sách token (Nhấn Enter 2 lần liên tiếp để kết thúc):")
            new_tokens = []
            while True:
                tk = input().strip()
                if not tk: break
                new_tokens.append(tk)
            
            if new_tokens:
                old_tokens = get_tokens()
                save_tokens(old_tokens + new_tokens)
                print(f"{Fore.GREEN}[+] Đã nạp thành công {len(new_tokens)} token vào file tokens.txt!")
            input("Nhấn Enter để quay lại...")
            
        elif choice == '4':
            await loc_token()

        elif choice == '5':
            new_key = input(f"\n{Fore.YELLOW}Nhập Key đăng nhập Website của bạn: {Style.RESET_ALL}").strip().upper()
            if new_key:
                print(f"{Fore.CYAN}[*] Đang xác thực Key lên website của bạn...")
                connector = aiohttp.TCPConnector(ssl=False)
                async with aiohttp.ClientSession(connector=connector) as session:
                    try:
                        async with session.post(BACKEND_URL, json={"action": "validate", "key": new_key}) as r:
                            data = await r.json()
                            if data.get("valid"):
                                current_key = new_key
                                config["key"] = current_key
                                save_config(config)
                                print(f"{Fore.GREEN}[✓] Xác thực Key thành công! Đã kết nối đồng bộ.")
                            else:
                                print(f"{Fore.RED}[❌] Lỗi: Key không tồn tại hoặc đã hết hạn trên database của bạn.")
                    except Exception as e:
                        print(f"{Fore.RED}[❌] Không kết nối được với Netlify của bạn: {str(e)}")
            input("\nNhấn Enter để quay lại...")
            
        elif choice == '6':
            try:
                await start_bot_auto_loop(current_key)
            except KeyboardInterrupt:
                print(f"\n{Fore.YELLOW}[!] Đã dừng bot chạy tự động.")
                await asyncio.sleep(1.5)

        elif choice == '7':
            print(f"\n{Fore.YELLOW}[!] Đang tắt hệ thống...")
            sys.exit(0)
            
        else:
            print(f"{Fore.RED}[!] Lựa chọn không hợp lệ!")
            await asyncio.sleep(1)

if __name__ == "__main__":
    try:
        asyncio.run(main_loop())
    except KeyboardInterrupt:
        print(f"\n{Fore.YELLOW}[!] Đã dừng kịch bản.")
        sys.exit(0)