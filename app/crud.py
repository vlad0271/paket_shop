from sqlalchemy.orm import Session
from app import models, schemas

def get_packages(db: Session):
    return db.query(models.Package).all()

def get_package(db: Session, package_id: int):
    return db.query(models.Package).filter(models.Package.id == package_id).first()

def get_options(db: Session):
    return db.query(models.Option).all()

def get_options_by_category(db: Session, category: str):
    return db.query(models.Option).filter(models.Option.category == category).all()

def get_pricing(db: Session, bottles: int, quantity: int):
    pricing = db.query(models.Pricing).filter(
        models.Pricing.bottles == bottles,
        models.Pricing.quantity_from <= quantity
    ).filter(
        (models.Pricing.quantity_to >= quantity) | (models.Pricing.quantity_to == None)
    ).first()
    return pricing

def create_order(db: Session, order: schemas.OrderCreate):
    db_order = models.Order(**order.model_dump())
    db.add(db_order)
    db.commit()
    db.refresh(db_order)
    return db_order

def get_order(db: Session, order_id: int):
    return db.query(models.Order).filter(models.Order.id == order_id).first()

def get_orders(db: Session, skip: int = 0, limit: int = 100):
    return db.query(models.Order).offset(skip).limit(limit).all()
