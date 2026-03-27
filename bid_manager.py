#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Менеджер ставок — Яндекс Директ
Читает статистику, применяет правила, обновляет AverageCpc.

Запуск:
    python bid_manager.py           # dry-run (только показывает решения)
    python bid_manager.py --apply   # реально меняет ставки

Переменные окружения:
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID — для уведомлений (опционально)
"""

import csv
import io
import json
import logging
import os
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

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

# ID наших кампаний (только их трогаем)
OUR_CAMPAIGN_IDS = {708112800, 708112806, 708112808}

# Лимиты ставок
BID_MIN = 15    # руб
BID_MAX = 60    # руб

# ============================================================================
# ПРАВИЛА УПРАВЛЕНИЯ СТАВКАМИ
#
# Порядок важен: первое сработавшее правило применяется.
# ============================================================================

RULES = [
    {
        'name': 'Мало показов — поднять ставку',
        'condition': lambda s: s['impressions'] < 300,
        'change': +0.20,
        'reason': f'показов < 300 за неделю',
    },
    {
        'name': 'Высокий CPC — снизить ставку',
        'condition': lambda s: s['cpc'] > 35,
        'change': -0.15,
        'reason': 'CPC > 35 руб',
    },
    {
        'name': 'Низкий CTR — снизить ставку',
        'condition': lambda s: s['ctr'] < 3.0,
        'change': -0.10,
        'reason': 'CTR < 3%',
    },
    {
        'name': 'Хорошая эффективность — масштабировать',
        'condition': lambda s: s['ctr'] > 5.0 and s['cpc'] < 28,
        'change': +0.10,
        'reason': 'CTR > 5% и CPC < 28 руб',
    },
]

# ============================================================================
# ЛОГИРОВАНИЕ
# ============================================================================

LOG_DIR = Path('logs')
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / f"bid_manager_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

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
# DIRECT API: ПОЛУЧИТЬ ТЕКУЩИЕ СТАВКИ КАМПАНИЙ
# ============================================================================

def get_campaigns() -> dict:
    """Возвращает {campaign_id: {'name': ..., 'bid': руб, 'weekly_limit': руб}}"""
    resp = requests.post(f'{API_URL}/campaigns', headers=HEADERS, json={
        "method": "get",
        "params": {
            "SelectionCriteria": {"Ids": list(OUR_CAMPAIGN_IDS)},
            "FieldNames": ["Id", "Name"],
            "TextCampaignFieldNames": ["BiddingStrategy"]
        }
    }, timeout=30)
    data = resp.json()

    if 'error' in data:
        logger.error(f"Ошибка API: {data['error']}")
        return {}

    result = {}
    for c in data['result']['Campaigns']:
        strategy = c['TextCampaign']['BiddingStrategy']['Search']
        if strategy['BiddingStrategyType'] == 'AVERAGE_CPC':
            avg_cpc = strategy['AverageCpc']
            result[c['Id']] = {
                'name': c['Name'],
                'bid': avg_cpc['AverageCpc'],               # руб (returnMoneyInMicros=false не работает здесь)
                'weekly_limit': avg_cpc.get('WeeklySpendLimit'),
            }
    return result


# ============================================================================
# REPORTS API: ПОЛУЧИТЬ СТАТИСТИКУ ЗА НЕДЕЛЮ
# ============================================================================

def get_stats() -> dict:
    """Возвращает {campaign_name: {'impressions': N, 'clicks': N, 'ctr': %, 'cpc': руб, 'cost': руб}}"""
    body = {
        "params": {
            "SelectionCriteria": {},
            "FieldNames": ["CampaignId", "CampaignName", "Impressions", "Clicks", "Ctr", "AvgCpc", "Cost"],
            "ReportName": f"BidManager {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            "ReportType": "CAMPAIGN_PERFORMANCE_REPORT",
            "DateRangeType": "LAST_7_DAYS",
            "Format": "TSV",
            "IncludeVAT": "NO",
            "IncludeDiscount": "NO"
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
                        'name': row['CampaignName'],
                        'impressions': int(row['Impressions']),
                        'clicks': int(row['Clicks']),
                        'ctr': float(row['Ctr']),
                        'cpc': float(row['AvgCpc']),
                        'cost': float(row['Cost']),
                    }
            return result
        elif resp.status_code in (201, 202):
            wait = int(resp.headers.get('retryIn', 5))
            logger.info(f"Отчёт формируется, жду {wait} сек...")
            time.sleep(wait)
        else:
            logger.error(f"Ошибка Reports API {resp.status_code}: {resp.text}")
            return {}

    logger.error("Отчёт не готов после 10 попыток.")
    return {}


# ============================================================================
# ЛОГИКА ПРАВИЛ
# ============================================================================

def apply_rules(stats: dict) -> tuple[float, str]:
    """Возвращает (коэффициент изменения, причина). 0.0 = без изменений."""
    for rule in RULES:
        if rule['condition'](stats):
            return rule['change'], rule['name'] + ' (' + rule['reason'] + ')'
    return 0.0, 'Стабильно — без изменений'


def calc_new_bid(current_bid_micros: int, change: float) -> int:
    """Считает новую ставку в микрорублях с учётом лимитов."""
    current_rub = current_bid_micros / 1_000_000
    new_rub = current_rub * (1 + change)
    new_rub = max(BID_MIN, min(BID_MAX, new_rub))
    return int(round(new_rub) * 1_000_000)


# ============================================================================
# DIRECT API: ОБНОВИТЬ СТАВКУ КАМПАНИИ
# ============================================================================

def update_bid(campaign_id: int, new_bid_micros: int, weekly_limit: int) -> bool:
    """Обновляет AverageCpc кампании. Возвращает True при успехе."""
    resp = requests.post(f'{API_URL}/campaigns', headers=HEADERS, json={
        "method": "update",
        "params": {
            "Campaigns": [{
                "Id": campaign_id,
                "TextCampaign": {
                    "BiddingStrategy": {
                        "Search": {
                            "BiddingStrategyType": "AVERAGE_CPC",
                            "AverageCpc": {
                                "AverageCpc": new_bid_micros,
                                "WeeklySpendLimit": weekly_limit,
                            }
                        },
                        "Network": {
                            "BiddingStrategyType": "SERVING_OFF"
                        }
                    }
                }
            }]
        }
    }, timeout=30)

    data = resp.json()
    if 'error' in data:
        logger.error(f"Ошибка обновления кампании {campaign_id}: {data['error']}")
        return False

    errors = data.get('result', {}).get('UpdateResults', [{}])[0].get('Errors', [])
    if errors:
        logger.error(f"Ошибка обновления кампании {campaign_id}: {errors}")
        return False

    return True


# ============================================================================
# TELEGRAM
# ============================================================================

def send_telegram(text: str) -> None:
    bot_token = os.environ.get('TELEGRAM_BOT_TOKEN')
    chat_id = os.environ.get('TELEGRAM_CHAT_ID')
    if not bot_token or not chat_id:
        return

    url = f'https://api.telegram.org/bot{bot_token}/sendMessage'
    for cid in chat_id.split(','):
        cid = cid.strip()
        if not cid:
            continue
        data = json.dumps({'chat_id': cid, 'text': text, 'parse_mode': 'Markdown'}).encode('utf-8')
        req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                result = json.loads(r.read())
            if not result.get('ok'):
                logger.warning(f"Telegram error: {result}")
        except Exception as e:
            logger.warning(f"Telegram недоступен: {e}")


# ============================================================================
# MAIN
# ============================================================================

def main():
    dry_run = '--apply' not in sys.argv

    logger.info("=" * 60)
    logger.info(f"💰 Менеджер ставок — Яндекс Директ")
    logger.info(f"Режим: {'DRY-RUN (без изменений)' if dry_run else '⚡ APPLY (меняем ставки)'}")
    logger.info("=" * 60)

    # 1. Текущие ставки
    logger.info("Получаю текущие ставки кампаний...")
    campaigns = get_campaigns()
    if not campaigns:
        logger.error("Не удалось получить кампании.")
        return

    for cid, c in campaigns.items():
        logger.info(f"  [{cid}] {c['name']}: {c['bid'] / 1_000_000:.0f} руб")

    # 2. Статистика за неделю
    logger.info("\nПолучаю статистику за 7 дней...")
    stats = get_stats()
    if not stats:
        logger.error("Не удалось получить статистику.")
        return

    # 3. Применяем правила и формируем решения
    decisions = []
    for cid, campaign in campaigns.items():
        if cid not in stats:
            logger.warning(f"Нет статистики для кампании {campaign['name']} — пропускаю")
            continue

        s = stats[cid]
        change, reason = apply_rules(s)
        current_bid = campaign['bid']
        new_bid = calc_new_bid(current_bid, change) if change != 0 else current_bid

        decisions.append({
            'id': cid,
            'name': campaign['name'],
            'weekly_limit': campaign['weekly_limit'],
            'stats': s,
            'current_bid': current_bid,
            'new_bid': new_bid,
            'change': change,
            'reason': reason,
            'changed': new_bid != current_bid,
        })

    # 4. Логируем решения
    logger.info("\n" + "=" * 60)
    logger.info("📋 РЕШЕНИЯ:")
    logger.info("=" * 60)
    for d in decisions:
        s = d['stats']
        logger.info(f"\n{d['name']}")
        logger.info(f"  Показы: {s['impressions']}  Клики: {s['clicks']}  CTR: {s['ctr']:.1f}%  CPC: {s['cpc']:.0f}₽  Расход: {s['cost']:.0f}₽")
        logger.info(f"  Правило: {d['reason']}")
        if d['changed']:
            logger.info(f"  Ставка: {d['current_bid'] / 1_000_000:.0f}₽ → {d['new_bid'] / 1_000_000:.0f}₽  ({'+' if d['change'] > 0 else ''}{d['change']*100:.0f}%)")
        else:
            logger.info(f"  Ставка: {d['current_bid'] / 1_000_000:.0f}₽ (без изменений)")

    # 5. Применяем изменения (если не dry-run)
    applied = []
    if not dry_run:
        logger.info("\n⚡ Применяю изменения...")
        for d in decisions:
            if d['changed']:
                ok = update_bid(d['id'], d['new_bid'], d['weekly_limit'])
                status = '✅' if ok else '❌'
                logger.info(f"  {status} {d['name']}: {d['current_bid'] / 1_000_000:.0f}₽ → {d['new_bid'] / 1_000_000:.0f}₽")
                if ok:
                    applied.append(d)
    else:
        logger.info("\n⏭ Dry-run — ничего не меняю. Запусти с --apply чтобы применить.")

    # 6. Telegram-уведомление
    mode_label = '🔍 Dry-run' if dry_run else '⚡ Применено'
    date_str = datetime.now().strftime('%d.%m.%Y %H:%M')
    lines = [f"💰 *Менеджер ставок* — {date_str}", f"_{mode_label}_", ""]

    for d in decisions:
        s = d['stats']
        arrow = f"{d['current_bid']//1_000_000}₽ → {d['new_bid']//1_000_000}₽" if d['changed'] else f"{d['current_bid']//1_000_000}₽"
        lines.append(f"*{d['name'].replace('B2B — ', '')}*")
        lines.append(f"  CTR {s['ctr']:.1f}% | CPC {s['cpc']:.0f}₽ | расход {s['cost']:.0f}₽")
        lines.append(f"  {arrow} — _{d['reason'].split('(')[0].strip()}_")
        lines.append("")

    send_telegram('\n'.join(lines))

    logger.info("\n✅ Готово.")


if __name__ == '__main__':
    main()
