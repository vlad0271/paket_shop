import os
from pathlib import Path
from app.database import SessionLocal, init_db
from app.models import Package, Option, Pricing

def get_image_files():
    """Получить список всех изображений из папки static/images (путь совпадает с app.main)"""
    project_root = Path(__file__).resolve().parent
    images_dir = project_root / "static" / "images"
    if os.environ.get("STATIC_IMAGES_DIR"):
        images_dir = Path(os.environ.get("STATIC_IMAGES_DIR")).resolve()
    
    image_extensions = ['.jpg', '.jpeg', '.png', '.webp', '.gif']
    image_files = []
    
    print(f"Ищем изображения в: {images_dir}")
    print(f"Директория существует: {images_dir.exists()}")
    
    if images_dir.exists():
        # suffixes() на Windows не даёт дублей в отличие от glob("*.jpg") + glob("*.JPG")
        seen = set()
        for f in images_dir.iterdir():
            if f.suffix.lower() in image_extensions and f.name not in seen:
                seen.add(f.name)
                image_files.append(f)
    else:
        print(f"⚠️  Директория {images_dir} не существует!")
        print("Создайте папку static/images/ и добавьте туда изображения")

    # Сортируем по имени файла
    image_files = sorted([str(f.name) for f in image_files])
    return image_files

def init_sample_data():
    init_db()
    db = SessionLocal()

    try:
        existing_packages = db.query(Package).count()
        if existing_packages > 0:
            print("База данных уже содержит данные")
            return

        # Получаем список изображений
        image_files = get_image_files()
        print(f"Найдено изображений: {len(image_files)}")
        if image_files:
            for img in image_files:
                print(f"  - {img}")

        # Создаем пакеты с реальными изображениями
        packages_data = [
            {
                "name": "Классический пакет на 1 бутылку",
                "bottles": 1,
                "paper_type": "standard",
                "color": "brown",
                "handle_type": "rope",
                "has_print": False,
                "image_name": "package1.jpg",
                "base_price": 150.0
            },
            {
                "name": "Подарочный пакет на 2 бутылки",
                "bottles": 2,
                "paper_type": "premium",
                "color": "white",
                "handle_type": "ribbon",
                "has_print": True,
                "image_name": "package2.jpg",
                "base_price": 280.0
            },
            {
                "name": "Большой пакет на 3 бутылки",
                "bottles": 3,
                "paper_type": "standard",
                "color": "brown",
                "handle_type": "rope",
                "has_print": False,
                "image_name": "package3.jpg",
                "base_price": 350.0
            },
        ]

        packages = []
        for i, pkg_data in enumerate(packages_data):
            # Ищем изображение для этого пакета
            image_url = None
            
            # Сначала ищем точное совпадение
            if pkg_data["image_name"] in image_files:
                image_url = f"/static/images/{pkg_data['image_name']}"
            else:
                # Ищем изображение по индексу (package1.jpg, package2.jpg и т.д.)
                for img_file in image_files:
                    if f"package{i+1}" in img_file.lower() or f"paket{i+1}" in img_file.lower():
                        image_url = f"/static/images/{img_file}"
                        break
                
                # Если не нашли, берем первое доступное изображение
                if not image_url and image_files:
                    image_url = f"/static/images/{image_files[i % len(image_files)]}"
                elif not image_url:
                    # Если изображений нет, используем заглушку
                    image_url = "/static/images/default.jpg"
            
            packages.append(Package(
                name=pkg_data["name"],
                bottles=pkg_data["bottles"],
                paper_type=pkg_data["paper_type"],
                color=pkg_data["color"],
                handle_type=pkg_data["handle_type"],
                has_print=pkg_data["has_print"],
                image_url=image_url,
                base_price=pkg_data["base_price"]
            ))

        options = [
            Option(category="paper",  name="Крафт бумага",      value="kraft",  price_modifier=0.0),
            Option(category="paper",  name="Мелованная бумага",  value="coated", price_modifier=20.0),
            Option(category="color",  name="Коричневый",         value="brown",  price_modifier=0.0),
            Option(category="color",  name="Белый",              value="white",  price_modifier=0.0),
            Option(category="color",  name="Черный",             value="black",  price_modifier=15.0),
            Option(category="color",  name="Оранжевый",          value="orange", price_modifier=10.0),
            Option(category="handle", name="Веревочные ручки",   value="rope",   price_modifier=0.0),
            Option(category="handle", name="Ленточные ручки",    value="ribbon", price_modifier=20.0),
            Option(category="print",  name="С печатью",          value="yes",    price_modifier=50.0),
        ]

        pricing_rules = [
            Pricing(bottles=1, base_price=150.0, quantity_from=1, quantity_to=49, discount_percent=0.0),
            Pricing(bottles=1, base_price=150.0, quantity_from=50, quantity_to=99, discount_percent=5.0),
            Pricing(bottles=1, base_price=150.0, quantity_from=100, quantity_to=None, discount_percent=10.0),
            Pricing(bottles=2, base_price=250.0, quantity_from=1, quantity_to=49, discount_percent=0.0),
            Pricing(bottles=2, base_price=250.0, quantity_from=50, quantity_to=99, discount_percent=5.0),
            Pricing(bottles=2, base_price=250.0, quantity_from=100, quantity_to=None, discount_percent=10.0),
            Pricing(bottles=3, base_price=350.0, quantity_from=1, quantity_to=49, discount_percent=0.0),
            Pricing(bottles=3, base_price=350.0, quantity_from=50, quantity_to=99, discount_percent=5.0),
            Pricing(bottles=3, base_price=350.0, quantity_from=100, quantity_to=None, discount_percent=10.0),
        ]

        db.add_all(packages)
        db.add_all(options)
        db.add_all(pricing_rules)
        db.commit()

        print("База данных инициализирована с тестовыми данными")
        print(f"Добавлено пакетов: {len(packages)}")
        print(f"Добавлено опций: {len(options)}")
        print(f"Добавлено правил цен: {len(pricing_rules)}")

    except Exception as e:
        print(f"Ошибка при инициализации данных: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    init_sample_data()
