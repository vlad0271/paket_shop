#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Админ-панель — управление Яндекс Директ через Claude AI
Защищена токеном (ADMIN_TOKEN в env).
"""

import csv
import io
import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import AsyncGenerator

import requests
from openai import OpenAI
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

router = APIRouter(prefix="/admin")

# ============================================================================
# YANDEX DIRECT
# ============================================================================

DIRECT_TOKEN = 'y0__xDB-O3LAhj04z4goe2H2hb7BdqiFzzob_KzE3qjBKWqWppmXQ'
API_URL = 'https://api.direct.yandex.com/json/v5'
REPORTS_URL = 'https://api.direct.yandex.com/json/v5/reports'

D_HEADERS = {
    'Authorization': f'Bearer {DIRECT_TOKEN}',
    'Accept-Language': 'ru',
    'Content-Type': 'application/json',
}
D_REPORT_HEADERS = {
    'Authorization': f'Bearer {DIRECT_TOKEN}',
    'Accept-Language': 'ru',
    'returnMoneyInMicros': 'false',
    'skipReportHeader': 'true',
    'skipReportSummary': 'true',
}

OUR_CAMPAIGN_IDS = [708112800, 708112806, 708112808]
CAMPAIGN_NAMES = {
    708112800: 'B2B — Магазины',
    708112806: 'B2B — Рестораны',
    708112808: 'B2B — Брендированные',
}


# ============================================================================
# ИНСТРУМЕНТЫ (вызываются агентом)
# ============================================================================

def tool_get_campaign_stats(days: int = 7) -> str:
    if days <= 7:
        date_range = "LAST_7_DAYS"
    elif days <= 14:
        date_range = "LAST_14_DAYS"
    else:
        date_range = "LAST_30_DAYS"

    body = {
        "params": {
            "SelectionCriteria": {},
            "FieldNames": ["CampaignId", "CampaignName", "Impressions", "Clicks",
                           "Ctr", "AvgCpc", "Cost"],
            "ReportName": f"Admin {datetime.now().strftime('%Y%m%d%H%M%S')}",
            "ReportType": "CAMPAIGN_PERFORMANCE_REPORT",
            "DateRangeType": date_range,
            "Format": "TSV",
            "IncludeVAT": "NO",
            "IncludeDiscount": "NO"
        }
    }
    for _ in range(10):
        resp = requests.post(REPORTS_URL, headers=D_REPORT_HEADERS, json=body, timeout=60)
        if resp.status_code == 200:
            reader = csv.DictReader(io.StringIO(resp.text), delimiter='\t')
            rows = [r for r in reader if int(r['CampaignId']) in OUR_CAMPAIGN_IDS]
            if not rows:
                return "Нет данных за выбранный период."
            lines = [f"Статистика за {days} дней:\n"]
            for r in rows:
                lines.append(f"[{r['CampaignId']}] {r['CampaignName']}")
                lines.append(
                    f"  Показы: {r['Impressions']}  Клики: {r['Clicks']}  "
                    f"CTR: {r['Ctr']}%  CPC: {r['AvgCpc']}₽  Расход: {r['Cost']}₽"
                )
            return "\n".join(lines)
        elif resp.status_code in (201, 202):
            time.sleep(int(resp.headers.get('retryIn', 5)))
        else:
            return f"Ошибка Reports API {resp.status_code}: {resp.text[:300]}"
    return "Отчёт не готов после 10 попыток."


def tool_get_keywords(campaign_id: int = None) -> str:
    ids = [campaign_id] if campaign_id else OUR_CAMPAIGN_IDS
    resp = requests.post(f'{API_URL}/keywords', headers=D_HEADERS, json={
        "method": "get",
        "params": {
            "SelectionCriteria": {"CampaignIds": ids},
            "FieldNames": ["Id", "Keyword", "Status", "AdGroupId", "CampaignId"],
            "Page": {"Limit": 10000}
        }
    }, timeout=30)
    data = resp.json()
    if 'error' in data:
        return f"Ошибка API: {data['error']}"
    keywords = data.get('result', {}).get('Keywords', [])
    if not keywords:
        return "Ключевых слов не найдено."
    lines = [f"Ключевые слова ({len(keywords)} шт.):\n"]
    for kw in keywords:
        cname = CAMPAIGN_NAMES.get(kw['CampaignId'], kw['CampaignId'])
        lines.append(
            f"ID:{kw['Id']}  \"{kw['Keyword']}\"  "
            f"Группа:{kw['AdGroupId']}  {cname}  [{kw['Status']}]"
        )
    return "\n".join(lines)


def tool_delete_keywords(keyword_ids: list) -> str:
    resp = requests.post(f'{API_URL}/keywords', headers=D_HEADERS, json={
        "method": "delete",
        "params": {"SelectionCriteria": {"Ids": keyword_ids}}
    }, timeout=30)
    data = resp.json()
    if 'error' in data:
        return f"Ошибка API: {data['error']}"
    results = data.get('result', {}).get('DeleteResults', [])
    ok = sum(1 for r in results if not r.get('Errors'))
    bad = [r.get('Errors') for r in results if r.get('Errors')]
    msg = f"Удалено: {ok} из {len(keyword_ids)}."
    if bad:
        msg += f" Ошибки: {bad}"
    return msg


def tool_add_keywords(ad_group_id: int, keywords: list) -> str:
    kw_objects = [{"Keyword": kw, "AdGroupId": ad_group_id} for kw in keywords]
    resp = requests.post(f'{API_URL}/keywords', headers=D_HEADERS, json={
        "method": "add",
        "params": {"Keywords": kw_objects}
    }, timeout=30)
    data = resp.json()
    if 'error' in data:
        return f"Ошибка API: {data['error']}"
    results = data.get('result', {}).get('AddResults', [])
    ok = sum(1 for r in results if r.get('Id'))
    bad = [r.get('Errors') for r in results if r.get('Errors')]
    msg = f"Добавлено: {ok} из {len(keywords)}."
    if bad:
        msg += f" Ошибки: {bad}"
    return msg


def _get_campaign_strategy(campaign_id: int) -> dict:
    resp = requests.post(f'{API_URL}/campaigns', headers=D_HEADERS, json={
        "method": "get",
        "params": {
            "SelectionCriteria": {"Ids": [campaign_id]},
            "FieldNames": ["Id"],
            "TextCampaignFieldNames": ["BiddingStrategy"]
        }
    }, timeout=30)
    data = resp.json()
    if 'error' in data:
        raise RuntimeError(f"Ошибка API: {data['error']}")
    campaigns = data['result']['Campaigns']
    if not campaigns:
        raise RuntimeError(f"Кампания {campaign_id} не найдена")
    return campaigns[0]['TextCampaign']['BiddingStrategy']['Search']['AverageCpc']


def tool_update_bid(campaign_id: int, bid_rub: float) -> str:
    try:
        current = _get_campaign_strategy(campaign_id)
    except RuntimeError as e:
        return str(e)
    resp = requests.post(f'{API_URL}/campaigns', headers=D_HEADERS, json={
        "method": "update",
        "params": {"Campaigns": [{
            "Id": campaign_id,
            "TextCampaign": {"BiddingStrategy": {
                "Search": {
                    "BiddingStrategyType": "AVERAGE_CPC",
                    "AverageCpc": {
                        "AverageCpc": int(bid_rub * 1_000_000),
                        "WeeklySpendLimit": current.get('WeeklySpendLimit', 1500000000)
                    }
                },
                "Network": {"BiddingStrategyType": "SERVING_OFF"}
            }}
        }]}
    }, timeout=30)
    data = resp.json()
    if 'error' in data:
        return f"Ошибка API: {data['error']}"
    errs = data.get('result', {}).get('UpdateResults', [{}])[0].get('Errors', [])
    if errs:
        return f"Ошибка: {errs}"
    cname = CAMPAIGN_NAMES.get(campaign_id, campaign_id)
    return f"✅ Ставка [{cname}] изменена на {bid_rub}₽"


def tool_update_budget(campaign_id: int, budget_rub: float) -> str:
    try:
        current = _get_campaign_strategy(campaign_id)
    except RuntimeError as e:
        return str(e)
    resp = requests.post(f'{API_URL}/campaigns', headers=D_HEADERS, json={
        "method": "update",
        "params": {"Campaigns": [{
            "Id": campaign_id,
            "TextCampaign": {"BiddingStrategy": {
                "Search": {
                    "BiddingStrategyType": "AVERAGE_CPC",
                    "AverageCpc": {
                        "AverageCpc": current['AverageCpc'],
                        "WeeklySpendLimit": int(budget_rub * 1_000_000)
                    }
                },
                "Network": {"BiddingStrategyType": "SERVING_OFF"}
            }}
        }]}
    }, timeout=30)
    data = resp.json()
    if 'error' in data:
        return f"Ошибка API: {data['error']}"
    errs = data.get('result', {}).get('UpdateResults', [{}])[0].get('Errors', [])
    if errs:
        return f"Ошибка: {errs}"
    cname = CAMPAIGN_NAMES.get(campaign_id, campaign_id)
    return f"✅ Бюджет [{cname}] изменён на {budget_rub}₽/нед"


def tool_get_ad_groups(campaign_id: int = None) -> str:
    ids = [campaign_id] if campaign_id else OUR_CAMPAIGN_IDS
    resp = requests.post(f'{API_URL}/adgroups', headers=D_HEADERS, json={
        "method": "get",
        "params": {
            "SelectionCriteria": {"CampaignIds": ids},
            "FieldNames": ["Id", "Name", "CampaignId", "Status"]
        }
    }, timeout=30)
    data = resp.json()
    if 'error' in data:
        return f"Ошибка API: {data['error']}"
    groups = data.get('result', {}).get('AdGroups', [])
    if not groups:
        return "Групп объявлений не найдено."
    lines = [f"Группы объявлений ({len(groups)}):\n"]
    for g in groups:
        cname = CAMPAIGN_NAMES.get(g['CampaignId'], g['CampaignId'])
        lines.append(f"ID:{g['Id']}  \"{g['Name']}\"  {cname}  [{g['Status']}]")
    return "\n".join(lines)


def tool_get_keyword_stats(days: int = 7) -> str:
    if days <= 7:
        date_range = "LAST_7_DAYS"
    elif days <= 14:
        date_range = "LAST_14_DAYS"
    else:
        date_range = "LAST_30_DAYS"

    body = {
        "params": {
            "SelectionCriteria": {},
            "FieldNames": ["CampaignId", "CampaignName", "AdGroupId", "CriterionId",
                           "Criterion", "CriterionType", "Impressions", "Clicks",
                           "Ctr", "AvgCpc", "Cost"],
            "ReportName": f"KwStats {datetime.now().strftime('%Y%m%d%H%M%S')}",
            "ReportType": "CRITERIA_PERFORMANCE_REPORT",
            "DateRangeType": date_range,
            "Format": "TSV",
            "IncludeVAT": "NO",
            "IncludeDiscount": "NO"
        }
    }
    for _ in range(10):
        resp = requests.post(REPORTS_URL, headers=D_REPORT_HEADERS, json=body, timeout=60)
        if resp.status_code == 200:
            reader = csv.DictReader(io.StringIO(resp.text), delimiter='\t')
            rows = [r for r in reader if int(r['CampaignId']) in OUR_CAMPAIGN_IDS]
            if not rows:
                return "Нет данных за выбранный период."
            lines = [f"Статистика по ключевым словам за {days} дней:\n"]
            current_campaign = None
            for r in sorted(rows, key=lambda x: (x['CampaignId'], -int(x['Clicks'] or 0))):
                if r['CampaignName'] != current_campaign:
                    current_campaign = r['CampaignName']
                    lines.append(f"\n{r['CampaignName']}:")
                kw = r['Criterion'] if r['Criterion'] != '--' else '---autotargeting'
                lines.append(
                    f"  [{r['CriterionType']}] \"{kw}\"  "
                    f"Показы:{r['Impressions']}  Клики:{r['Clicks']}  "
                    f"CTR:{r['Ctr']}%  CPC:{r['AvgCpc']}₽  Расход:{r['Cost']}₽"
                )
            return "\n".join(lines)
        elif resp.status_code in (201, 202):
            time.sleep(int(resp.headers.get('retryIn', 5)))
        else:
            return f"Ошибка Reports API {resp.status_code}: {resp.text[:300]}"
    return "Отчёт не готов после 10 попыток."


def tool_create_campaign(name: str, bid_rub: float = 30.0, weekly_budget_rub: float = 1500.0) -> str:
    """Создаёт текстовую кампанию со стратегией AVERAGE_CPC."""
    resp = requests.post(f'{API_URL}/campaigns', headers=D_HEADERS, json={
        "method": "add",
        "params": {
            "Campaigns": [{
                "Name": name,
                "StartDate": datetime.now().strftime('%Y-%m-%d'),
                "TextCampaign": {
                    "BiddingStrategy": {
                        "Search": {
                            "BiddingStrategyType": "AVERAGE_CPC",
                            "AverageCpc": {
                                "AverageCpc": int(bid_rub * 1_000_000),
                                "WeeklySpendLimit": int(weekly_budget_rub * 1_000_000)
                            }
                        },
                        "Network": {"BiddingStrategyType": "SERVING_OFF"}
                    }
                }
            }]
        }
    }, timeout=30)
    data = resp.json()
    if 'error' in data:
        return f"Ошибка API: {data['error']}"
    results = data.get('result', {}).get('AddResults', [])
    if not results:
        return f"Пустой ответ: {json.dumps(data, ensure_ascii=False)}"
    errors = results[0].get('Errors')
    if errors:
        return f"Ошибка создания кампании: {errors}"
    campaign_id = results[0].get('Id')
    return f"Кампания создана. ID: {campaign_id}  Ставка: {bid_rub}₽  Бюджет: {weekly_budget_rub}₽/нед"


def tool_create_ad(ad_group_id: int, title1: str, title2: str, text: str, href: str) -> str:
    """Создаёт текстовое объявление в группе."""
    resp = requests.post(f'{API_URL}/ads', headers=D_HEADERS, json={
        "method": "add",
        "params": {
            "Ads": [{
                "AdGroupId": ad_group_id,
                "TextAd": {
                    "Title": title1,
                    "Title2": title2,
                    "Text": text,
                    "Href": href
                }
            }]
        }
    }, timeout=30)
    data = resp.json()
    if 'error' in data:
        return f"Ошибка API: {data['error']}"
    results = data.get('result', {}).get('AddResults', [])
    if not results:
        return f"Пустой ответ: {json.dumps(data, ensure_ascii=False)}"
    errors = results[0].get('Errors')
    if errors:
        return f"Ошибка создания объявления: {errors}"
    ad_id = results[0].get('Id')
    return f"Объявление создано. ID: {ad_id}  Заголовок: {title1}"


def tool_create_ad_group(campaign_id: int, name: str) -> str:
    """Создаёт группу объявлений с отключённым автотаргетингом."""
    resp = requests.post(f'{API_URL}/adgroups', headers=D_HEADERS, json={
        "method": "add",
        "params": {
            "AdGroups": [{
                "CampaignId": campaign_id,
                "Name": name,
                "RegionIds": [1]
            }]
        }
    }, timeout=30)
    data = resp.json()
    if 'error' in data:
        return f"Ошибка API: {data['error']}"
    results = data.get('result', {}).get('AddResults', [])
    if not results:
        return f"Пустой ответ: {json.dumps(data, ensure_ascii=False)}"
    errors = results[0].get('Errors')
    if errors:
        return f"Ошибка создания группы: {errors}"
    group_id = results[0].get('Id')
    return f"Группа создана. ID: {group_id}  Автотаргетинг: отключён"


def tool_archive_ad_group(ad_group_id: int) -> str:
    """Архивирует группу объявлений (остановить и скрыть старую группу)."""
    # Сначала останавливаем
    resp = requests.post(f'{API_URL}/adgroups', headers=D_HEADERS, json={
        "method": "suspend",
        "params": {"SelectionCriteria": {"Ids": [ad_group_id]}}
    }, timeout=30)
    data = resp.json()
    if 'error' in data:
        return f"Ошибка suspend: {data['error']}"

    # Затем архивируем
    resp2 = requests.post(f'{API_URL}/adgroups', headers=D_HEADERS, json={
        "method": "archive",
        "params": {"SelectionCriteria": {"Ids": [ad_group_id]}}
    }, timeout=30)
    data2 = resp2.json()
    if 'error' in data2:
        return f"Группа остановлена, но архивировать не удалось: {data2['error']}"
    return f"Группа {ad_group_id} остановлена и заархивирована."


def tool_update_autotargeting_categories(ad_group_id: int, enabled_categories: list) -> str:
    """Управляет категориями автотаргетинга в группе объявлений через adgroups.update.
    Категории: EXACT (целевые), NARROW (узкие), BROAD (широкие),
    ALTERNATIVE (альтернативные), COMPETITOR_BRAND (бренды конкурентов),
    OWN_BRAND (ваш бренд), NO_BRAND (без бренда).
    enabled_categories — список категорий, которые ВКЛЮЧИТЬ. Остальные выключаются.
    """
    ALL_CATEGORIES = ["EXACT", "NARROW", "BROAD", "ALTERNATIVE",
                      "COMPETITOR_BRAND", "OWN_BRAND", "NO_BRAND"]
    categories_payload = [
        {"Category": cat, "Value": "YES" if cat in enabled_categories else "NO"}
        for cat in ALL_CATEGORIES
    ]
    resp = requests.post(f'{API_URL}/adgroups', headers=D_HEADERS, json={
        "method": "update",
        "params": {
            "AdGroups": [{
                "Id": ad_group_id,
                "AutotargetingCategories": categories_payload
            }]
        }
    }, timeout=30)
    data = resp.json()
    if 'error' in data:
        return f"Ошибка API: {data['error']}"
    errs = data.get('result', {}).get('UpdateResults', [{}])[0].get('Errors', [])
    if errs:
        return f"Ошибка обновления категорий: {errs}"
    enabled_str = ", ".join(enabled_categories) if enabled_categories else "НЕТ (все отключены)"
    disabled = [c for c in ALL_CATEGORIES if c not in enabled_categories]
    return (
        f"Категории автотаргетинга группы {ad_group_id} обновлены.\n"
        f"  Включены: {enabled_str}\n"
        f"  Отключены: {', '.join(disabled) if disabled else 'нет'}"
    )


def tool_get_campaign_settings(campaign_id: int = None) -> str:
    """Возвращает текущие настройки кампаний: стратегию, ставку, бюджет, статус.
    Если campaign_id не указан — показывает все три наши кампании.
    """
    ids = [campaign_id] if campaign_id else OUR_CAMPAIGN_IDS
    resp = requests.post(f'{API_URL}/campaigns', headers=D_HEADERS, json={
        "method": "get",
        "params": {
            "SelectionCriteria": {"Ids": ids},
            "FieldNames": ["Id", "Name", "Status", "State"],
            "TextCampaignFieldNames": ["BiddingStrategy"]
        }
    }, timeout=30)
    data = resp.json()
    if 'error' in data:
        return f"Ошибка API: {data['error']}"
    campaigns = data.get('result', {}).get('Campaigns', [])
    if not campaigns:
        return "Кампании не найдены."

    lines = ["Текущие настройки кампаний:\n"]
    for c in campaigns:
        lines.append(f"[{c['Id']}] {c['Name']}  Статус: {c['Status']} / {c['State']}")
        strategy = c.get('TextCampaign', {}).get('BiddingStrategy', {})
        search = strategy.get('Search', {})
        stype = search.get('BiddingStrategyType', '—')
        if stype == 'AVERAGE_CPC':
            avg = search.get('AverageCpc', {})
            bid = avg.get('AverageCpc', 0) / 1_000_000
            budget = avg.get('WeeklySpendLimit', 0) / 1_000_000
            lines.append(f"  Стратегия: AVERAGE_CPC  Ставка: {bid:.2f}₽  Бюджет/нед: {budget:.0f}₽")
        elif stype == 'HIGHEST_POSITION':
            lines.append(f"  Стратегия: HIGHEST_POSITION (ручные ставки)  — ставки задаются на ключи")
        else:
            lines.append(f"  Стратегия: {stype}")
    return "\n".join(lines)


def tool_get_keyword_bids(campaign_id: int) -> str:
    """Показывает текущие ставки по ключевым словам кампании.
    Актуально для режима HIGHEST_POSITION — позволяет увидеть какие ставки выставлены на каждый ключ.
    """
    resp = requests.post(f'{API_URL}/keywords', headers=D_HEADERS, json={
        "method": "get",
        "params": {
            "SelectionCriteria": {"CampaignIds": [campaign_id]},
            "FieldNames": ["Id", "Keyword", "Bid", "ContextBid", "Status", "AdGroupId"],
            "Page": {"Limit": 10000}
        }
    }, timeout=30)
    data = resp.json()
    if 'error' in data:
        return f"Ошибка API: {data['error']}"
    keywords = data.get('result', {}).get('Keywords', [])
    if not keywords:
        return "Ключевых слов не найдено."

    cname = CAMPAIGN_NAMES.get(campaign_id, campaign_id)
    lines = [f"Ставки ключей [{cname}] ({len(keywords)} шт.):\n"]
    for kw in keywords:
        bid = (kw.get('Bid') or 0) / 1_000_000
        ctx = (kw.get('ContextBid') or 0) / 1_000_000
        bid_str = f"{bid:.2f}₽" if bid else "не задана"
        ctx_str = f"{ctx:.2f}₽" if ctx else "—"
        lines.append(
            f"  ID:{kw['Id']}  \"{kw['Keyword']}\"  "
            f"Поиск:{bid_str}  РСЯ:{ctx_str}  [{kw['Status']}]"
        )
    return "\n".join(lines)


def tool_update_keyword_bids(campaign_id: int, bid_rub: float, keyword_ids: list = None) -> str:
    """Устанавливает ставки на ключевые слова в режиме HIGHEST_POSITION (ручные ставки).
    Если keyword_ids не указан — выставляет ставку всем ключам кампании.
    НЕ работает в режиме AVERAGE_CPC — там ставки управляются через update_bid.
    """
    bid_micro = int(max(bid_rub, 0.3) * 1_000_000)

    # Если ID не переданы — получить все ключи кампании
    if not keyword_ids:
        resp = requests.post(f'{API_URL}/keywords', headers=D_HEADERS, json={
            "method": "get",
            "params": {
                "SelectionCriteria": {"CampaignIds": [campaign_id]},
                "FieldNames": ["Id", "Keyword"],
                "Page": {"Limit": 10000}
            }
        }, timeout=30)
        data = resp.json()
        if 'error' in data:
            return f"Ошибка получения ключей: {data['error']}"
        keywords = data.get('result', {}).get('Keywords', [])
        if not keywords:
            return "Ключевых слов не найдено."
        keyword_ids = [kw['Id'] for kw in keywords]
        kw_labels = {kw['Id']: kw['Keyword'] for kw in keywords}
    else:
        kw_labels = {kid: str(kid) for kid in keyword_ids}

    # Обновить ставки
    resp2 = requests.post(f'{API_URL}/keywords', headers=D_HEADERS, json={
        "method": "update",
        "params": {"Keywords": [
            {"Id": kid, "Bid": bid_micro, "ContextBid": bid_micro}
            for kid in keyword_ids
        ]}
    }, timeout=30)
    data2 = resp2.json()
    if 'error' in data2:
        return f"Ошибка keywords.update: {data2['error']}"
    results = data2.get('result', {}).get('UpdateResults', [])
    ok = sum(1 for r in results if not r.get('Errors'))
    bad = [(keyword_ids[i], r.get('Errors')) for i, r in enumerate(results) if r.get('Errors')]

    cname = CAMPAIGN_NAMES.get(campaign_id, campaign_id)
    msg = f"Ставки ключей [{cname}]: {bid_rub}₽ — обновлено {ok} из {len(keyword_ids)}."
    if bad:
        msg += f"\n  Ошибки у {len(bad)} ключей: {bad[0]}"
    return msg


def tool_update_campaign_strategy(campaign_id: int, strategy: str,
                                  bid_rub: float = None, weekly_budget_rub: float = None) -> str:
    """Меняет стратегию кампании.
    strategy: 'HIGHEST_POSITION' (ручные ставки) или 'AVERAGE_CPC' (средняя цена клика).
    При AVERAGE_CPC bid_rub и weekly_budget_rub обязательны.
    При HIGHEST_POSITION bid_rub и weekly_budget_rub игнорируются — ставки задаются на ключах отдельно.
    """
    strategy = strategy.upper()

    if strategy == "HIGHEST_POSITION":
        search_params = {"BiddingStrategyType": "HIGHEST_POSITION"}
    elif strategy == "AVERAGE_CPC":
        if not bid_rub or not weekly_budget_rub:
            return "Для AVERAGE_CPC нужно указать bid_rub и weekly_budget_rub."
        search_params = {
            "BiddingStrategyType": "AVERAGE_CPC",
            "AverageCpc": {
                "AverageCpc": int(bid_rub * 1_000_000),
                "WeeklySpendLimit": int(weekly_budget_rub * 1_000_000)
            }
        }
    else:
        return f"Неизвестная стратегия: {strategy}. Доступны: HIGHEST_POSITION, AVERAGE_CPC."

    resp = requests.post(f'{API_URL}/campaigns', headers=D_HEADERS, json={
        "method": "update",
        "params": {"Campaigns": [{
            "Id": campaign_id,
            "TextCampaign": {"BiddingStrategy": {
                "Search": search_params,
                "Network": {"BiddingStrategyType": "SERVING_OFF"}
            }}
        }]}
    }, timeout=30)
    data = resp.json()
    if 'error' in data:
        return f"Ошибка API: {data['error']}"
    errs = data.get('result', {}).get('UpdateResults', [{}])[0].get('Errors', [])
    if errs:
        return f"Ошибка обновления стратегии: {errs}"

    cname = CAMPAIGN_NAMES.get(campaign_id, campaign_id)
    if strategy == "HIGHEST_POSITION":
        return (
            f"Кампания [{cname}] переведена на ручные ставки (HIGHEST_POSITION).\n"
            f"  Ставки на ключи — update_keyword_bids (всем сразу или по ID).\n"
            f"  Ставку на автотаргетинг — set_autotargeting_bid."
        )
    else:
        return (
            f"Кампания [{cname}] переведена на AVERAGE_CPC.\n"
            f"  Средняя ставка: {bid_rub}₽  Недельный бюджет: {weekly_budget_rub}₽"
        )


def tool_set_autotargeting_bid(campaign_id: int, bid_rub: float = 0.3) -> str:
    """Выставляет ставку 0.3₽ ТОЛЬКО на автотаргетинг в кампании.
    Стратегию кампании и ставки ключевых слов НЕ меняет.
    Шаги: получить группы → получить автотаргетинги → выставить ставки через bids.set.
    """
    bid_rub = max(bid_rub, 0.3)
    bid_micro = int(bid_rub * 1_000_000)

    # Шаг 1: получить ID групп кампании
    resp = requests.post(f'{API_URL}/adgroups', headers=D_HEADERS, json={
        "method": "get",
        "params": {
            "SelectionCriteria": {"CampaignIds": [campaign_id]},
            "FieldNames": ["Id", "Name"]
        }
    }, timeout=30)
    data = resp.json()
    if 'error' in data:
        return f"Ошибка получения групп: {data['error']}"
    groups = data.get('result', {}).get('AdGroups', [])
    if not groups:
        return f"Групп в кампании {campaign_id} не найдено."
    group_ids = [g['Id'] for g in groups]

    # Шаг 2: получить автотаргетинги по группам
    resp2 = requests.post(f'{API_URL}/autotargetings', headers=D_HEADERS, json={
        "method": "get",
        "params": {
            "SelectionCriteria": {"AdGroupIds": group_ids},
            "FieldNames": ["Id", "AdGroupId", "CampaignId", "Bid", "ContextBid", "State"]
        }
    }, timeout=30)

    # Диагностика если /autotargetings недоступен
    if resp2.status_code != 200 or not resp2.text.strip():
        return (
            f"Эндпоинт /autotargetings вернул HTTP {resp2.status_code}.\n"
            f"Ответ: {resp2.text[:300] if resp2.text else '(пустой)'}\n"
            f"Групп найдено: {len(group_ids)} — {group_ids}"
        )

    data2 = resp2.json()
    if 'error' in data2:
        return (
            f"Ошибка /autotargetings.get: {data2['error']}\n"
            f"Групп найдено: {len(group_ids)} — {group_ids}"
        )

    autotargetings = data2.get('result', {}).get('Autotargetings', [])
    if not autotargetings:
        return (
            f"Автотаргетинги не найдены через /autotargetings.get.\n"
            f"Полный ответ API: {json.dumps(data2, ensure_ascii=False)[:500]}"
        )

    # Шаг 3: выставить ставки через bids.set
    bid_objects = [
        {"AutotargetingId": at['Id'], "Bid": bid_micro, "ContextBid": bid_micro}
        for at in autotargetings
    ]
    resp3 = requests.post(f'{API_URL}/bids', headers=D_HEADERS, json={
        "method": "set",
        "params": {"Bids": bid_objects}
    }, timeout=30)
    data3 = resp3.json()
    if 'error' in data3:
        return (
            f"Автотаргетинги найдены ({len(autotargetings)} шт.), но bids.set вернул ошибку:\n"
            f"{data3['error']}\n"
            f"IDs автотаргетингов: {[at['Id'] for at in autotargetings]}"
        )

    results3 = data3.get('result', {}).get('SetResults', [])
    ok = sum(1 for r in results3 if not r.get('Errors'))
    bad = [r.get('Errors') for r in results3 if r.get('Errors')]
    cname = CAMPAIGN_NAMES.get(campaign_id, campaign_id)
    msg = (
        f"Ставка автотаргетинга [{cname}] → {bid_rub}₽\n"
        f"  Обновлено: {ok} из {len(autotargetings)}\n"
        f"  Ключевые слова и стратегия НЕ изменены."
    )
    if bad:
        msg += f"\n  Ошибки: {bad[0]}"
    return msg


def tool_switch_to_manual_bids(campaign_id: int, bid_rub: float = 0.3) -> str:
    """Переключает кампанию на стратегию HIGHEST_POSITION (ручные ставки)
    и выставляет всем ключевым словам минимальную ставку bid_rub рублей (мин. 0.3).
    Фактически нейтрализует автотаргетинг — у него не будет бюджета на показы.
    """
    bid_rub = max(bid_rub, 0.3)  # минимум Яндекс Директ
    bid_micro = int(bid_rub * 1_000_000)

    # Шаг 1: переключить стратегию на HIGHEST_POSITION (ручные ставки)
    resp = requests.post(f'{API_URL}/campaigns', headers=D_HEADERS, json={
        "method": "update",
        "params": {"Campaigns": [{
            "Id": campaign_id,
            "TextCampaign": {"BiddingStrategy": {
                "Search": {"BiddingStrategyType": "HIGHEST_POSITION"},
                "Network": {"BiddingStrategyType": "SERVING_OFF"}
            }}
        }]}
    }, timeout=30)
    data = resp.json()
    if 'error' in data:
        return f"Ошибка переключения стратегии: {data['error']}"
    errs = data.get('result', {}).get('UpdateResults', [{}])[0].get('Errors', [])
    if errs:
        return f"Ошибка стратегии: {errs}"

    # Шаг 2: получить все ключи кампании
    resp2 = requests.post(f'{API_URL}/keywords', headers=D_HEADERS, json={
        "method": "get",
        "params": {
            "SelectionCriteria": {"CampaignIds": [campaign_id]},
            "FieldNames": ["Id", "Keyword", "Status"],
            "Page": {"Limit": 10000}
        }
    }, timeout=30)
    data2 = resp2.json()
    if 'error' in data2:
        return f"Стратегия переключена. Ошибка получения ключей: {data2['error']}"
    keywords = data2.get('result', {}).get('Keywords', [])
    if not keywords:
        cname = CAMPAIGN_NAMES.get(campaign_id, campaign_id)
        return f"Кампания [{cname}] переключена на ручные ставки. Ключевых слов не найдено — ставки не обновлены."

    # Шаг 3: выставить всем ключам ставку bid_rub
    kw_updates = [{"Id": kw["Id"], "Bid": bid_micro, "ContextBid": bid_micro} for kw in keywords]
    resp3 = requests.post(f'{API_URL}/keywords', headers=D_HEADERS, json={
        "method": "update",
        "params": {"Keywords": kw_updates}
    }, timeout=30)
    data3 = resp3.json()
    if 'error' in data3:
        return f"Стратегия переключена. Ошибка обновления ставок ключей: {data3['error']}"
    results3 = data3.get('result', {}).get('UpdateResults', [])
    ok = sum(1 for r in results3 if not r.get('Errors'))
    bad = [r.get('Errors') for r in results3 if r.get('Errors')]

    cname = CAMPAIGN_NAMES.get(campaign_id, campaign_id)
    msg = (
        f"Кампания [{cname}] переключена на ручные ставки.\n"
        f"  Ставка выставлена: {bid_rub}₽ ({ok} из {len(keywords)} ключей)\n"
        f"  Автотаргетинг фактически нейтрализован — ставки ниже минимального порога показа."
    )
    if bad:
        msg += f"\n  Ошибки у {len(bad)} ключей: {bad[0]}"
    return msg


# ============================================================================
# ПАМЯТЬ АГЕНТА
# ============================================================================

MEMORY_FILE = Path(__file__).resolve().parent.parent.parent / "logs" / "agent_memory.json"
MAX_MEMORY_ENTRIES = 30


def _load_memory() -> dict:
    if MEMORY_FILE.exists():
        try:
            return json.loads(MEMORY_FILE.read_text(encoding='utf-8'))
        except Exception:
            return {}
    return {}


def _save_memory_file(data: dict):
    # Удаляем самые старые записи если превышен лимит
    if len(data) > MAX_MEMORY_ENTRIES:
        sorted_keys = sorted(data, key=lambda k: data[k].get('updated', ''))
        for k in sorted_keys[:len(data) - MAX_MEMORY_ENTRIES]:
            del data[k]
    MEMORY_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def tool_save_memory(key: str, value: str) -> str:
    data = _load_memory()
    data[key] = {"value": value, "updated": datetime.now().strftime('%Y-%m-%d %H:%M')}
    _save_memory_file(data)
    return f"Сохранено в память: [{key}] = {value}"


def tool_read_memory() -> str:
    data = _load_memory()
    if not data:
        return "Память пуста."
    lines = ["Содержимое памяти:\n"]
    for key, entry in sorted(data.items(), key=lambda x: x[1].get('updated', ''), reverse=True):
        lines.append(f"[{entry['updated']}] {key}: {entry['value']}")
    return "\n".join(lines)


def _memory_context() -> str:
    """Возвращает содержимое памяти для системного промпта."""
    data = _load_memory()
    if not data:
        return ""
    lines = ["\n\nПАМЯТЬ (накопленный контекст из прошлых сессий):"]
    for key, entry in sorted(data.items(), key=lambda x: x[1].get('updated', ''), reverse=True):
        lines.append(f"- [{entry['updated']}] {key}: {entry['value']}")
    return "\n".join(lines)


# ============================================================================
# TOOLS SCHEMA (OpenAI-compatible format — работает с DeepSeek)
# ============================================================================

def _fn(name, description, properties, required=None):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                **({"required": required} if required else {}),
            },
        },
    }

DEEPSEEK_TOOLS = [
    _fn("get_campaign_stats",
        "Статистика рекламных кампаний: показы, клики, CTR, CPC, расход.",
        {"days": {"type": "integer", "description": "Период: 7, 14 или 30 дней", "enum": [7, 14, 30]}}),

    _fn("get_keywords",
        "Список ключевых слов с ID, статусами и группами. ID нужны для удаления.",
        {"campaign_id": {"type": "integer", "description": "ID кампании (опционально). 708112800=Магазины, 708112806=Рестораны, 708112808=Брендированные"}}),

    _fn("delete_keywords",
        "Удалить ключевые слова по ID. Только после явного подтверждения пользователя.",
        {"keyword_ids": {"type": "array", "items": {"type": "integer"}, "description": "Список ID ключевых слов"}},
        required=["keyword_ids"]),

    _fn("add_keywords",
        "Добавить ключевые слова в группу объявлений.",
        {
            "ad_group_id": {"type": "integer", "description": "ID группы объявлений (из get_ad_groups)"},
            "keywords": {"type": "array", "items": {"type": "string"}, "description": "Список ключевых фраз"},
        },
        required=["ad_group_id", "keywords"]),

    _fn("update_bid",
        "Изменить ставку (AverageCpc) кампании. Только после подтверждения.",
        {
            "campaign_id": {"type": "integer", "description": "ID кампании"},
            "bid_rub": {"type": "number", "description": "Новая ставка в рублях (15–60)"},
        },
        required=["campaign_id", "bid_rub"]),

    _fn("update_budget",
        "Изменить недельный бюджет кампании. Только после подтверждения.",
        {
            "campaign_id": {"type": "integer", "description": "ID кампании"},
            "budget_rub": {"type": "number", "description": "Новый недельный бюджет в рублях"},
        },
        required=["campaign_id", "budget_rub"]),

    _fn("get_ad_groups",
        "Список групп объявлений. Нужно перед добавлением ключевых слов.",
        {"campaign_id": {"type": "integer", "description": "ID кампании (опционально)"}}),

    _fn("get_keyword_stats",
        "Статистика по каждому ключевому слову: показы, клики, CTR, CPC, расход. "
        "Показывает ---autotargeting отдельной строкой — виден его реальный расход. "
        "Использовать для анализа эффективности отдельных ключей.",
        {"days": {"type": "integer", "description": "Период: 7, 14 или 30 дней", "enum": [7, 14, 30]}}),

    _fn("save_memory",
        "Сохранить важный факт в долгосрочную память. Используй после каждого значимого действия: "
        "изменения ставок, бюджетов, ключей, наблюдений по статистике. "
        "Память доступна в следующих сессиях.",
        {
            "key": {"type": "string", "description": "Короткий ключ (например: autotargeting_status, bid_магазины, наблюдение_CTR)"},
            "value": {"type": "string", "description": "Значение — факт или решение с датой"},
        },
        required=["key", "value"]),

    _fn("read_memory",
        "Прочитать всю сохранённую память из прошлых сессий.",
        {}),

    _fn("create_ad",
        "Создать текстовое объявление в группе. Title1 до 35 символов, Title2 до 30, Text до 81 символа.",
        {
            "ad_group_id": {"type": "integer", "description": "ID группы объявлений"},
            "title1": {"type": "string", "description": "Заголовок 1 (до 35 символов)"},
            "title2": {"type": "string", "description": "Заголовок 2 (до 30 символов)"},
            "text": {"type": "string", "description": "Текст объявления (до 81 символа)"},
            "href": {"type": "string", "description": "Ссылка (обычно https://pakety.shop)"},
        },
        required=["ad_group_id", "title1", "title2", "text", "href"]),

    _fn("create_campaign",
        "Создать новую рекламную кампанию в Яндекс Директ со стратегией AVERAGE_CPC. "
        "Только после явного подтверждения пользователя.",
        {
            "name": {"type": "string", "description": "Название кампании"},
            "bid_rub": {"type": "number", "description": "Средняя ставка CPC в рублях (по умолчанию 30)"},
            "weekly_budget_rub": {"type": "number", "description": "Недельный бюджет в рублях (по умолчанию 1500)"},
        },
        required=["name"]),

    _fn("create_ad_group",
        "Создать новую группу объявлений в существующей кампании.",
        {
            "campaign_id": {"type": "integer", "description": "ID кампании"},
            "name": {"type": "string", "description": "Название новой группы"},
        },
        required=["campaign_id", "name"]),

    _fn("archive_ad_group",
        "Остановить и заархивировать группу объявлений. "
        "Использовать после пересоздания группы — для деактивации старой группы с автотаргетингом. "
        "Только после явного подтверждения пользователя.",
        {"ad_group_id": {"type": "integer", "description": "ID группы для архивирования"}},
        required=["ad_group_id"]),

    _fn("update_autotargeting_categories",
        "Управлять категориями автотаргетинга в группе объявлений. "
        "С 2024г. полностью отключить автотаргетинг невозможно, но можно снизить его влияние: "
        "оставить только EXACT (целевые) и NARROW (узкие), отключить BROAD/ALTERNATIVE/COMPETITOR_BRAND/OWN_BRAND/NO_BRAND. "
        "Категории: EXACT=целевые, NARROW=узкие, BROAD=широкие, ALTERNATIVE=альтернативные, "
        "COMPETITOR_BRAND=бренды конкурентов, OWN_BRAND=ваш бренд, NO_BRAND=без бренда. "
        "Только после явного подтверждения пользователя.",
        {
            "ad_group_id": {"type": "integer", "description": "ID группы объявлений"},
            "enabled_categories": {
                "type": "array",
                "items": {"type": "string", "enum": ["EXACT", "NARROW", "BROAD", "ALTERNATIVE", "COMPETITOR_BRAND", "OWN_BRAND", "NO_BRAND"]},
                "description": "Список категорий которые ОСТАВИТЬ включёнными. Остальные будут отключены."
            }
        },
        required=["ad_group_id", "enabled_categories"]),

    _fn("get_campaign_settings",
        "Показать текущие настройки кампаний: стратегию, ставку CPC, недельный бюджет, статус. "
        "Вызывать ПЕРВЫМ когда нужно понять в каком режиме работает кампания перед изменением ставок.",
        {"campaign_id": {"type": "integer", "description": "ID кампании (опционально). Без параметра — все три кампании."}}),

    _fn("get_keyword_bids",
        "Показать текущие ставки по всем ключевым словам кампании. "
        "Использовать для кампаний с HIGHEST_POSITION чтобы увидеть какие ставки сейчас выставлены.",
        {"campaign_id": {"type": "integer", "description": "ID кампании"}},
        required=["campaign_id"]),

    _fn("update_keyword_bids",
        "Установить ставки на ключевые слова в режиме ручных ставок (HIGHEST_POSITION). "
        "Если keyword_ids не указан — выставляет ставку всем ключам кампании. "
        "ВАЖНО: работает только после переключения стратегии на HIGHEST_POSITION через update_campaign_strategy. "
        "В режиме AVERAGE_CPC для изменения ставки используй update_bid.",
        {
            "campaign_id": {"type": "integer", "description": "ID кампании"},
            "bid_rub": {"type": "number", "description": "Ставка в рублях (минимум 0.3)"},
            "keyword_ids": {"type": "array", "items": {"type": "integer"},
                            "description": "Список ID ключей (опционально). Если не указан — обновятся все ключи кампании."},
        },
        required=["campaign_id", "bid_rub"]),

    _fn("update_campaign_strategy",
        "Изменить стратегию кампании. "
        "HIGHEST_POSITION — ручные ставки (ставки задаются на каждый ключ отдельно). "
        "AVERAGE_CPC — средняя цена клика с недельным бюджетом. "
        "Только после явного подтверждения пользователя.",
        {
            "campaign_id": {"type": "integer", "description": "ID кампании"},
            "strategy": {"type": "string", "enum": ["HIGHEST_POSITION", "AVERAGE_CPC"],
                         "description": "HIGHEST_POSITION=ручные ставки, AVERAGE_CPC=средняя цена клика"},
            "bid_rub": {"type": "number", "description": "Средняя ставка CPC в рублях (только для AVERAGE_CPC)"},
            "weekly_budget_rub": {"type": "number", "description": "Недельный бюджет в рублях (только для AVERAGE_CPC)"},
        },
        required=["campaign_id", "strategy"]),

    _fn("set_autotargeting_bid",
        "Выставить ставку 0.3₽ ТОЛЬКО на автотаргетинг в кампании. "
        "Стратегию кампании и ставки ключевых слов НЕ меняет. "
        "Использовать когда автотаргетинг жрёт бюджет — при ставке 0.3₽ он перестаёт показываться. "
        "Только после явного подтверждения пользователя.",
        {
            "campaign_id": {"type": "integer", "description": "ID кампании"},
            "bid_rub": {"type": "number", "description": "Ставка в рублях (минимум 0.3, по умолчанию 0.3)"},
        },
        required=["campaign_id"]),

    _fn("switch_to_manual_bids",
        "Переключить кампанию на стратегию 'Ручные ставки' (HIGHEST_POSITION) и выставить "
        "всем ключевым словам (включая автотаргетинг) минимальную ставку 0.3₽. "
        "Кардинальный сброс всех ставок — используй только если set_autotargeting_bid не помог. "
        "Только после явного подтверждения пользователя.",
        {
            "campaign_id": {"type": "integer", "description": "ID кампании"},
            "bid_rub": {"type": "number", "description": "Ставка в рублях (минимум 0.3, по умолчанию 0.3)"},
        },
        required=["campaign_id"]),
]

TOOL_FUNCTIONS = {
    "get_campaign_stats": lambda i: tool_get_campaign_stats(i.get("days", 7)),
    "get_keywords":       lambda i: tool_get_keywords(i.get("campaign_id")),
    "delete_keywords":    lambda i: tool_delete_keywords(i["keyword_ids"]),
    "add_keywords":       lambda i: tool_add_keywords(i["ad_group_id"], i["keywords"]),
    "create_ad":          lambda i: tool_create_ad(i["ad_group_id"], i["title1"], i["title2"], i["text"], i["href"]),
    "create_campaign":    lambda i: tool_create_campaign(i["name"], i.get("bid_rub", 30.0), i.get("weekly_budget_rub", 1500.0)),
    "create_ad_group":    lambda i: tool_create_ad_group(i["campaign_id"], i["name"]),
    "archive_ad_group":   lambda i: tool_archive_ad_group(i["ad_group_id"]),
    "update_autotargeting_categories": lambda i: tool_update_autotargeting_categories(i["ad_group_id"], i.get("enabled_categories", [])),
    "get_campaign_settings":           lambda i: tool_get_campaign_settings(i.get("campaign_id")),
    "get_keyword_bids":                lambda i: tool_get_keyword_bids(i["campaign_id"]),
    "update_keyword_bids":             lambda i: tool_update_keyword_bids(i["campaign_id"], i["bid_rub"], i.get("keyword_ids")),
    "update_campaign_strategy":        lambda i: tool_update_campaign_strategy(i["campaign_id"], i["strategy"], i.get("bid_rub"), i.get("weekly_budget_rub")),
    "set_autotargeting_bid":           lambda i: tool_set_autotargeting_bid(i["campaign_id"], i.get("bid_rub", 0.3)),
    "switch_to_manual_bids":           lambda i: tool_switch_to_manual_bids(i["campaign_id"], i.get("bid_rub", 0.3)),
    "get_keyword_stats":  lambda i: tool_get_keyword_stats(i.get("days", 7)),
    "save_memory":        lambda i: tool_save_memory(i["key"], i["value"]),
    "read_memory":        lambda i: tool_read_memory(),
    "update_bid":         lambda i: tool_update_bid(i["campaign_id"], i["bid_rub"]),
    "update_budget":      lambda i: tool_update_budget(i["campaign_id"], i["budget_rub"]),
    "get_ad_groups":      lambda i: tool_get_ad_groups(i.get("campaign_id")),
}

SYSTEM_PROMPT = """Ты AI-ассистент для управления рекламными кампаниями в Яндекс Директ.

