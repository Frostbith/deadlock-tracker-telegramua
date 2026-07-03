# -*- coding: utf-8 -*-

"""
Скрипт для тестування працездатності бота без сторонніх бібліотек.
Тестує отримання changenumber через SteamCMD API за допомогою urllib, роботу зі станом та форматування часу.
"""

import os
import sys
import unittest
import urllib.request
import json
from unittest.mock import MagicMock, patch

# Встановлюємо тестові змінні в env перед імпортом bot
os.environ["TELEGRAM_BOT_TOKEN"] = "123456789:TestToken"
os.environ["TELEGRAM_CHAT_ID"] = "@TestChannel"

import bot

class TestDeadlockTrackerStandalone(unittest.TestCase):
    
    def test_steamcmd_api_connection(self):
        """Тестує реальне підключення до API SteamCMD за допомогою urllib для AppID 1422450 (Deadlock)."""
        print("\n[TEST] Тестування отримання changenumber для AppID 1422450 (Deadlock)...")
        try:
            cn = bot.get_latest_changenumber(1422450)
            print(f"[SUCCESS] Отримано changenumber: {cn} (тип: {type(cn)})")
            self.assertIsInstance(cn, int)
            self.assertGreater(cn, 0)
        except Exception as e:
            self.fail(f"[FAIL] Не вдалося отримати changenumber через API: {e}")

    def test_format_times(self):
        """Тестує відображення дати, київського та сієтлського часу."""
        date_str, kyiv_time, seattle_time = bot.format_times()
        print(f"\n[TEST] Форматування часу:")
        print(f"Дата:    {date_str}")
        print(f"Київ:    {kyiv_time}")
        print(f"Сієтл:   {seattle_time}")
        
        # Перевіряємо формат дати DD.MM.YYYY
        self.assertEqual(len(date_str), 10)
        self.assertEqual(date_str[2], ".")
        self.assertEqual(date_str[5], ".")
        
        # Перевіряємо формат часу HH:MM
        self.assertEqual(len(kyiv_time), 5)
        self.assertEqual(kyiv_time[2], ":")
        self.assertEqual(len(seattle_time), 5)
        self.assertEqual(seattle_time[2], ":")

    def test_state_saving_and_loading(self):
        """Тестує запис та зчитування стану в last_known.json."""
        print("\n[TEST] Тестування збереження та зчитування стану...")
        test_state = {
            "1422450": 100000,
            "3488080": 200000
        }
        
        # Використовуємо тимчасовий файл для тесту
        with patch('bot.STATE_FILE', bot.BASE_DIR / "last_known_test.json"):
            # Видаляємо тестовий файл, якщо він існує
            if bot.STATE_FILE.exists():
                bot.STATE_FILE.unlink()
                
            # Зберігаємо
            bot.save_state(test_state)
            self.assertTrue(bot.STATE_FILE.exists())
            
            # Завантажуємо
            loaded_state = bot.load_state()
            self.assertEqual(loaded_state, test_state)
            print(f"[SUCCESS] Збережено та зчитано успішно: {loaded_state}")
            
            # Прибираємо тестовий файл
            bot.STATE_FILE.unlink()

    @patch('bot.send_telegram_request')
    def test_telegram_notification_formatting(self, mock_send):
        """Тестує правильність формування повідомлення для Telegram."""
        print("\n[TEST] Тестування формування HTML-повідомлення...")
        
        # Імітуємо успішну відповідь від Telegram API
        mock_send.return_value = {"ok": True, "result": {}}
        
        # 1. Тест для Експериментальної версії (changenumber)
        result1 = bot.send_telegram_notification(
            "Deadlock Experimental", 3488080, 36900000, 36910000
        )
        self.assertTrue(result1)
        args, kwargs = mock_send.call_args
        payload1 = args[0] if args else kwargs.get('payload', {})
        text1 = payload1.get('text', '')
        self.assertIn("Deadlock Experimental", text1)
        self.assertIn("36900000 =&gt; 36910000", text1)
        self.assertNotIn("Оновлено Версій", text1)  # Не повинно бути цього рядка для експериментальної
        
        # 2. Тест для Головної версії (версія клієнта)
        result2 = bot.send_telegram_notification(
            "Deadlock", 1422450, 36900000, 36910000, old_ver="6612", new_ver="6612", ver_updated=0
        )
        self.assertTrue(result2)
        args, kwargs = mock_send.call_args
        payload2 = args[0] if args else kwargs.get('payload', {})
        text2 = payload2.get('text', '')
        self.assertIn("Deadlock", text2)
        self.assertIn("6612 =&gt; 6612", text2)
        self.assertIn("Оновлено Версій: 0", text2)
        
        print("[SUCCESS] Формат повідомлення правильний.")

if __name__ == "__main__":
    unittest.main()
