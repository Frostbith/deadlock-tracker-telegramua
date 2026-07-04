#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Deadlock SteamDB Changelist Tracker Bot (Standalone Edition)
Бот для відстеження оновлень гри Deadlock на SteamDB та надсилання сповіщень у Telegram.

Цей файл є повністю автономним (Standalone) та не потребує встановлення сторонніх бібліотек.
Він використовує виключно стандартну бібліотеку Python (urllib, json, datetime, zoneinfo).
"""

import os
import sys
import time
import json
import logging
import tempfile
import traceback
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path

# =====================================================================
# КОНФІГУРАЦІЯ БОТА (Конфігуруйте тут або використовуйте файл .env)
# =====================================================================
TELEGRAM_BOT_TOKEN = "your_bot_token_here"
TELEGRAM_CHAT_ID = "@your_channel_username"
CHECK_INTERVAL = 90
API_TIMEOUT = 15
# =====================================================================

BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
STATE_FILE = BASE_DIR / "last_known.json"

# Назви ігор Deadlock та їхні AppID для відстеження
APPS = {
    1422450: "Deadlock",
    3488080: "Deadlock Experimental"
}


def load_env():
    """Мануальне зчитування файлу .env для уникнення залежності від python-dotenv."""
    global TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, CHECK_INTERVAL, API_TIMEOUT
    
    if not ENV_PATH.exists():
        return
        
    try:
        with open(ENV_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip()
                    
                    # Видаляємо можливі лапки навколо значення
                    if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                        val = val[1:-1]
                        
                    if key == "TELEGRAM_BOT_TOKEN":
                        TELEGRAM_BOT_TOKEN = val
                    elif key == "TELEGRAM_CHAT_ID":
                        TELEGRAM_CHAT_ID = val
                    elif key == "CHECK_INTERVAL":
                        try:
                            CHECK_INTERVAL = int(val)
                        except ValueError:
                            pass
                    elif key == "API_TIMEOUT":
                        try:
                            API_TIMEOUT = int(val)
                        except ValueError:
                            pass
    except Exception as e:
        print(f"Помилка при зчитуванні файлу .env: {e}")


# Завантажуємо конфігурацію з .env, якщо він існує
load_env()

# Налаштування логування
logger = logging.getLogger("DeadlockTracker")
logger.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

# Вивід у консоль
stdout_handler = logging.StreamHandler(sys.stdout)
stdout_handler.setFormatter(formatter)
logger.addHandler(stdout_handler)


def check_config():
    """Перевірка обов'язкових конфігураційних даних."""
    missing = []
    if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "your_bot_token_here":
        missing.append("TELEGRAM_BOT_TOKEN")
    if not TELEGRAM_CHAT_ID or TELEGRAM_CHAT_ID == "@your_channel_username":
        missing.append("TELEGRAM_CHAT_ID")
        
    if missing:
        logger.critical(f"Помилка конфігурації! Не вказано значення для: {', '.join(missing)}")
        logger.critical("Вкажіть їх безпосередньо в коді bot.py або створіть файл .env")
        sys.exit(1)


def load_state() -> dict:
    """Завантажує останній відомий стан із файлу last_known.json."""
    if not STATE_FILE.exists():
        logger.info(f"Файл стану {STATE_FILE} не знайдено. Створюємо новий.")
        return {}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        logger.warning(f"Файл стану {STATE_FILE} пошкоджений. Ініціалізуємо новий.")
        return {}
    except Exception as e:
        logger.error(f"Помилка при завантаженні файлу стану: {e}")
        return {}


def save_state(state: dict):
    """Безпечно зберігає поточний стан у файл за допомогою тимчасового файлу."""
    try:
        temp_fd, temp_path = tempfile.mkstemp(dir=STATE_FILE.parent, prefix="state_temp_", suffix=".json")
        try:
            with os.fdopen(temp_fd, 'w', encoding='utf-8') as f:
                json.dump(state, f, indent=4, ensure_ascii=False)
            os.replace(temp_path, STATE_FILE)
        except Exception as e:
            if os.path.exists(temp_path):
                os.remove(temp_path)
            raise e
    except Exception as e:
        logger.error(f"Помилка при збереженні стану у файл: {e}")


def get_latest_changenumber(appid: int) -> int:
    """Отримує поточний changenumber для AppID через SteamCMD API за допомогою urllib."""
    url = f"https://api.steamcmd.net/v1/info/{appid}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json"
        }
    )
    
    with urllib.request.urlopen(req, timeout=API_TIMEOUT) as response:
        res_json = json.loads(response.read().decode("utf-8"))
        
    if res_json.get("status") != "success":
        raise ValueError(f"Неуспішний статус відповіді API: {res_json.get('status')}")
        
    data = res_json.get("data", {})
    app_data = data.get(str(appid))
    if not app_data:
        raise ValueError(f"Дані про AppID {appid} відсутні у відповіді API")
        
    changenumber = app_data.get("_change_number")
    if changenumber is None:
        raise ValueError(f"Параметр '_change_number' не знайдено у відповіді для AppID {appid}")
        
    return int(changenumber)


