import urllib.request
import urllib.parse
import json
import logging
import os
import yaml
from pathlib import Path

_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"


def _load_size_labels() -> dict:
    with open(_CONFIG_PATH, encoding="utf-8") as f:
        config = yaml.safe_load(f)
    return {
        s["key"]: f"{s['width']}×{s['length']}×{s['height']} мм"
        for s in config.get("standard_sizes", [])
    }


def send_order_notification(order) -> None:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]

    if order.bag_size == 'unknown':
        text = (
            f"📦 Новый запрос #{order.id}\n\n"
            f"👤 {order.customer_name}\n"
            f"📞 {order.customer_phone}\n"
            f"📧 {order.customer_email or '—'}\n\n"
            f"Размеров не знаю, свяжитесь со мной"
        )
    else:
        print_text = "Да" if order.has_print else "Нет"
        size_labels = _load_size_labels()
        if order.custom_width:
            package_line = f"Пакет: произвольный {order.custom_width}×{order.custom_length}×{order.custom_height} мм"
        elif order.bag_size:
            package_line = f"Пакет: стандартный {size_labels.get(order.bag_size, order.bag_size)}"
        else:
            package_line = f"Бутылок: {order.bottles}"
        text = (
            f"📦 Новый заказ #{order.id}\n\n"
            f"👤 {order.customer_name}\n"
            f"📞 {order.customer_phone}\n"
            f"📧 {order.customer_email or '—'}\n\n"
            f"{package_line}\n"
            f"Бумага: {order.paper_type}\n"
            f"Цвет: {order.color}\n"
            f"Ручки: {order.handle_type}\n"
            f"Печать: {print_text}\n"
            f"Количество: {order.quantity} шт.\n"
            f"💰 Сумма: {order.total_price:.2f} руб."
        )

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = json.dumps({"chat_id": chat_id, "text": text}).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})

    with urllib.request.urlopen(req, timeout=10) as resp:
        result = json.loads(resp.read())

    if not result.get("ok"):
        raise RuntimeError(f"Telegram API error: {result}")

    logging.info(f"Уведомление о заказе #{order.id} отправлено в Telegram")
