#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Менеджер бюджетов — Яндекс Директ
Перераспределяет суммарный бюджет между кампаниями на основе эффективности.

Метрика: score = CTR / CPC (высокий CTR + низкий CPC = лучше)
Суммарный бюджет (TOTAL_BUDGET) не меняется — меняется только доля каждой кампании.

Запуск:
    python budget_manager.py           # dry-run (только показывает решения)
    python budget_manager.py --apply   # реально меняет бюджеты

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

# ID наших кампаний
OUR_CAMPAIGN_IDS = {708112800, 708112806, 708112808}

# Бюджет
TOTAL_BUDGET = 3000       # руб/нед суммарно по всем кампаниям
MIN_BUDGET   = 500       # руб/нед минимум на кампанию
MAX_BUDGET   = 2000      # руб/нед максимум на кампанию

# Округление: до ближайшего кратного
ROUND_TO = 100  # руб

# ============================================================================
# ЛОГИРОВАНИЕ
# ============================================================================

LOG_DIR = Path('logs')
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / f"budget_manager_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

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
# DIRECT API: ПОЛУЧИТЬ ТЕКУЩИЕ СТАВКИ/БЮДЖЕТЫ КАМПАНИЙ
# ============================================================================

def get_campaigns() -> dict:
    """Возвращает {campaign_id: {'name': str, 'bid': микруб, 'weekly_limit': микруб}}"""
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
                'bid': avg_cpc['AverageCpc'],
                'weekly_limit': avg_cpc.get('WeeklySpendLimit'),
            }
    return result


# ============================================================================
# REPORTS API: СТАТИСТИКА ЗА НЕДЕЛЮ
# ============================================================================

