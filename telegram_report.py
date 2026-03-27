#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Яндекс Директ → Telegram отчёт
Запускать вручную или по расписанию (Windows Task Scheduler / cron).

Переменные окружения:
    TELEGRAM_BOT_TOKEN — токен бота
    TELEGRAM_CHAT_ID   — id чата (через запятую для нескольких)

Запуск:
    python telegram_report.py
"""

import csv
import io
import json
import logging
import os
import time
import urllib.request
import urllib.parse
from datetime import datetime
from pathlib import Path

# ============================================================================
# НАСТРОЙКИ
# ============================================================================

DIRECT_TOKEN = 'y0__xDB-O3LAhj04z4goe2H2hb7BdqiFzzob_KzE3qjBKWqWppmXQ'
REPORTS_URL = 'https://api.direct.yandex.com/json/v5/reports'

DIRECT_HEADERS = {
    'Authorization': f'Bearer {DIRECT_TOKEN}',
    'Accept-Language': 'ru',
    'returnMoneyInMicros': 'false',
    'skipReportHeader': 'true',
    'skipReportSummary': 'true',
}

LOG_DIR = Path('logs')
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / f"tg_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


# ============================================================================
# DIRECT API: ПОЛУЧЕНИЕ СТАТИСТИКИ
# ============================================================================

def fetch_stats(date_range: str = 'LAST_7_DAYS') -> list[dict] | None:
    """Запрашивает статистику кампаний, возвращает список строк или None."""
    import requests

    body = {
        "params": {
            "SelectionCriteria": {},
            "FieldNames": ["CampaignName", "Impressions", "Clicks", "Ctr", "AvgCpc", "Cost"],
            "ReportName": f"TG отчёт {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            "ReportType": "CAMPAIGN_PERFORMANCE_REPORT",
            "DateRangeType": date_range,
            "Format": "TSV",
            "IncludeVAT": "NO",
            "IncludeDiscount": "NO"
        }
    }

    for attempt in range(1, 11):
        logger.info(f"Попытка {attempt}/10...")
        try:
            resp = requests.post(REPORTS_URL, headers=DIRECT_HEADERS, json=body, timeout=60)
        except Exception as e:
            logger.error(f"Ошибка соединения: {e}")
            return None

        if resp.status_code == 200:
            logger.info("Отчёт получен.")
            reader = csv.DictReader(io.StringIO(resp.text), delimiter='\t')
            return list(reader)

        elif resp.status_code in (201, 202):
            wait = int(resp.headers.get('retryIn', 5))
            logger.info(f"Отчёт формируется, жду {wait} сек...")
            time.sleep(wait)

        else:
            logger.error(f"Ошибка {resp.status_code}: {resp.text}")
            return None

    logger.error("Отчёт не готов после 10 попыток.")
    return None


# ============================================================================
# ФОРМАТИРОВАНИЕ СООБЩЕНИЯ
# ============================================================================

# Короткие имена кампаний для Telegram
CAMPAIGN_SHORT = {
    'B2B — Магазины и ритейл':      'Магазины',
    'B2B — Рестораны и кафе':       'Рестораны',
    'B2B — Брендированные пакеты':  'Брендированные',
}

PERIOD_LABELS = {
    'LAST_7_DAYS':  'за 7 дней',
    'LAST_30_DAYS': 'за 30 дней',
    'TODAY':        'сегодня',
    'YESTERDAY':    'вчера',
}


def format_message(rows: list[dict], date_range: str) -> str:
    period = PERIOD_LABELS.get(date_range, date_range)
    date_str = datetime.now().strftime('%d.%m.%Y')

    total_imp = sum(int(r.get('Impressions', 0)) for r in rows)
    total_clicks = sum(int(r.get('Clicks', 0)) for r in rows)
    total_cost = sum(float(r.get('Cost', 0)) for r in rows)
    avg_cpc = total_cost / total_clicks if total_clicks else 0
    avg_ctr = (total_clicks / total_imp * 100) if total_imp else 0

    lines = [
        f"📊 *Яндекс Директ* — {period}",
        f"📅 {date_str}",
        "",
    ]

    for r in rows:
        name = CAMPAIGN_SHORT.get(r['CampaignName'], r['CampaignName'])
        imp = int(r.get('Impressions', 0))
        clicks = int(r.get('Clicks', 0))
        ctr = float(r.get('Ctr', 0))
        cpc = float(r.get('AvgCpc', 0))
        cost = float(r.get('Cost', 0))

        lines += [
            f"*{name}*",
            f"  👁 {imp:,}  🖱 {clicks}  CTR {ctr:.1f}%",
            f"  CPC {cpc:.0f}₽  |  расход {cost:.0f}₽",
            "",
        ]

    lines += [
        "─────────────────",
        f"*Итого {period}:*",
        f"  👁 {total_imp:,}  🖱 {total_clicks}  CTR {avg_ctr:.1f}%",
        f"  CPC {avg_cpc:.0f}₽  |  расход {total_cost:.0f}₽",
    ]

    return '\n'.join(lines)


# ============================================================================
# ОТПРАВКА В TELEGRAM
# ============================================================================

def send_telegram(text: str) -> None:
    token = os.environ['TELEGRAM_BOT_TOKEN']
    chat_id = os.environ['TELEGRAM_CHAT_ID']
    chat_ids = [cid.strip() for cid in chat_id.split(',') if cid.strip()]

    url = f'https://api.telegram.org/bot{token}/sendMessage'
    for cid in chat_ids:
        data = json.dumps({
            'chat_id': cid,
            'text': text,
            'parse_mode': 'Markdown'
        }).encode('utf-8')
        req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
        if not result.get('ok'):
            raise RuntimeError(f"Telegram error: {result}")
        logger.info(f"Отчёт отправлен в чат {cid}")


# ============================================================================
# MAIN
# ============================================================================

def main():
    logger.info("=" * 60)
    logger.info("📊 Telegram отчёт — Яндекс Директ")
    logger.info("=" * 60)

    # Проверка env-переменных
    if not os.environ.get('TELEGRAM_BOT_TOKEN') or not os.environ.get('TELEGRAM_CHAT_ID'):
        logger.error("❌ Нет TELEGRAM_BOT_TOKEN или TELEGRAM_CHAT_ID в переменных окружения.")
        logger.error("   Установи: set TELEGRAM_BOT_TOKEN=... && set TELEGRAM_CHAT_ID=...")
        return

    date_range = 'LAST_7_DAYS'  # Можно менять: LAST_30_DAYS, TODAY, YESTERDAY

    rows = fetch_stats(date_range)
    if not rows:
        logger.error("❌ Не удалось получить статистику.")
        return

    message = format_message(rows, date_range)
    logger.info(f"\nСообщение:\n{message}\n")

    send_telegram(message)
    logger.info("✅ Готово.")


if __name__ == '__main__':
    main()
