import os
import yaml
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response
from app.api import packages, calculator, orders
from app.database import init_db

# Получаем абсолютный путь к корню проекта (папка paket)
BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "config.yaml"
STATIC_DIR = BASE_DIR / "static"
# Папка изображений — по умолчанию static/images; можно задать STATIC_IMAGES_DIR
STATIC_IMAGES_DIR = STATIC_DIR / "images"
if os.environ.get("STATIC_IMAGES_DIR"):
    STATIC_IMAGES_DIR = Path(os.environ.get("STATIC_IMAGES_DIR")).resolve()
FRONTEND_DIR = BASE_DIR / "frontend"

app = FastAPI(title="Craft Paper Package Store")

app.include_router(packages.router)
app.include_router(calculator.router)
app.include_router(orders.router)


# Заглушка «Нет изображения» (SVG) — видна в интерфейсе (строка: в bytes нельзя кириллицу)
PLACEHOLDER_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="280" height="200" viewBox="0 0 280 200">'
    '<rect fill="#f0f0f0" width="280" height="200"/>'
    '<text x="50%" y="50%" dominant-baseline="middle" text-anchor="middle" fill="#999" font-family="sans-serif" font-size="14">Нет изображения</text>'
    '</svg>'
)


@app.get("/static/images/{path:path}")
def serve_image(path: str):
    """Отдаёт файл из static/images или заглушку, если файла нет."""
    if ".." in path or path.startswith("/"):
        return Response(content=PLACEHOLDER_SVG.encode("utf-8"), media_type="image/svg+xml")
    file_path = STATIC_IMAGES_DIR / path
    if file_path.is_file():
        return FileResponse(str(file_path), media_type=None)
    return Response(content=PLACEHOLDER_SVG.encode("utf-8"), media_type="image/svg+xml")


# Монтируем только css/js/video — /static/images обрабатывает serve_image выше.
# Нельзя монтировать весь /static: Mount перехватит /static/images/* раньше Route.
for _subdir in ["css", "js", "video"]:
    _path = STATIC_DIR / _subdir
    if _path.exists():
        app.mount(f"/static/{_subdir}", StaticFiles(directory=str(_path)), name=_subdir)

@app.on_event("startup")
def startup_event():
    init_db()
    if not STATIC_DIR.exists():
        print(f"⚠️  Создайте директорию: {STATIC_DIR}")
    if not STATIC_IMAGES_DIR.exists():
        print(f"⚠️  Создайте директорию с изображениями: {STATIC_IMAGES_DIR}")
    else:
        print(f"[OK] Изображения загружаются из: {STATIC_IMAGES_DIR}")

@app.get("/api/contacts")
def get_contacts():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        config = yaml.safe_load(f)
    return config["contacts"]


@app.get("/api/standard-sizes")
def get_standard_sizes():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        config = yaml.safe_load(f)
    return config.get("standard_sizes", [])


@app.get("/api/card-images")
def get_card_images():
    """Возвращает списки фото для карточек 1/2/3 бутылки из static/images/cards/{n}/."""
    EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp'}
    result = {}
    cards_dir = STATIC_IMAGES_DIR / "cards"
    for bottles in ["1", "2", "3"]:
        folder = cards_dir / bottles
        images = []
        if folder.is_dir():
            for f in sorted(folder.iterdir()):
                if f.suffix.lower() in EXTENSIONS:
                    images.append(f"/static/images/cards/{bottles}/{f.name}")
        result[bottles] = images
    return result


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return FileResponse(str(STATIC_DIR / "favicon.svg"), media_type="image/svg+xml")


@app.get("/")
def read_root():
    index_file = FRONTEND_DIR / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    else:
        return {"error": f"Файл {index_file} не найден"}
