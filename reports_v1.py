#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Yandex Direct Reports API — Чтение статистики (v1)
Для: Влада (бумажные пакеты, Москва)

Reports API отличается от основного API:
- Асинхронный: отправляем запрос, ждём, скачиваем результат
- HTTP 200 — отчёт готов (данные в теле ответа, формат TSV)
- HTTP 201 — отчёт создаётся, повторить через retryIn секунд
- HTTP 202 — отчёт в очереди, повторить через retryIn секунд
"""

import requests
import json
import logging
import time
import csv
import io
from datetime import datetime, timedelta
from pathlib import Path

# ============================================================================
# ЛОГИРОВАНИЕ
# ============================================================================

LOG_DIR = Path('logs')
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / f"reports_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ============================================================================
# НАСТРОЙКИ
# ============================================================================

TOKEN = 'y0__xDB-O3LAhj04z4goe2H2hb7BdqiFzzob_KzE3qjBKWqWppmXQ'
REPORTS_URL = 'https://api.direct.yandex.com/json/v5/reports'

HEADERS = {
    'Authorization': f'Bearer {TOKEN}',
    'Accept-Language': 'ru',
    'returnMoneyInMicros': 'false',   # деньги в рублях, не в микрорублях
    'skipReportHeader': 'true',       # убрать заголовок с названием отчёта
    'skipReportSummary': 'true',      # убрать итоговую строку
}

MAX_RETRIES = 10      # максимум попыток получить отчёт
RETRY_DELAY = 5       # секунд между попытками если сервер не указал своё время


# ============================================================================
# ПОЛУЧЕНИЕ ОТЧЁТА
# ============================================================================

def get_report(report_name: str, fields: list, date_range: str = 'LAST_30_DAYS',
               date_from: str = None, date_to: str = None,
               campaign_ids: list = None) -> str | None:
    """
    Запрашивает отчёт и ждёт его готовности.
    Возвращает TSV-строку с данными или None при ошибке.
    """
    logger.info("=" * 80)
    logger.info(f"📊 Запрос отчёта: {report_name}")
    logger.info("=" * 80)

    # Формируем критерии выборки
    selection_criteria = {}
    if date_range == "CUSTOM_DATE" and date_from and date_to:
        selection_criteria["DateFrom"] = date_from
        selection_criteria["DateTo"] = date_to
    if campaign_ids:
        selection_criteria["Filter"] = [
            {"Field": "CampaignId", "Operator": "IN", "Values": [str(cid) for cid in campaign_ids]}
        ]

    request_body = {
        "params": {
            "SelectionCriteria": selection_criteria,
            "FieldNames": fields,
            "ReportName": report_name,
            "ReportType": "CAMPAIGN_PERFORMANCE_REPORT",
            "DateRangeType": date_range,
            "Format": "TSV",
            "IncludeVAT": "NO",
            "IncludeDiscount": "NO"
        }
    }

    logger.info(f"\n📦 Тело запроса:\n{json.dumps(request_body, indent=2, ensure_ascii=False)}")

    for attempt in range(1, MAX_RETRIES + 1):
        logger.info(f"\n🔄 Попытка {attempt}/{MAX_RETRIES}...")

        try:
            response = requests.post(
                REPORTS_URL,
                headers=HEADERS,
                json=request_body,
                timeout=60
            )
        except Exception as e:
            logger.error(f"❌ Ошибка соединения: {e}")
            return None

        logger.info(f"HTTP статус: {response.status_code}")

        if response.status_code == 200:
            logger.info("✅ Отчёт готов!")
            logger.info(f"\n📄 Данные ({len(response.text)} символов):\n{response.text}")
            return response.text

        elif response.status_code in (201, 202):
            retry_in = int(response.headers.get('retryIn', RETRY_DELAY))
            status_msg = "создаётся" if response.status_code == 201 else "в очереди"
            logger.info(f"⏳ Отчёт {status_msg}. Жду {retry_in} сек...")
            time.sleep(retry_in)

        elif response.status_code == 400:
            logger.error(f"❌ Ошибка запроса (400):\n{response.text}")
            return None

        elif response.status_code == 401:
            logger.error("❌ Ошибка авторизации (401). Проверь токен.")
            return None

        else:
            logger.error(f"❌ Неожиданный статус {response.status_code}:\n{response.text}")
            return None

    logger.error(f"❌ Отчёт не готов после {MAX_RETRIES} попыток")
    return None


# ============================================================================
# ПАРСИНГ TSV
# ============================================================================

def parse_tsv(tsv_data: str) -> list[dict]:
    """Парсит TSV-ответ в список словарей."""
    reader = csv.DictReader(io.StringIO(tsv_data), delimiter='\t')
    rows = list(reader)
    logger.info(f"\n📋 Распарсено строк: {len(rows)}")
    return rows


def print_report(rows: list[dict], title: str):
    """Красиво выводит отчёт в лог."""
    logger.info("\n" + "=" * 80)
    logger.info(f"📈 {title}")
    logger.info("=" * 80)

    if not rows:
        logger.info("Нет данных за выбранный период.")
        return

    for row in rows:
        logger.info("-" * 40)
        for key, value in row.items():
            logger.info(f"  {key}: {value}")

    logger.info("=" * 80)


# ============================================================================
# ОСНОВНОЙ БЛОК
# ============================================================================

def main():
    logger.info("=" * 80)
    logger.info("📊 Yandex Direct Reports API v1")
    logger.info(f"Лог файл: {LOG_FILE.absolute()}")
    logger.info("=" * 80)

    # --- Отчёт: Статистика за последнюю неделю ---
    tsv = get_report(
        report_name=f"Статистика за неделю {datetime.now().strftime('%Y-%m-%d')}",
        fields=[
            "CampaignName",
            "Impressions",    # показы
            "Clicks",         # клики
            "Ctr",            # CTR (%)
            "AvgCpc",         # средняя цена клика
            "Cost",           # расход
        ],
        date_range="LAST_7_DAYS"
    )

    if tsv:
        rows = parse_tsv(tsv)
        print_report(rows, "Статистика кампаний за 30 дней")

        # Краткое резюме
        logger.info("\n📌 РЕЗЮМЕ:")
        total_clicks = sum(int(r.get('Clicks', 0)) for r in rows)
        total_cost = sum(float(r.get('Cost', 0)) for r in rows)
        total_impressions = sum(int(r.get('Impressions', 0)) for r in rows)
        logger.info(f"  Показов всего:  {total_impressions:,}")
        logger.info(f"  Кликов всего:   {total_clicks:,}")
        logger.info(f"  Расход всего:   {total_cost:.2f} руб.")
        if total_clicks > 0:
            logger.info(f"  Средний CPC:    {total_cost / total_clicks:.2f} руб.")
    else:
        logger.warning("⚠️ Не удалось получить отчёт. Возможно, кампании ещё не набрали статистику.")

    logger.info("\n" + "=" * 80)
    logger.info("✅ РАБОТА ЗАВЕРШЕНА")
    logger.info(f"Лог: {LOG_FILE.absolute()}")
    logger.info("=" * 80)


if __name__ == '__main__':
    main()