Бизнес: производство и продажа крафт-бумажных подарочных пакетов, Москва (pakety.shop). B2B-клиенты: магазины, рестораны, бренды.

Кампании:
- 708112800 "B2B — Магазины": пакеты для розничных магазинов
- 708112806 "B2B — Рестораны": пакеты для ресторанов и кафе
- 708112808 "B2B — Брендированные пакеты": кастомные пакеты с логотипом

Стратегии кампании и управление ставками:

ПРЕЖДЕ ЧЕМ МЕНЯТЬ СТАВКИ — вызови get_campaign_settings чтобы узнать текущую стратегию каждой кампании. Не угадывай — смотри факты.

AVERAGE_CPC:
- Ставка кампании → update_bid (меняет AverageCpc)
- Бюджет → update_budget
- Ставки отдельных ключей в этом режиме НЕ управляются.

HIGHEST_POSITION (ручные ставки):
- Ставки ключей → update_keyword_bids (всем сразу или по ID). Посмотреть текущие ставки → get_keyword_bids.
- Ставка автотаргетинга → set_autotargeting_bid
- update_bid и update_budget в этом режиме НЕ применимы.

СМЕНА СТРАТЕГИИ: update_campaign_strategy. Если пользователь хочет ставки на ключи, а стратегия AVERAGE_CPC — сначала переключи через update_campaign_strategy, затем update_keyword_bids. Предупреди и спроси подтверждение.

