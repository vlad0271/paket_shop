#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Trend Analyzer — Яндекс Директ
Сравнивает статистику по неделям, выявляет тренды.

Запуск:
    python trend_analyzer.py            # последние 2 завершённые недели
    python trend_analyzer.py --weeks 4  # последние 4 недели

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
from datetime import date, timedelta

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

# ============================================================================
# ВЫЧИСЛЕНИЕ НЕДЕЛЬ
# ============================================================================

def get_completed_weeks(n: int) -> list[tuple[date, date]]:
    """
    Возвращает список (date_from, date_to) для последних N завершённых недель.
    Неделя: понедельник–воскресенье.
    Порядок: от новой к старой.
    """
    today = date.today()
    # weekday(): пн=0 ... вс=6. Сколько дней прошло с последнего воскресенья:
    days_since_sunday = (today.weekday() + 1) % 7
    last_sunday = today - timedelta(days=days_since_sunday) if days_since_sunday else today

    weeks = []
    for i in range(n):
        week_end = last_sunday - timedelta(weeks=i)
        week_start = week_end - timedelta(days=6)
        weeks.append((week_start, week_end))
    return weeks


# ============================================================================
# REPORTS API
# ============================================================================

def fetch_week_stats(date_from: date, date_to: date) -> dict | None:
    """
    Возвращает {campaign_id: {name, impressions, clicks, ctr, cpc, cost}}
    за указанный период или None при ошибке.
    """
    body = {
        "params": {
            "SelectionCriteria": {
                "DateFrom": date_from.strftime('%Y-%m-%d'),
                "DateTo":   date_to.strftime('%Y-%m-%d'),
            },
            "FieldNames": ["CampaignId", "CampaignName", "Impressions", "Clicks", "Ctr", "AvgCpc", "Cost"],
            "ReportName": f"Trends {date_from} {date_to}",
            "ReportType": "CAMPAIGN_PERFORMANCE_REPORT",
            "DateRangeType": "CUSTOM_DATE",
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
                if cid in OUR_CAMPAIGN_IDS:
                    result[cid] = {
                        'name':        row['CampaignName'],
                        'impressions': int(row['Impressions']),
                        'clicks':      int(row['Clicks']),
                        'ctr':         float(row['Ctr']),
                        'cpc':         float(row['AvgCpc']),
                        'cost':        float(row['Cost']),
                    }
            return result
        elif resp.status_code in (201, 202):
            wait = int(resp.headers.get('retryIn', 5))
            print(f"  отчёт формируется, жду {wait} сек...")
            time.sleep(wait)
        else:
            print(f"  ошибка Reports API {resp.status_code}: {resp.text[:200]}")
            return None

    print(f"  отчёт не готов после 10 попыток")
    return None


# ============================================================================
# ФОРМАТИРОВАНИЕ ТРЕНДОВ
# ============================================================================

def pct_change(old: float, new: float) -> float | None:
    if old == 0:
        return None
    return (new - old) / old * 100


def trend_label(pct: float | None, higher_is_better: bool | None = True) -> str:
    """Возвращает строку вида '↑ +12%  ✅' или '→ стабильно'."""
    if pct is None:
        return '—'
    if abs(pct) < 3:
        return '→ стабильно'
    arrow = '↑' if pct > 0 else '↓'
    sign  = '+' if pct > 0 else ''
    num   = f'{sign}{pct:.0f}%'
    if higher_is_better is None:
        return f'{arrow} {num}'
    good = (pct > 0) == higher_is_better
    mark = '✅' if good else '⚠️'
    return f'{arrow} {num}  {mark}'


def format_report(weeks_data: list) -> str:
    """
    weeks_data: [((date_from, date_to), stats_dict), ...] от новой к старой.
    Сравниваем [0] (текущая неделя) с [1] (предыдущая).
    """
    if len(weeks_data) < 2:
        return "⚠️ Мало данных — нужно минимум 2 завершённые недели для анализа трендов."

    (cur_dates, cur_stats)   = weeks_data[0]
    (prev_dates, prev_stats) = weeks_data[1]
    cur_start,  cur_end  = cur_dates
    prev_start, prev_end = prev_dates

    lines = [
        "📈 *Тренды Яндекс Директ*",
        f"Неделя {cur_start.strftime('%d.%m')}–{cur_end.strftime('%d.%m')} "
        f"vs {prev_start.strftime('%d.%m')}–{prev_end.strftime('%d.%m')}",
        "",
    ]

    for cid in sorted(OUR_CAMPAIGN_IDS):
        cur  = cur_stats.get(cid)
        prev = prev_stats.get(cid)
        if not cur and not prev:
            continue

        name = CAMPAIGN_SHORT.get((cur or prev)['name'], (cur or prev)['name'])
        lines.append(f"*{name}*")

        if not prev or not cur:
            lines.append("  нет данных за одну из недель")
            lines.append("")
            continue

        # (метка, старое, новое, higher_is_better, формат)
        metrics = [
            ('Показы', prev['impressions'], cur['impressions'], True,  '{:.0f}'),
            ('Клики',  prev['clicks'],      cur['clicks'],      True,  '{:.0f}'),
            ('CTR',    prev['ctr'],         cur['ctr'],         True,  '{:.1f}%'),
            ('CPC',    prev['cpc'],         cur['cpc'],         False, '{:.0f}₽'),
            ('Расход', prev['cost'],        cur['cost'],        None,  '{:.0f}₽'),
        ]
        for label, old_val, new_val, hib, fmt in metrics:
            pct = pct_change(old_val, new_val)
            lines.append(f"  {label}: {fmt.format(old_val)} → {fmt.format(new_val)}  {trend_label(pct, hib)}")

        lines.append("")

    # Итого по всем кампаниям
    common = set(cur_stats) & set(prev_stats)
    if common:
        def total(stats, key):
            return sum(stats[i][key] for i in common)

        cur_imp  = total(cur_stats,  'impressions')
        prev_imp = total(prev_stats, 'impressions')
        cur_cl   = total(cur_stats,  'clicks')
        prev_cl  = total(prev_stats, 'clicks')
        cur_cost = total(cur_stats,  'cost')
        prev_cost= total(prev_stats, 'cost')

        lines += [
            "─────────────────",
            "*Итого:*",
            f"  Показы:  {prev_imp:,.0f} → {cur_imp:,.0f}  {trend_label(pct_change(prev_imp, cur_imp), True)}",
            f"  Клики:   {prev_cl} → {cur_cl}  {trend_label(pct_change(prev_cl, cur_cl), True)}",
            f"  Расход:  {prev_cost:.0f}₽ → {cur_cost:.0f}₽  {trend_label(pct_change(prev_cost, cur_cost), None)}",
        ]

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
    n_weeks = 2
    args = sys.argv[1:]
    if '--weeks' in args:
        idx = args.index('--weeks')
        if idx + 1 < len(args):
            n_weeks = int(args[idx + 1])

    print(f"📈 Trend Analyzer — последние {n_weeks} завершённых недели")
    print("=" * 60)

    weeks = get_completed_weeks(n_weeks)
    print("Периоды:")
    for i, (wstart, wend) in enumerate(weeks):
        label = " ← анализируемая" if i == 0 else (" ← база" if i == 1 else "")
        print(f"  Нед {i + 1}: {wstart.strftime('%d.%m')}–{wend.strftime('%d.%m')}{label}")
    print()

    weeks_data = []
    for wstart, wend in weeks:
        print(f"Получаю {wstart}–{wend}...")
        stats = fetch_week_stats(wstart, wend)
        if stats is None:
            print("  Пропускаю (ошибка API).")
            continue
        weeks_data.append(((wstart, wend), stats))

    report = format_report(weeks_data)
    print("\n" + "=" * 60)
    print(report)
    print("=" * 60)

    send_telegram(report)
    print("\n✅ Готово.")


if __name__ == '__main__':
    main()