def format_times():
    """Повертає дату, час у Києві та час у Сієтлі (без сторонніх бібліотек)."""
    utc_now = datetime.now(timezone.utc)
    
    # Спроба використати вбудований ZoneInfo
    try:
        from zoneinfo import ZoneInfo
        kyiv_zone = ZoneInfo("Europe/Kyiv")
        seattle_zone = ZoneInfo("America/Los_Angeles")
        
        kyiv_now = utc_now.astimezone(kyiv_zone)
        seattle_now = utc_now.astimezone(seattle_zone)
        
        date_str = kyiv_now.strftime("%d.%m.%Y")
        kyiv_time_str = kyiv_now.strftime("%H:%M")
        seattle_time_str = seattle_now.strftime("%H:%M")
    except Exception:
        # Автономний математичний розрахунок як запасний варіант
        month = utc_now.month
        day = utc_now.day
        
        # Літній час для України (остання неділя березня - остання неділя жовтня)
        is_kyiv_dst = False
        if 3 < month < 10:
            is_kyiv_dst = True
        elif month == 3:
            is_kyiv_dst = day >= 25
        elif month == 10:
            is_kyiv_dst = day < 25
            
        # Літній час для США (друга неділя березня - перша неділя листопада)
        is_seattle_dst = False
        if 3 < month < 11:
            is_seattle_dst = True
        elif month == 3:
            is_seattle_dst = day >= 10
        elif month == 11:
            is_seattle_dst = day < 3
            
        kyiv_offset = 3 if is_kyiv_dst else 2
        seattle_offset = -7 if is_seattle_dst else -8
        
        kyiv_now = utc_now + timedelta(hours=kyiv_offset)
        seattle_now = utc_now + timedelta(hours=seattle_offset)
        
        date_str = kyiv_now.strftime("%d.%m.%Y")
        kyiv_time_str = kyiv_now.strftime("%H:%M")
        seattle_time_str = seattle_now.strftime("%H:%M")
        
    return date_str, kyiv_time_str, seattle_time_str