Правила работы:
1. Перед удалением ключей — покажи список и явно спроси подтверждение.
2. Перед любым изменением (ставка, бюджет, стратегия, ключи) — назови конкретные цифры и спроси подтверждение.
3. Если нет данных — сначала запроси их инструментом (get_campaign_stats, get_campaign_settings, get_keyword_bids). Не угадывай и не предполагай.
4. Отвечай на русском. Будь конкретен: цифры, ID, названия кампаний.
5. ЧЕСТНОСТЬ: Если не знаешь ответа на вопрос — прямо скажи "не знаю" или "нужно проверить через API". Здесь управляют реальными деньгами. Любая ошибочная информация или догадка недопустима.
6. Автотаргетинг (---autotargeting) — важные правила:
   - С 2024г. полностью ОТКЛЮЧИТЬ автотаргетинг невозможно ни через API, ни через веб-интерфейс. Он принудительно встроен в Яндекс Директ.
   - Категории автотаргетинга на Поиске: EXACT (целевые), NARROW (узкие), BROAD (широкие), ALTERNATIVE (альтернативные), COMPETITOR_BRAND (бренды конкурентов), OWN_BRAND (ваш бренд), NO_BRAND (без бренда).
   - Метод 1 — снизить охват (update_autotargeting_categories): оставить только EXACT и NARROW, отключить остальные. Вызывать для каждой группы отдельно (нужен ad_group_id из get_ad_groups).
   - Метод 2 — заглушить ставкой (set_autotargeting_bid): выставить 0.3₽ ТОЛЬКО на автотаргетинг, ключи и стратегию НЕ трогает. Предпочтительный метод.
   - Метод 3 — кардинальный (switch_to_manual_bids): ручные ставки + 0.3₽ ВСЕМ ключам. Только если методы 1 и 2 не помогли.
