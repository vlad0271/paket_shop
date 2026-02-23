from sqlalchemy import create_engine, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

DATABASE_URL = "sqlite:///./database/paket.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    Base.metadata.create_all(bind=engine)
    # Миграция: добавляем bag_size если столбца ещё нет
    migrations = [
        "ALTER TABLE orders ADD COLUMN bag_size VARCHAR",
        "ALTER TABLE orders ADD COLUMN custom_width INTEGER",
        "ALTER TABLE orders ADD COLUMN custom_length INTEGER",
        "ALTER TABLE orders ADD COLUMN custom_height INTEGER",
    ]
    with engine.connect() as conn:
        for sql in migrations:
            try:
                conn.execute(text(sql))
                conn.commit()
            except Exception:
                pass  # столбец уже существует