def send_telegram_request(payload: dict) -> dict:
    """Надсилає POST запит до Telegram Bot API за допомогою urllib."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = json.dumps(payload).encode("utf-8")
    
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    
    with urllib.request.urlopen(req, timeout=API_TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8"))


def get_deadlock_version_from_github() -> str:
    """Отримує поточну версію клієнта Deadlock (ClientVersion) з репозиторію GameTracking."""
    url = "https://raw.githubusercontent.com/SteamTracking/GameTracking-Deadlock/master/game/citadel/steam.inf"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as response:
            content = response.read().decode("utf-8")
            for line in content.splitlines():
                if line.startswith("ClientVersion="):
                    return line.split("=", 1)[1].strip()
    except Exception as e:
        logger.warning(f"Не вдалося отримати версію з GitHub: {e}")
    return ""



def send_telegram_notification(app_name: str, appid: int, old_cn: int, new_cn: int, old_ver: str = "", new_ver: str = "", ver_updated: int = -1) -> bool:
    """Надсилає повідомлення про зміну changenumber або версії в Telegram-канал у новому візуальному дизайні."""
    date_str, kyiv_time, seattle_time = format_times()
    
    if old_ver and new_ver:
        # Для головної версії Deadlock показуємо версію клієнта
        message = (
            f"<b>{app_name}</b>\n\n"
            f"<b>|</b> <code>{old_ver} =&gt; {new_ver}</code>\n"
            f"<b>|</b> Оновлено Версій: {ver_updated}\n\n"
            f"<b>Дата та час</b>\n\n"
            f"<b>|</b> <code>{date_str}</code> <b>|</b>\n"
            f"<b>|</b> <code>{kyiv_time} Київ</code> <b>|</b>\n"
            f"<b>|</b> <code>{seattle_time} Сієтл</code> <b>|</b>\n\n"
            f"@Deadlockua @mikolaich07"
        )
    else:
        # Для Експериментальної версії (де немає версії клієнта) показуємо changenumber і не пишемо лінію "Оновлено Версій"
        message = (
            f"<b>{app_name}</b>\n\n"
            f"<b>|</b> <code>{old_cn} =&gt; {new_cn}</code>\n\n"
            f"<b>Дата та час</b>\n\n"
            f"<b>|</b> <code>{date_str}</code> <b>|</b>\n"
            f"<b>|</b> <code>{kyiv_time} Київ</code> <b>|</b>\n"
            f"<b>|</b> <code>{seattle_time} Сієтл</code> <b>|</b>\n\n"
            f"@Deadlockua @mikolaich07"
        )
    
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    
    try:
        res_json = send_telegram_request(payload)
        if not res_json.get("ok"):
            logger.error(f"Помилка надсилання повідомлення в Telegram: {res_json}")
            return False
        logger.info(f"Надіслано сповіщення для {app_name} (AppID {appid}): CN {old_cn} -> {new_cn}")
        return True
    except Exception as e:
        logger.error(f"Помилка при відправці запиту до Telegram API: {e}")
        return False


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Deadlock SteamDB Updates Tracker Bot")
    parser.add_argument("--test", action="store_true", help="Надіслати тестове сповіщення в Telegram та завершити роботу")
    args = parser.parse_args()
    
    if args.test:
        logger.info("==========================================")
        logger.info("Запуск бота в тестовому режимі...")
        logger.info("==========================================")
        check_config()
        date_str, kyiv_time, seattle_time = format_times()
        test_message = (
            f"<b>Deadlock</b>\n\n"
            f"<b>|</b> <code>6612 =&gt; 6612</code>\n"
            f"<b>|</b> Оновлено Версій: 0\n\n"
            f"<b>Дата та час</b>\n\n"
            f"<b>|</b> <code>{date_str}</code> <b>|</b>\n"
            f"<b>|</b> <code>{kyiv_time} Київ</code> <b>|</b>\n"
            f"<b>|</b> <code>{seattle_time} Сієтл</code> <b>|</b>\n\n"
            f"@Deadlockua @mikolaich07"
        )
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": test_message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        try:
            send_telegram_request(payload)
            logger.info("УСПІХ! Тестове повідомлення успішно надіслано в Telegram.")
            sys.exit(0)
        except Exception as e:
            logger.error(f"ПОМИЛКА при надсиланні тестового повідомлення: {e}")
            logger.error("Будь ласка, перевірте:")
            logger.error("1. Чи правильний TELEGRAM_BOT_TOKEN у .env (або bot.py)")
            logger.error("2. Чи правильний TELEGRAM_CHAT_ID у .env (або bot.py)")
            logger.error("3. Чи доданий бот у канал або групу як АДМІНІСТРАТОР із дозволом на надсилання повідомлень")
            sys.exit(1)

    logger.info("==========================================")
    logger.info("Запуск бота Deadlock SteamDB Tracker...")
    logger.info("==========================================")
    
    # 1. Перевірка конфігурації
    check_config()
    
    # 2. Завантаження стану
    state = load_state()
    state_modified = False
    
    # 3. Первинна ініціалізація та синхронізація з актуальними даними
    logger.info("Синхронізація стану з поточними даними Steam...")
    for appid, name in APPS.items():
        appid_str = str(appid)
        logger.info(f"Отримання актуального changenumber для {name} ({appid})...")
        retries = 3
        current_cn = 0
        for attempt in range(1, retries + 1):
            try:
                current_cn = get_latest_changenumber(appid)
                break
            except Exception as e:
                logger.warning(f"Спроба {attempt}/{retries} отримання версії для AppID {appid} завершилася помилкою: {e}")
                if attempt < retries:
                    time.sleep(5)
                    
        if current_cn > 0:
            # Оновлюємо стан на актуальний без надсилання сповіщень
            if state.get(appid_str) != current_cn:
                state[appid_str] = current_cn
                state_modified = True
                logger.info(f"Оновлено стан для {name} ({appid}) на актуальний: {current_cn}")
        else:
            if appid_str not in state:
                state[appid_str] = 0
                state_modified = True

        # На додачу до changenumber, для головного AppID 1422450 ми синхронізуємо ClientVersion з GitHub
        if appid == 1422450:
            version_key = f"{appid_str}_version"
            current_ver = get_deadlock_version_from_github()
            if current_ver:
                if state.get(version_key) != current_ver:
                    state[version_key] = current_ver
                    state_modified = True
                    logger.info(f"Оновлено клієнтську версію для {name} ({appid}) на актуальну: {current_ver}")
            else:
                if version_key not in state:
                    state[version_key] = "unknown"
                    state_modified = True
        elif appid == 3488080:
            version_key = f"{appid_str}_version"
            if version_key not in state:
                state[version_key] = "1926"
                state_modified = True
                logger.info(f"Ініціалізовано початкову версію для {name} ({appid}): 1926")
                
        # Затримка між запитами при ініціалізації
        time.sleep(2)
            
    if state_modified:
        save_state(state)
        logger.info("Початковий стан успішно синхронізовано та збережено в last_known.json.")
    
    logger.info(f"Моніторинг розпочато. Інтервал перевірки: {CHECK_INTERVAL} секунд.")
    
    # 4. Основний цикл моніторингу
    try:
        while True:
            logger.info("Початок перевірки оновлень...")
            
            for appid, name in APPS.items():
                appid_str = str(appid)
                old_cn = state.get(appid_str, 0)
                
                # Перевіряємо чи є відкладене оновлення для цього AppID
                pending_key = f"pending_{appid_str}"
                pending = state.get(pending_key)
                
                if pending:
                    logger.info(f"Виявлено відкладене оновлення для {name} ({appid}). Перевіряємо версію на GitHub...")
                    current_ver = get_deadlock_version_from_github()
                    old_ver = pending["old_ver"]
                    
                    if current_ver and current_ver != old_ver:
                        logger.info(f"Знайдено нову версію на GitHub під час відкладеного моніторингу: {current_ver}")
                        new_cn = pending["new_cn"]
                        
                        send_telegram_notification(
                            name, appid, pending["old_cn"], new_cn,
                            old_ver=old_ver, new_ver=current_ver, ver_updated=1
                        )
                        
                        state[appid_str] = new_cn
                        state[f"{appid_str}_version"] = current_ver
                        state.pop(pending_key, None)
                        save_state(state)
                        continue
                    
                    time_passed = time.time() - pending["timestamp"]
                    if time_passed >= 300:
                        logger.info("Минуло 5 хвилин очікування на GitHub. Оновлення визнано технічним.")
                        new_cn = pending["new_cn"]
                        
                        send_telegram_notification(
                            name, appid, pending["old_cn"], new_cn,
                            old_ver=old_ver, new_ver=old_ver, ver_updated=0
                        )
                        
                        state[appid_str] = new_cn
                        state.pop(pending_key, None)
                        save_state(state)
                        continue
                    else:
                        logger.info(f"Очікуємо оновлення GitHub. Минуло {int(time_passed)} сек з 300.")
                        continue
                
                try:
                    new_cn = get_latest_changenumber(appid)
                    
                    if new_cn != old_cn:
                        logger.info(f"[ОНОВЛЕННЯ] {name} ({appid}): {old_cn} -> {new_cn}")
                        
                        if appid == 1422450:
                            version_key = f"{appid_str}_version"
                            old_ver = state.get(version_key, "unknown")
                            
                            # Робимо 5 швидких спроб перевірити GitHub (з інтервалом 15 сек)
                            new_ver = old_ver
                            for attempt in range(5):
                                temp_ver = get_deadlock_version_from_github()
                                if temp_ver and temp_ver != old_ver:
                                    new_ver = temp_ver
                                    logger.info(f"Знайдено нову версію на GitHub: {new_ver} (спроба {attempt+1})")
                                    break
                                time.sleep(15)
                                
                            if new_ver != old_ver:
                                # Версія оновилася одразу!
                                send_telegram_notification(
                                    name, appid, old_cn, new_cn,
                                    old_ver=old_ver, new_ver=new_ver, ver_updated=1
                                )
                                state[appid_str] = new_cn
                                state[version_key] = new_ver
                                save_state(state)
                            else:
                                # Версія ще не оновилася. Відкладаємо повідомлення на 5 хвилин
                                logger.info("Версія на GitHub ще не змінилася. Створюємо відкладену перевірку...")
                                state[pending_key] = {
                                    "old_cn": old_cn,
                                    "new_cn": new_cn,
                                    "timestamp": time.time(),
                                    "old_ver": old_ver
                                }
                                save_state(state)
                        elif appid == 3488080:
                            version_key = f"{appid_str}_version"
                            old_ver = state.get(version_key, "1926")
                            try:
                                old_ver_int = int(old_ver)
                                new_ver = str(old_ver_int + 1)
                            except ValueError:
                                new_ver = "1927"
                            
                            send_telegram_notification(
                                name, appid, old_cn, new_cn,
                                old_ver=old_ver, new_ver=new_ver, ver_updated=1
                            )
                            state[appid_str] = new_cn
                            state[version_key] = new_ver
                            save_state(state)
                    else:
                        logger.debug(f"Без змін для {name} ({appid}): CN {old_cn}")
                        
                except Exception as e:
                    logger.error(f"Помилка при перевірці AppID {appid} ({name}): {e}")
                    # Не падаємо, переходимо до наступного додатка
                
                # Невелика затримка між перевіркою окремих AppID
                time.sleep(2)
                
            logger.info(f"Перевірку завершено. Засинаємо на {CHECK_INTERVAL} сек...")
            time.sleep(CHECK_INTERVAL)
            
    except KeyboardInterrupt:
        logger.info("Бот зупинений користувачем (KeyboardInterrupt).")
    except Exception as e:
        logger.critical(f"Критична помилка в роботі бота: {e}")
        logger.critical(traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    main()
