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


def tool_disable_autotargeting(ad_group_ids: list) -> str:
    """Отключает автотаргетинг для указанных групп объявлений.
    ---autotargeting нельзя удалить через keywords.delete — это системный псевдо-ключ.
    Единственный способ — отключить автотаргетинг на уровне группы через adgroups.update.
    """
    groups_payload = [
        {"Id": gid, "TextAdGroup": {"AutotargetingEnabled": "NO"}}
        for gid in ad_group_ids
    ]
    resp = requests.post(f'{API_URL}/adgroups', headers=D_HEADERS, json={
        "method": "update",
        "params": {"AdGroups": groups_payload}
    }, timeout=30)
    data = resp.json()
    if 'error' in data:
        return f"Ошибка API: {data['error']}"
    results = data.get('result', {}).get('UpdateResults', [])
    ok = sum(1 for r in results if not r.get('Errors'))
    bad = [r.get('Errors') for r in results if r.get('Errors')]
    msg = f"Автотаргетинг отключён в {ok} из {len(ad_group_ids)} группах."
    if bad:
        msg += f" Ошибки: {bad}"
    return msg


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

    _fn("disable_autotargeting",
        "Отключить автотаргетинг (---autotargeting) в группах объявлений. "
        "Использовать вместо delete_keywords когда пользователь хочет удалить ---autotargeting. "
        "Автотаргетинг — системный псевдо-ключ, его нельзя удалить через keywords.delete.",
        {"ad_group_ids": {"type": "array", "items": {"type": "integer"}, "description": "Список ID групп объявлений"}},
        required=["ad_group_ids"]),
]

TOOL_FUNCTIONS = {
    "get_campaign_stats": lambda i: tool_get_campaign_stats(i.get("days", 7)),
    "get_keywords":       lambda i: tool_get_keywords(i.get("campaign_id")),
    "delete_keywords":    lambda i: tool_delete_keywords(i["keyword_ids"]),
    "add_keywords":       lambda i: tool_add_keywords(i["ad_group_id"], i["keywords"]),
    "disable_autotargeting": lambda i: tool_disable_autotargeting(i["ad_group_ids"]),
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

Текущая стратегия: AVERAGE_CPC, ~1500 руб/нед на каждую, ставки ~30–33 руб.

Правила работы:
1. Перед удалением ключей — покажи список и явно спроси подтверждение
2. Перед изменением ставок/бюджетов — объясни причину, назови конкретные цифры, спроси подтверждение
3. Если нет данных для анализа — сначала вызови get_campaign_stats
4. Отвечай на русском. Будь конкретен: цифры, ID, названия кампаний.
5. "---autotargeting" — это НЕ обычный ключ. Его нельзя удалить через delete_keywords. Для отключения автотаргетинга используй ТОЛЬКО disable_autotargeting с ID группы объявлений (не ID ключа). Если нужен ID группы — вызови get_keywords, поле AdGroupId.

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

    # Системное сообщение идёт первым, затем история
    api_messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    api_messages += [{"role": m["role"], "content": m["content"]} for m in messages]

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
