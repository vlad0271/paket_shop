#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Keyword Analyzer — Яндекс Директ
Анализирует ключевые слова: мёртвые, не работают, дорогие, лучшие.

Запуск:
    python keyword_analyzer.py

Переменные окружения:
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID — для уведомлений (опционально)
"""

import csv
import io
import json
import os
import sys
import time
import urllib.request
from datetime import datetime

import requests

# ============================================================================
# НАСТРОЙКИ
# ============================================================================

TOKEN = 'y0__xDB-O3LAhj04z4goe2H2hb7BdqiFzzob_KzE3qjBKWqWppmXQ'
REPORTS_URL = 'https://api.direct.yandex.com/json/v5/reports'

REPORT_HEADERS = {
    'Authorization': f'Bearer {TOKEN}',
    'Accept-Language': 'ru',
    'returnMoneyInMicros': 'false',
    'skipReportHeader': 'true',
    'skipReportSummary': 'true',
}

OUR_CAMPAIGN_IDS = {708112800, 708112806, 708112808}

CAMPAIGN_SHORT = {
    'B2B — Магазины и ритейл':     'Магазины',
    'B2B — Рестораны и кафе':      'Рестораны',
    'B2B — Брендированные пакеты': 'Брендированные',
}

# Пороги
MIN_IMPRESSIONS_FOR_BAD = 50   # показов — считаем ключ нерабочим
CPC_EXPENSIVE = 35.0           # ₽ — считаем ключ дорогим
CTR_GOOD = 5.0                 # % — считаем ключ лучшим
CPC_GOOD = 30.0                # ₽ — считаем ключ лучшим


# ============================================================================
# REPORTS API
# ============================================================================

def fetch_keyword_stats() -> list[dict] | None:
    """
    Возвращает список ключевых слов со статистикой за LAST_7_DAYS или None.
    """
    body = {
        "params": {
            "SelectionCriteria": {},
            "FieldNames": [
                "CampaignId", "CampaignName",
                "Criterion", "CriterionId",
                "Impressions", "Clicks", "Ctr", "AvgCpc", "Cost",
            ],
            "ReportName": f"Keywords {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            "ReportType": "CRITERIA_PERFORMANCE_REPORT",
            "DateRangeType": "LAST_7_DAYS",
            "Format": "TSV",
            "IncludeVAT": "NO",
            "IncludeDiscount": "NO",
        }
    }

    for attempt in range(1, 11):
        resp = requests.post(REPORTS_URL, headers=REPORT_HEADERS, json=body, timeout=60)
        if resp.status_code == 200:
            reader = csv.DictReader(io.StringIO(resp.text), delimiter='\t')
            result = []
            for row in reader:
                cid = int(row['CampaignId'])
                if cid not in OUR_CAMPAIGN_IDS:
                    continue
                def safe_float(val):
                    return float(val) if val != '--' else 0.0

                result.append({
                    'campaign_id':   cid,
                    'campaign_name': row['CampaignName'],
                    'keyword':       row['Criterion'],
                    'keyword_id':    row['CriterionId'],
                    'impressions':   int(row['Impressions']),
                    'clicks':        int(row['Clicks']),
                    'ctr':           safe_float(row['Ctr']),
                    'cpc':           safe_float(row['AvgCpc']),
                    'cost':          safe_float(row['Cost']),
                })
            return result
        elif resp.status_code in (201, 202):
            wait = int(resp.headers.get('retryIn', 5))
            print(f"  отчёт формируется, жду {wait} сек...")
            time.sleep(wait)
        else:
            print(f"  ошибка Reports API {resp.status_code}: {resp.text[:200]}")
            return None

    print("  отчёт не готов после 10 попыток")
    return None


# ============================================================================
# КЛАССИФИКАЦИЯ
# ============================================================================

def classify(keywords: list[dict]) -> dict:
    """
    Возвращает {категория: [ключи]}.
    Один ключ может попасть только в одну категорию (приоритет сверху вниз).
    """
    dead       = []  # 0 показов
    not_working = []  # ≥50 показов, 0 кликов
    expensive  = []  # CPC > 35₽ (хотя бы 1 клик)
    best       = []  # CTR > 5% и CPC < 30₽

    for kw in keywords:
        imp    = kw['impressions']
        clicks = kw['clicks']
        ctr    = kw['ctr']
        cpc    = kw['cpc']

        if imp == 0:
            dead.append(kw)
        elif clicks == 0 and imp >= MIN_IMPRESSIONS_FOR_BAD:
            not_working.append(kw)
        elif clicks > 0 and cpc > CPC_EXPENSIVE:
            expensive.append(kw)
        elif ctr > CTR_GOOD and cpc < CPC_GOOD:
            best.append(kw)

    # Сортировка
    dead.sort(key=lambda k: k['campaign_id'])
    not_working.sort(key=lambda k: -k['impressions'])   # худшие сверху
    expensive.sort(key=lambda k: -k['cpc'])              # дороже сверху
    best.sort(key=lambda k: -k['ctr'])                   # лучшие сверху

    return {
        'dead':        dead,
        'not_working': not_working,
        'expensive':   expensive,
        'best':        best,
    }


# ============================================================================
# ФОРМАТИРОВАНИЕ
# ============================================================================

def group_by_campaign(keywords: list[dict]) -> dict:
    """Группирует список ключей по короткому имени кампании."""
    groups = {}
    for kw in keywords:
        name = CAMPAIGN_SHORT.get(kw['campaign_name'], kw['campaign_name'])
        groups.setdefault(name, []).append(kw)
    return groups


def format_report(classified: dict, total: int, all_keywords: list[dict]) -> str:
    dead        = classified['dead']
    not_working = classified['not_working']
    expensive   = classified['expensive']
    best        = classified['best']

    lines = [
        "🔑 *Ключевые слова — 7 дней*",
        f"Всего ключей: {total}",
        "",
    ]

    # ── Мёртвые ──────────────────────────────────────────────
    if dead:
        lines.append(f"💀 *Мёртвые* (0 показов) — {len(dead)} шт.")
        for name, kws in group_by_campaign(dead).items():
            lines.append(f"  {name}:")
            for kw in kws:
                lines.append(f"    · {kw['keyword']}")
        lines.append("")

    # ── Не работают ──────────────────────────────────────────
    if not_working:
        lines.append(f"❌ *Не работают* (≥{MIN_IMPRESSIONS_FOR_BAD} показов, 0 кликов) — {len(not_working)} шт.")
        for name, kws in group_by_campaign(not_working).items():
            lines.append(f"  {name}:")
            for kw in kws:
                lines.append(f"    · \"{kw['keyword']}\" — {kw['impressions']} показов")
        lines.append("")

    # ── Дорогие ──────────────────────────────────────────────
    if expensive:
        lines.append(f"⚠️ *Дорогие* (CPC > {CPC_EXPENSIVE:.0f}₽) — {len(expensive)} шт.")
        for name, kws in group_by_campaign(expensive).items():
            lines.append(f"  {name}:")
            for kw in kws:
                lines.append(f"    · \"{kw['keyword']}\" — {kw['clicks']} кликов, {kw['cpc']:.0f}₽ CPC")
        lines.append("")

    # ── Лучшие ───────────────────────────────────────────────
    if best:
        lines.append(f"✅ *Лучшие* (CTR > {CTR_GOOD:.0f}%, CPC < {CPC_GOOD:.0f}₽) — {len(best)} шт.")
        for name, kws in group_by_campaign(best).items():
            lines.append(f"  {name}:")
            for kw in kws:
                lines.append(f"    · \"{kw['keyword']}\" — CTR {kw['ctr']:.1f}%, {kw['cpc']:.0f}₽ CPC")
        lines.append("")

    # ── В норме ──────────────────────────────────────────────
    flagged_ids = {kw['keyword_id'] for group in classified.values() for kw in group}
    normal = [kw for kw in all_keywords if kw['keyword_id'] not in flagged_ids]
    if normal:
        lines.append(f"→ *В норме* — {len(normal)} шт.")
        for name, kws in group_by_campaign(normal).items():
            lines.append(f"  {name}:")
            for kw in kws:
                lines.append(f"    · \"{kw['keyword']}\" — {kw['impressions']} пок, {kw['clicks']} кл, CTR {kw['ctr']:.1f}%, {kw['cpc']:.0f}₽")

    return '\n'.join(lines)


# ============================================================================
# TELEGRAM
# ============================================================================

def send_telegram(text: str) -> None:
    bot_token = os.environ.get('TELEGRAM_BOT_TOKEN')
    chat_id   = os.environ.get('TELEGRAM_CHAT_ID')
    if not bot_token or not chat_id:
        print("\n[Telegram не настроен — только вывод в консоль]")
        return

    url = f'https://api.telegram.org/bot{bot_token}/sendMessage'
    for cid in chat_id.split(','):
        cid = cid.strip()
        if not cid:
            continue
        data = json.dumps({'chat_id': cid, 'text': text, 'parse_mode': 'Markdown'}).encode('utf-8')
        req  = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                result = json.loads(r.read())
            if result.get('ok'):
                print(f"Отправлено в Telegram (чат {cid})")
            else:
                print(f"Ошибка Telegram: {result}")
        except Exception as e:
            print(f"Telegram недоступен: {e}")


# ============================================================================
# MAIN
# ============================================================================

def main():
    print("🔑 Keyword Analyzer — Яндекс Директ")
    print("=" * 60)

    print("Получаю статистику по ключевым словам за 7 дней...")
    keywords = fetch_keyword_stats()

    if keywords is None:
        print("❌ Не удалось получить данные.")
        sys.exit(1)

    if not keywords:
        msg = "⚠️ Ключевых слов не найдено. Возможно, кампании ещё не набрали статистику."
        print(msg)
        send_telegram(msg)
        return

    print(f"Получено ключей: {len(keywords)}")

    classified = classify(keywords)
    report     = format_report(classified, total=len(keywords), all_keywords=keywords)

    print("\n" + "=" * 60)
    print(report)
    print("=" * 60)

    send_telegram(report)
    print("\n✅ Готово.")


if __name__ == '__main__':
    main()
