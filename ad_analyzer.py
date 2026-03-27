#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ad Analyzer — Яндекс Директ
Сравнивает объявления внутри каждой кампании по CTR.

Запуск:
    python ad_analyzer.py

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
API_URL = 'https://api.direct.yandex.com/json/v5'
REPORTS_URL = 'https://api.direct.yandex.com/json/v5/reports'

HEADERS = {
    'Authorization': f'Bearer {TOKEN}',
    'Accept-Language': 'ru',
    'Content-Type': 'application/json',
}
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

MIN_IMPRESSIONS = 10   # меньше — "мало данных"


# ============================================================================
# ШАГ 1: СТАТИСТИКА ПО ОБЪЯВЛЕНИЯМ
# ============================================================================

def fetch_ad_stats() -> dict | None:
    """
    Возвращает {ad_id: {campaign_id, campaign_name, impressions, clicks, ctr, cpc, cost}}
    за LAST_7_DAYS или None при ошибке.
    """
    body = {
        "params": {
            "SelectionCriteria": {},
            "FieldNames": ["AdId", "CampaignId", "CampaignName", "Impressions", "Clicks", "Ctr", "AvgCpc", "Cost"],
            "ReportName": f"Ads {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            "ReportType": "AD_PERFORMANCE_REPORT",
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
            result = {}
            for row in reader:
                cid = int(row['CampaignId'])
                if cid not in OUR_CAMPAIGN_IDS:
                    continue
                def safe_float(val):
                    return float(val) if val != '--' else 0.0
                aid = int(row['AdId'])
                result[aid] = {
                    'campaign_id':   cid,
                    'campaign_name': row['CampaignName'],
                    'impressions':   int(row['Impressions']),
                    'clicks':        int(row['Clicks']),
                    'ctr':           safe_float(row['Ctr']),
                    'cpc':           safe_float(row['AvgCpc']),
                    'cost':          safe_float(row['Cost']),
                }
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
# ШАГ 2: ТЕКСТЫ ОБЪЯВЛЕНИЙ
# ============================================================================

def fetch_ad_creatives(ad_ids: list[int]) -> dict:
    """
    Возвращает {ad_id: {title, title2, text}} через ads.get.
    Поля могут отсутствовать — подставляем пустую строку.
    """
    resp = requests.post(f'{API_URL}/ads', headers=HEADERS, json={
        "method": "get",
        "params": {
            "SelectionCriteria": {"Ids": ad_ids},
            "FieldNames": ["Id", "CampaignId"],
            "TextAdFieldNames": ["Title", "Title2", "Text"],
        }
    }, timeout=30)

    data = resp.json()
    if 'error' in data:
        print(f"  ошибка ads.get: {data['error']}")
        return {}

    result = {}
    for ad in data.get('result', {}).get('Ads', []):
        text_ad = ad.get('TextAd', {})
        result[ad['Id']] = {
            'title':  text_ad.get('Title', ''),
            'title2': text_ad.get('Title2', ''),
            'text':   text_ad.get('Text', ''),
        }
    return result


# ============================================================================
# АНАЛИЗ
# ============================================================================

def analyze(stats: dict, creatives: dict) -> dict:
    """
    Объединяет статистику с текстами, группирует по кампании,
    сортирует по CTR внутри каждой кампании.
    Возвращает {campaign_name: [ad_dict, ...]}.
    """
    campaigns = {}
    for aid, s in stats.items():
        creative = creatives.get(aid, {})
        ad = {
            'id':          aid,
            'title':       creative.get('title', ''),
            'title2':      creative.get('title2', ''),
            'text':        creative.get('text', ''),
            'impressions': s['impressions'],
            'clicks':      s['clicks'],
            'ctr':         s['ctr'],
            'cpc':         s['cpc'],
            'cost':        s['cost'],
        }
        name = CAMPAIGN_SHORT.get(s['campaign_name'], s['campaign_name'])
        campaigns.setdefault(name, []).append(ad)

    # Сортируем по CTR внутри кампании (лучшие сверху)
    for name in campaigns:
        campaigns[name].sort(key=lambda a: -a['ctr'])

    return campaigns


# ============================================================================
# ФОРМАТИРОВАНИЕ
# ============================================================================

def ad_label(title: str, title2: str, text: str) -> str:
    parts = [p for p in [title, title2] if p]
    headline = ' | '.join(parts) if parts else '(без заголовка)'
    return f"{headline}\n      {text}" if text else headline


def format_report(campaigns: dict) -> str:
    lines = [
        "📣 *Объявления — 7 дней*",
        "",
    ]

    for camp_name, ads in sorted(campaigns.items()):
        total = len(ads)
        lines.append(f"*{camp_name}* ({total} объявл.)")

        enough_data = [a for a in ads if a['impressions'] >= MIN_IMPRESSIONS]
        low_data    = [a for a in ads if a['impressions'] < MIN_IMPRESSIONS]

        for i, ad in enumerate(enough_data):
            if i == 0 and len(enough_data) > 1:
                icon = '🏆'
            elif i == len(enough_data) - 1 and len(enough_data) > 1:
                icon = '💀'
            else:
                icon = '→'

            label = ad_label(ad['title'], ad['title2'], ad['text'])
            lines.append(f"  {icon} {label}")
            lines.append(f"      CTR {ad['ctr']:.1f}%  |  {ad['cpc']:.0f}₽ CPC  |  {ad['clicks']} кликов  |  {ad['impressions']} показов")

        for ad in low_data:
            label = ad_label(ad['title'], ad['title2'], ad['text'])
            lines.append(f"  ⏳ {label}")
            lines.append(f"      мало данных ({ad['impressions']} показов)")

        lines.append("")

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
    print("📣 Ad Analyzer — Яндекс Директ")
    print("=" * 60)

    print("Шаг 1: статистика по объявлениям за 7 дней...")
    stats = fetch_ad_stats()
    if stats is None:
        print("❌ Не удалось получить статистику.")
        sys.exit(1)
    if not stats:
        msg = "⚠️ Объявлений не найдено. Возможно, кампании ещё не набрали статистику."
        print(msg)
        send_telegram(msg)
        return
    print(f"  Найдено объявлений: {len(stats)}")

    print("Шаг 2: тексты объявлений...")
    creatives = fetch_ad_creatives(list(stats.keys()))
    print(f"  Получено текстов: {len(creatives)}")

    campaigns = analyze(stats, creatives)
    report    = format_report(campaigns)

    print("\n" + "=" * 60)
    print(report)
    print("=" * 60)

    send_telegram(report)
    print("\n✅ Готово.")


if __name__ == '__main__':
    main()