7. После каждого значимого действия — вызывай save_memory. Память загружена в контекст автоматически.

Ограничения:
- Отвечай ТОЛЬКО на вопросы, связанные с Яндекс Директ, рекламными кампаниями, ключевыми словами, ставками и бюджетами этого бизнеса.
- Допустимо обсуждать тематику ключевых слов и объявлений в контексте бумажных пакетов: подбор фраз, формулировки для объявлений, целевая аудитория (магазины, рестораны, бренды), сезонность спроса на упаковку.
- Если вопрос не касается рекламы пакетов — вежливо откажи: "Я специализируюсь только на управлении рекламой бумажных пакетов в Яндекс Директ. Задайте вопрос по кампаниям."
- Не пиши код, не давай советов по другим темам, не обсуждай ничего кроме рекламы."""


# ============================================================================
# ЛОГИРОВАНИЕ ЧАТА
# ============================================================================

LOG_DIR = Path(__file__).resolve().parent.parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)


def _write_chat_log(messages: list, tool_calls_log: list, assistant_text: str):
    """Пишет запись в дневной лог-файл. Результаты API не логируются."""
    log_file = LOG_DIR / f"admin_chat_{datetime.now().strftime('%Y%m%d')}.log"
    lines = [
        f"\n{'═' * 60}",
        f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]",
        f"{'═' * 60}",
    ]
    # Полная переписка из истории
    for m in messages:
        role = "USER" if m["role"] == "user" else "ASSISTANT"
        content = m["content"]
        if isinstance(content, str):
            text = content.strip()
            if len(text) > 300:
                text = text[:300] + "…"
            lines.append(f"{role}: {text}")
    # Инструменты текущего хода
    for tc in tool_calls_log:
        params = ", ".join(f"{k}={v}" for k, v in tc["input"].items()) if tc["input"] else ""
        lines.append(f"TOOL: {tc['name']}({params})")
    # Финальный ответ агента
    if assistant_text.strip():
        text = assistant_text.strip()
        if len(text) > 300:
            text = text[:300] + "…"
        lines.append(f"ASSISTANT: {text}")
    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except Exception:
        pass  # не ломаем работу из-за ошибки логирования


# ============================================================================
# SSE STREAMING CHAT
# ============================================================================

def sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


async def chat_stream(messages: list) -> AsyncGenerator[str, None]:
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        yield sse({"type": "error", "message": "DEEPSEEK_API_KEY не задан"})
        return

    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")

    # Системное сообщение + память, затем последние 20 сообщений чата
    system_with_memory = SYSTEM_PROMPT + _memory_context()
    api_messages = [{"role": "system", "content": system_with_memory}]
    api_messages += [{"role": m["role"], "content": m["content"]} for m in messages[-20:]]

    log_tools = []       # [{name, input}] — все вызовы за сессию
    log_assistant = ""   # итоговый текст агента

    for _ in range(10):  # макс. итераций tool-use цикла
        tool_calls_acc = {}   # index -> {id, name, arguments}
        assistant_text = ""
        finish_reason = None

        try:
            stream = client.chat.completions.create(
                model="deepseek-chat",
                max_tokens=4096,
                messages=api_messages,
                tools=DEEPSEEK_TOOLS,
                stream=True,
            )
            for chunk in stream:
                choice = chunk.choices[0]
                delta = choice.delta
                finish_reason = choice.finish_reason or finish_reason

                if delta.content:
                    assistant_text += delta.content
                    log_assistant += delta.content
                    yield sse({"type": "text", "content": delta.content})

                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index
                        if idx not in tool_calls_acc:
                            tool_calls_acc[idx] = {
                                "id": tc.id,
                                "name": tc.function.name,
                                "arguments": "",
                            }
                            yield sse({"type": "tool_start", "name": tc.function.name})
                        if tc.function and tc.function.arguments:
                            tool_calls_acc[idx]["arguments"] += tc.function.arguments

        except Exception as e:
            yield sse({"type": "error", "message": f"DeepSeek API: {e}"})
            return

        if finish_reason != "tool_calls":
            break

        # Добавляем ответ ассистента с tool_calls в историю
        api_messages.append({
            "role": "assistant",
            "content": assistant_text or None,
            "tool_calls": [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {"name": tc["name"], "arguments": tc["arguments"]},
                }
                for tc in tool_calls_acc.values()
            ],
        })

        # Выполняем инструменты, каждый результат — отдельное сообщение role=tool
        for tc in tool_calls_acc.values():
            try:
                inp = json.loads(tc["arguments"]) if tc["arguments"].strip() else {}
            except json.JSONDecodeError:
                inp = {}

            yield sse({"type": "tool_executing", "name": tc["name"], "input": inp})
            log_tools.append({"name": tc["name"], "input": inp})

            try:
                result = TOOL_FUNCTIONS[tc["name"]](inp)
            except Exception as e:
                result = f"Ошибка: {e}"

            yield sse({"type": "tool_result", "name": tc["name"], "result": result})

            api_messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": result,
            })

    _write_chat_log(messages, log_tools, log_assistant)
    yield sse({"type": "done"})


# ============================================================================
# ENDPOINTS
# ============================================================================

class ChatRequest(BaseModel):
    messages: list
    token: str


def _check_token(token: str):
    expected = os.environ.get("ADMIN_TOKEN", "")
    if not expected:
        raise HTTPException(500, "ADMIN_TOKEN не задан на сервере")
    if token != expected:
        raise HTTPException(403, "Неверный токен")


@router.post("/api/chat")
async def chat_endpoint(req: ChatRequest):
    _check_token(req.token)
    return StreamingResponse(
        chat_stream(req.messages),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("", include_in_schema=False)
@router.get("/", include_in_schema=False)
async def admin_page():
    html_path = Path(__file__).resolve().parent.parent.parent / "static" / "admin" / "index.html"
    if html_path.exists():
        return FileResponse(str(html_path))
    raise HTTPException(404, "Страница не найдена")
