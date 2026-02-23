"""Обновляет опции бумаги и цвета в БД."""
from app.database import SessionLocal, init_db
from app.models import Option

def run():
    init_db()
    db = SessionLocal()
    try:
        # Удаляем старые опции бумаги и цвета
        db.query(Option).filter(Option.category.in_(["paper", "color"])).delete()

        new_options = [
            Option(category="paper", name="Крафт бумага",     value="kraft",  price_modifier=0.0),
            Option(category="paper", name="Мелованная бумага", value="coated", price_modifier=20.0),
            Option(category="color", name="Коричневый",        value="brown",  price_modifier=0.0),
            Option(category="color", name="Белый",             value="white",  price_modifier=0.0),
            Option(category="color", name="Черный",            value="black",  price_modifier=15.0),
            Option(category="color", name="Оранжевый",         value="orange", price_modifier=10.0),
        ]
        db.add_all(new_options)
        db.commit()
        print("Опции обновлены:")
        for o in new_options:
            print(f"  [{o.category}] {o.name} ({o.value})")
    except Exception as e:
        print(f"Ошибка: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    run()
