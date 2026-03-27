#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Yandex Direct API v5 — Campaign Creator (v7 — Исправленная обработка ошибок)
Для: Влада (бумажные пакеты, Москва)
Дата: 11 марта 2026

Исправления:
- ✅ Правильная проверка ответов API (не только HTTP-статус)
- ✅ Детальная диагностика ошибок авторизации и других проблем
- ✅ Убрано ложное сообщение об успехе при наличии ошибки в JSON
- ✅ Код стал более надёжным и читаемым

Установка:
    pip install requests

Использование:
    python direct_campaign_creator_v7.py
"""

import requests
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, List

# ============================================================================
# НАСТРОЙКА ЛОГИРОВАНИЯ
# ============================================================================

LOG_DIR = Path('logs')
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / f"yandex_direct_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

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
# ТОКЕН И НАСТРОЙКИ
# ============================================================================

TOKEN = 'y0__xDB-O3LAhj04z4goe2H2hb7BdqiFzzob_KzE3qjBKWqWppmXQ'  # замените при необходимости
API_URL = 'https://api.direct.yandex.com/json/v5'

# Заголовки (Client-Login может быть причиной ошибок, если такого логина нет в песочнице)
HEADERS = {
    'Authorization': f'Bearer {TOKEN}',
    'Content-Type': 'application/json',
    'Accept-Language': 'ru',
    #'Client-Login': 'c9269203781'
    # 'Client-Login': 'direct-api-client'   # при проблемах раскомментируйте или удалите
}

TODAY = datetime.now().strftime('%Y-%m-%d')
START_DATE = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')


# ============================================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================================

def log_request(response: requests.Response, operation: str, request_data: Optional[Dict] = None) -> Optional[Dict]:
    """Подробно логирует запрос и ответ, возвращает распарсенный JSON или None."""
    logger.info("=" * 80)
    logger.info(f"📡 {operation}")
    logger.info("=" * 80)
    logger.info(f"URL: {response.url}")
    logger.info(f"Метод: {response.request.method}")
    logger.info(f"Статус: {response.status_code}")

    # Заголовки запроса
    logger.info("\n📋 Заголовки запроса:")
    for key, value in response.request.headers.items():
        if key.lower() == 'authorization':
            # Скрываем токен (первые 15 символов)
            logger.info(f"  {key}: OAuth {value.split(' ')[1][:15]}...")
        else:
            logger.info(f"  {key}: {value}")

    # Тело запроса
    if request_data:
        logger.info("\n📦 Тело запроса:")
        logger.info(json.dumps(request_data, indent=2, ensure_ascii=False))

    # Тело ответа
    logger.info(f"\n📄 Тело ответа ({len(response.text)} символов):")
    logger.info(response.text)

    # Парсим JSON
    try:
        data = response.json()
        logger.info("\n✅ Парсинг JSON: Успешно")
        return data
    except json.JSONDecodeError:
        logger.info("❌ Парсинг JSON: Ошибка (не JSON)")
        return None


def is_success_response(api_response: Optional[Dict]) -> bool:
    """
    Проверяет, что ответ API не содержит ошибки.
    Возвращает True, если ответ есть и в нём нет поля 'error'.
    """
    if api_response is None:
        return False
    if 'error' in api_response:
        error = api_response['error']
        logger.error(f"❌ Ошибка API: {error.get('error_string', 'Неизвестная ошибка')} "
                     f"(код {error.get('error_code', '?')})")
        logger.error(f"   Детали: {error.get('error_detail', 'Нет деталей')}")
        return False
    return True


def extract_campaign_id(api_response: Dict) -> Optional[int]:
    """Извлекает ID кампании из успешного ответа на добавление."""
    try:
        return api_response['result']['AddResults'][0]['Id']
    except (KeyError, IndexError, TypeError):
        logger.error("❌ Не удалось извлечь ID кампании из ответа")
        return None


def extract_ad_group_id(api_response: Dict) -> Optional[int]:
    """Извлекает ID группы объявлений."""
    try:
        return api_response['result']['AddResults'][0]['Id']
    except (KeyError, IndexError, TypeError):
        logger.error("❌ Не удалось извлечь ID группы из ответа")
        return None


# ============================================================================
# ОСНОВНЫЕ ФУНКЦИИ ДЛЯ РАБОТЫ С API
# ============================================================================

def check_token() -> bool:
    """Проверяет валидность токена, запрашивая список кампаний."""
    logger.info("=" * 80)
    logger.info("🔍 ПРОВЕРКА ТОКЕНА")
    logger.info("=" * 80)
    logger.info(f"Токен: {TOKEN[:15]}... (длина: {len(TOKEN)})")
    logger.info(f"API URL: {API_URL}")

    request_data = {
        "method": "get",
        "params": {
            "SelectionCriteria": {},
            "FieldNames": ["Id", "Name", "Status"]
        }
    }

    logger.info("\n📦 Отправка запроса...")
    try:
        response = requests.post(
            f'{API_URL}/campaigns',
            headers=HEADERS,
            json=request_data,
            timeout=30
        )
    except Exception as e:
        logger.error(f"❌ Ошибка соединения: {e}")
        return False

    data = log_request(response, "Проверка кампаний", request_data)

    if not is_success_response(data):
        logger.error("❌ Токен не работает или произошла ошибка API")
        return False

    # Если ответ успешный, но кампаний может и не быть — это нормально
    campaigns = data.get('result', {}).get('Campaigns', [])
    logger.info(f"\n✅ Токен работает! Найдено кампаний: {len(campaigns)}")
    return True


def create_campaign(name: str, budget: int = 5000) -> Optional[int]:
    """Создаёт текстовую кампанию, возвращает её ID или None."""
    logger.info("=" * 80)
    logger.info(f"📋 Создание кампании: {name}")
    logger.info("=" * 80)

    request_data = {
        "method": "add",
        "params": {
            "Campaigns": [
                {
                    "Name": name,
                    "StartDate": START_DATE,
                    "TextCampaign": {
                        "BiddingStrategy": {
                            "Search": {
                                "BiddingStrategyType": "AVERAGE_CPC",
                                "AverageCpc": {
                                    "AverageCpc": 30000000,        # 30 руб за клик
                                    "WeeklySpendLimit": 2000000000  # 2000 руб/неделю ≈ 285 руб/день
                                }
                            },
                            "Network": {
                                "BiddingStrategyType": "SERVING_OFF"
                            }
                        }
                    },
                }
            ]
        }
    }

    try:
        response = requests.post(
            f'{API_URL}/campaigns',
            headers=HEADERS,
            json=request_data,
            timeout=30
        )
    except Exception as e:
        logger.error(f"❌ Ошибка соединения при создании кампании: {e}")
        return None

    data = log_request(response, "Создание кампании", request_data)

    if not is_success_response(data):
        logger.error("❌ Не удалось создать кампанию")
        return None

    campaign_id = extract_campaign_id(data)
    if campaign_id:
        logger.info(f"\n✅ Кампания создана! ID: {campaign_id}")
    else:
        logger.error("❌ Кампания создана, но ID не получен (структура ответа неожиданная)")
    return campaign_id


def create_ad_group(campaign_id: int, name: str) -> Optional[int]:
    """Создаёт группу объявлений в кампании, возвращает ID группы или None."""
    logger.info("=" * 80)
    logger.info(f"📦 Создание группы: {name}")
    logger.info("=" * 80)

    request_data = {
        "method": "add",
        "params": {
            "AdGroups": [
                {
                    "CampaignId": campaign_id,
                    "Name": name,
                    "RegionIds": [1]
                }
            ]
        }
    }

    try:
        response = requests.post(
            f'{API_URL}/adgroups',
            headers=HEADERS,
            json=request_data,
            timeout=30
        )
    except Exception as e:
        logger.error(f"❌ Ошибка соединения при создании группы: {e}")
        return None

    data = log_request(response, "Создание группы", request_data)

    if not is_success_response(data):
        logger.error("❌ Не удалось создать группу")
        return None

    ad_group_id = extract_ad_group_id(data)
    if ad_group_id:
        logger.info(f"\n✅ Группа создана! ID: {ad_group_id}")
    else:
        logger.error("❌ Группа создана, но ID не получен")
    return ad_group_id


def create_keywords(ad_group_id: int, keywords_list: List[str]) -> bool:
    """Добавляет ключевые слова в группу. Возвращает True при успехе."""
    logger.info("=" * 80)
    logger.info(f"🔑 Добавление ключевых слов ({len(keywords_list)} шт)")
    logger.info("=" * 80)

    request_data = {
        "method": "add",
        "params": {
            "Keywords": [
                {
                    "AdGroupId": ad_group_id,
                    "Keyword": keyword
                }
                for keyword in keywords_list
            ]
        }
    }

    try:
        response = requests.post(
            f'{API_URL}/keywords',
            headers=HEADERS,
            json=request_data,
            timeout=30
        )
    except Exception as e:
        logger.error(f"❌ Ошибка соединения при добавлении ключевых слов: {e}")
        return False

    data = log_request(response, "Добавление ключевых слов", request_data)
    return is_success_response(data)


def create_ads(ad_group_id: int, ads_list: List[Dict[str, str]]) -> bool:
    """Создаёт несколько текстовых объявлений в группе. Возвращает True, если все успешны."""
    logger.info("=" * 80)
    logger.info(f"📢 Создание объявлений ({len(ads_list)} шт)")
    logger.info("=" * 80)

    all_success = True
    for ad in ads_list:
        request_data = {
            "method": "add",
            "params": {
                "Ads": [
                    {
                        "AdGroupId": ad_group_id,
                        "TextAd": {
                            "Title": ad['title1'],
                            "Title2": ad['title2'],
                            "Text": ad['text'],
                            "Href": ad['link']
                        }
                    }
                ]
            }
        }

        try:
            response = requests.post(
                f'{API_URL}/ads',
                headers=HEADERS,
                json=request_data,
                timeout=30
            )
        except Exception as e:
            logger.error(f"❌ Ошибка соединения при создании объявления '{ad['title1']}': {e}")
            all_success = False
            continue

        data = log_request(response, f"Объявление: {ad['title1']}", request_data)

        if is_success_response(data):
            logger.info(f"\n✅ Объявление: {ad['title1']} создано")
        else:
            logger.error(f"\n❌ Ошибка при создании объявления: {ad['title1']}")
            all_success = False

    return all_success


# ============================================================================
# ОСНОВНОЙ БЛОК
# ============================================================================

def main():
    logger.info("=" * 80)
    logger.info("🚀 Yandex Direct API v5 — С ЛОГИРОВАНИЕМ (v7, исправленная)")
    logger.info("Для: Бумажные пакеты (Москва)")
    logger.info(f"Сайт: https://pakety.shop")
    logger.info(f"API: {API_URL}")
    logger.info(f"Дата старта: {START_DATE}")
    logger.info(f"Лог файл: {LOG_FILE.absolute()}")
    logger.info("=" * 80)

    if not TOKEN or len(TOKEN) < 10:
        logger.error("\n❌ Ошибка: Токен не указан или слишком короткий!")
        return

    # Проверка токена
    if not check_token():
        logger.error("\n❌ Токен недействителен. Дальнейшая работа невозможна.")
        logger.error("\n💡 Возможные причины:")
        logger.error("   1. Токен не имеет права direct:api")
        logger.error("   2. Токен отозван")
        logger.error("   3. Неверный формат токена")
        logger.error("   4. Проблемы с заголовком Client-Login (попробуйте закомментировать его в коде)")
        logger.error("\n🔗 Получите новый токен:")
        logger.error("   https://oauth.yandex.ru/authorize?response_type=token&client_id=cad1a6b81d09476bb649cb4eb45085db&scope=direct:api")
        return

    # Данные для кампаний
    campaigns = [
        {
            'name': 'B2B — Магазины и ритейл',
            'budget': 5000,
            'keywords': [
                'бумажные пакеты оптом',
                'крафт пакеты для магазинов',
                'пакеты бумажные купить москва',
                'упаковка бумажная оптом',
                'крафт пакеты производитель',
            ],
            'ads': [
                {
                    'title1': 'Бумажные пакеты оптом',
                    'title2': 'Производство Москва. От 100 шт',
                    'text': 'Крафт пакеты для магазинов. Нанесение логотипа. Скидки от объёма! Доставка по РФ.',
                    'link': 'https://pakety.shop'
                },
                {
                    'title1': 'Крафт пакеты для магазинов',
                    'title2': 'В наличии все размеры',
                    'text': 'Экологичная упаковка для вашего бизнеса. Цены от производителя. Звоните!',
                    'link': 'https://pakety.shop'
                },
                {
                    'title1': 'Пакеты бумажные от производителя',
                    'title2': 'Изготовим за 3-5 дней',
                    'text': 'Любые размеры и цвета. Брендирование. Образцы бесплатно!',
                    'link': 'https://pakety.shop'
                }
            ]
        },
        {
            'name': 'B2B — Рестораны и кафе',
            'budget': 5000,
            'keywords': [
                'упаковка для еды оптом',
                'пакеты для доставки ресторан',
                'бумажная упаковка для кафе',
                'пакеты для хо река',
                'упаковка для доставки еды',
            ],
            'ads': [
                {
                    'title1': 'Упаковка для доставки еды',
                    'title2': 'Бумажные пакеты для ресторанов',
                    'text': 'Термостойкие, прочные. Любые размеры. Спеццены для HoReCa!',
                    'link': 'https://pakety.shop'
                },
                {
                    'title1': 'Пакеты для кафе и ресторанов',
                    'title2': 'С логотипом за 3 дня',
                    'text': 'Экологичная упаковка для доставки. Нанесение бренда. Скидки!',
                    'link': 'https://pakety.shop'
                }
            ]
        },
        {
            'name': 'B2B — Брендированные пакеты',
            'budget': 5000,
            'keywords': [
                'пакеты с логотипом на заказ',
                'печать на бумажных пакетах',
                'брендированные пакеты оптом',
                'пакеты с принтом москва',
                'рекламные пакеты бумажные',
            ],
            'ads': [
                {
                    'title1': 'Пакеты с логотипом на заказ',
                    'title2': 'Печать на бумажных пакетах',
                    'text': 'Разработаем дизайн. Тираж от 100 шт. Бесплатные макеты!',
                    'link': 'https://pakety.shop'
                },
                {
                    'title1': 'Брендированные пакеты оптом',
                    'title2': 'Реклама вашего бренда',
                    'text': 'Качественная печать. Любые цвета. Изготовление 5-7 дней.',
                    'link': 'https://pakety.shop'
                }
            ]
        }
    ]

    # Создание кампаний
    for campaign in campaigns:
        logger.info(f"\n{'='*80}")
        logger.info(f"📋 КАМПАНИЯ: {campaign['name']}")
        logger.info(f"{'='*80}")

        campaign_id = create_campaign(name=campaign['name'], budget=campaign['budget'])

        if campaign_id:
            ad_group_id = create_ad_group(
                campaign_id=campaign_id,
                name=f"Группа 1 — {campaign['name']}"
            )

            if ad_group_id:
                create_keywords(
                    ad_group_id=ad_group_id,
                    keywords_list=campaign['keywords']
                )

                create_ads(
                    ad_group_id=ad_group_id,
                    ads_list=campaign['ads']
                )
        else:
            logger.warning("  ⚠️ Пропускаем группу и объявления (не удалось создать кампанию)")

    logger.info("\n" + "=" * 80)
    logger.info("✅ РАБОТА ЗАВЕРШЕНА")
    logger.info("=" * 80)
    logger.info("\n📌 Следующие шаги:")
    logger.info(f"1. Проверить лог файл: {LOG_FILE.absolute()}")
    logger.info("2. Зайти в Песочницу: https://api-sandbox.direct.yandex.ru/")
    logger.info("3. Проверить созданные кампании (если токен работал)")
    logger.info("=" * 80)

    print(f"\n📁 Лог сохранён в: {LOG_FILE.absolute()}")


if __name__ == '__main__':
    main()