def get_stats() -> dict:
    """Возвращает {campaign_id: {'name', 'impressions', 'clicks', 'ctr', 'cpc', 'cost'}}"""
    body = {
        "params": {
            "SelectionCriteria": {},
            "FieldNames": ["CampaignId", "CampaignName", "Impressions", "Clicks", "Ctr", "AvgCpc", "Cost"],
            "ReportName": f"BudgetManager {datetime.now().strftime('%Y-%m-%d %H:%M')}",
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
# ЛОГИКА ПЕРЕРАСПРЕДЕЛЕНИЯ БЮДЖЕТА
# ============================================================================

def calc_score(s: dict) -> float:
    """
    Эффективность кампании: CTR / CPC.
    Если кампания ещё не набрала статистику (0 показов / 0 CPC) — базовый score 0.5
    чтобы она получила хотя бы минимальный бюджет, не ноль.
    """
    if s['impressions'] == 0 or s['cpc'] == 0:
        return 0.5
    return s['ctr'] / s['cpc']


def round_to(value: float, step: int) -> int:
    """Округляет до кратного step."""
    return int(round(value / step) * step)


def redistribute(campaigns: dict, stats: dict) -> list:
    """
    Рассчитывает новый бюджет для каждой кампании.
    Возвращает список словарей с решениями.
    """
    # Считаем score для каждой кампании
    scored = []
    for cid, campaign in campaigns.items():
        s = stats.get(cid)
        if s is None:
            logger.warning(f"Нет статистики для [{cid}] {campaign['name']} — используем базовый score 0.5")
            s = {'name': campaign['name'], 'impressions': 0, 'clicks': 0, 'ctr': 0.0, 'cpc': 0.0, 'cost': 0.0}
        score = calc_score(s)
        scored.append({'id': cid, 'campaign': campaign, 'stats': s, 'score': score})

    total_score = sum(x['score'] for x in scored)

    # Пропорциональное распределение с лимитами
    # Итерируем несколько раз: кампании, упёршиеся в лимит, фиксируем,
    # остаток перераспределяем среди оставшихся.
    remaining_budget = TOTAL_BUDGET
    remaining_items = list(scored)
    budgets = {}

    for _ in range(len(scored) + 1):
        if not remaining_items:
            break
        score_sum = sum(x['score'] for x in remaining_items)
        if score_sum == 0:
            # Все score нулевые — делим поровну
            for x in remaining_items:
                x['score'] = 1.0
            score_sum = len(remaining_items)

        fixed_this_round = []
        for x in remaining_items:
            raw = remaining_budget * (x['score'] / score_sum)
            rounded = round_to(raw, ROUND_TO)
            clamped = max(MIN_BUDGET, min(MAX_BUDGET, rounded))
            if clamped != rounded:  # упёрлись в лимит
                budgets[x['id']] = clamped
                fixed_this_round.append(x)

        if not fixed_this_round:
            # Все вписались в лимиты — назначаем итоговые значения
            for x in remaining_items:
                raw = remaining_budget * (x['score'] / score_sum)
                rounded = round_to(raw, ROUND_TO)
                budgets[x['id']] = max(MIN_BUDGET, min(MAX_BUDGET, rounded))
            break

        remaining_budget -= sum(budgets[x['id']] for x in fixed_this_round)
        remaining_items = [x for x in remaining_items if x['id'] not in budgets]

    # Корректируем округление: разница суммы и TOTAL_BUDGET
    # Отдаём лидеру (с наибольшим score)
    total_assigned = sum(budgets.values())
    diff = TOTAL_BUDGET - total_assigned
    if diff != 0:
        leader_id = max(scored, key=lambda x: x['score'])['id']
        budgets[leader_id] = max(MIN_BUDGET, min(MAX_BUDGET, budgets[leader_id] + diff))

    # Формируем результат
    decisions = []
    for x in scored:
        cid = x['id']
        current_limit_micros = x['campaign']['weekly_limit']
        current_rub = (current_limit_micros or 0) / 1_000_000
        new_rub = budgets[cid]
        decisions.append({
            'id': cid,
            'name': x['campaign']['name'],
            'bid': x['campaign']['bid'],
            'stats': x['stats'],
            'score': x['score'],
            'current_budget': current_rub,
            'new_budget': new_rub,
            'new_budget_micros': new_rub * 1_000_000,
            'changed': abs(new_rub - current_rub) >= ROUND_TO,
        })

    return decisions


# ============================================================================
# DIRECT API: ОБНОВИТЬ БЮДЖЕТ КАМПАНИИ
# ============================================================================

def update_budget(campaign_id: int, bid_micros: int, new_weekly_limit_micros: int) -> bool:
    """Обновляет WeeklySpendLimit кампании, сохраняя текущую AverageCpc ставку."""
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
                                "AverageCpc": bid_micros,
                                "WeeklySpendLimit": int(new_weekly_limit_micros),
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
    logger.info("📦 Менеджер бюджетов — Яндекс Директ")
    logger.info(f"Режим: {'DRY-RUN (без изменений)' if dry_run else '⚡ APPLY (меняем бюджеты)'}")
    logger.info(f"Суммарный бюджет: {TOTAL_BUDGET} руб/нед | Лимиты: {MIN_BUDGET}–{MAX_BUDGET} руб")
    logger.info("=" * 60)

    # 1. Текущие кампании (ставки + бюджеты)
    logger.info("Получаю кампании...")
    campaigns = get_campaigns()
    if not campaigns:
        logger.error("Не удалось получить кампании.")
        return

    for cid, c in campaigns.items():
        limit_rub = (c['weekly_limit'] or 0) / 1_000_000
        logger.info(f"  [{cid}] {c['name']}: ставка {c['bid'] / 1_000_000:.0f}₽, бюджет {limit_rub:.0f}₽/нед")

    # 2. Статистика за неделю
    logger.info("\nПолучаю статистику за 7 дней...")
    stats = get_stats()
    if not stats:
        logger.error("Не удалось получить статистику.")
        return

    # 3. Расчёт нового распределения
    decisions = redistribute(campaigns, stats)

    # 4. Лог решений
    logger.info("\n" + "=" * 60)
    logger.info("📊 РАСПРЕДЕЛЕНИЕ БЮДЖЕТА:")
    logger.info("=" * 60)
    for d in decisions:
        s = d['stats']
        logger.info(f"\n{d['name']}")
        logger.info(f"  Показы: {s['impressions']}  Клики: {s['clicks']}  CTR: {s['ctr']:.1f}%  CPC: {s['cpc']:.0f}₽  Расход: {s['cost']:.0f}₽")
        logger.info(f"  Score: {d['score']:.4f}")
        if d['changed']:
            logger.info(f"  Бюджет: {d['current_budget']:.0f}₽ → {d['new_budget']:.0f}₽/нед")
        else:
            logger.info(f"  Бюджет: {d['current_budget']:.0f}₽/нед (без изменений)")

    total_new = sum(d['new_budget'] for d in decisions)
    logger.info(f"\nИтого: {total_new} руб/нед (из {TOTAL_BUDGET})")

    # 5. Применяем (если не dry-run)
    if not dry_run:
        logger.info("\n⚡ Применяю изменения...")
        for d in decisions:
            if d['changed']:
                ok = update_budget(d['id'], d['bid'], d['new_budget_micros'])
                status = '✅' if ok else '❌'
                logger.info(f"  {status} {d['name']}: {d['current_budget']:.0f}₽ → {d['new_budget']:.0f}₽/нед")
    else:
        logger.info("\n⏭ Dry-run — ничего не меняю. Запусти с --apply чтобы применить.")

    # 6. Telegram
    mode_label = '🔍 Dry-run' if dry_run else '⚡ Применено'
    date_str = datetime.now().strftime('%d.%m.%Y %H:%M')
    lines = [f"📦 *Менеджер бюджетов* — {date_str}", f"_{mode_label}_", f"_Пул: {TOTAL_BUDGET}₽/нед_", ""]

    for d in decisions:
        s = d['stats']
        short_name = d['name'].replace('B2B — ', '')
        if d['changed']:
            budget_str = f"{d['current_budget']:.0f}₽ → *{d['new_budget']:.0f}₽*/нед"
        else:
            budget_str = f"{d['new_budget']:.0f}₽/нед (без изменений)"
        lines.append(f"*{short_name}*")
        lines.append(f"  CTR {s['ctr']:.1f}% | CPC {s['cpc']:.0f}₽ | score {d['score']:.3f}")
        lines.append(f"  {budget_str}")
        lines.append("")

    send_telegram('\n'.join(lines))
    logger.info("\n✅ Готово.")


if __name__ == '__main__':
    main()
