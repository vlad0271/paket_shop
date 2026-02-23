from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime
from datetime import datetime
from app.database import Base

class Package(Base):
    __tablename__ = "packages"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    bottles = Column(Integer, nullable=False)
    paper_type = Column(String, nullable=False)
    color = Column(String, nullable=False)
    handle_type = Column(String, nullable=False)
    has_print = Column(Boolean, default=False)
    image_url = Column(String, nullable=True)
    base_price = Column(Float, nullable=False)

class Option(Base):
    __tablename__ = "options"

    id = Column(Integer, primary_key=True, index=True)
    category = Column(String, nullable=False)
    name = Column(String, nullable=False)
    value = Column(String, nullable=False)
    price_modifier = Column(Float, default=0.0)

class Pricing(Base):
    __tablename__ = "pricing"

    id = Column(Integer, primary_key=True, index=True)
    bottles = Column(Integer, nullable=False)
    base_price = Column(Float, nullable=False)
    quantity_from = Column(Integer, nullable=False)
    quantity_to = Column(Integer, nullable=True)
    discount_percent = Column(Float, default=0.0)

class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    customer_name = Column(String, nullable=False)
    customer_phone = Column(String, nullable=False)
    customer_email = Column(String, nullable=True)
    bottles = Column(Integer, nullable=False)
    bag_size = Column(String, nullable=True)
    custom_width = Column(Integer, nullable=True)
    custom_length = Column(Integer, nullable=True)
    custom_height = Column(Integer, nullable=True)
    paper_type = Column(String, nullable=False)
    color = Column(String, nullable=False)
    handle_type = Column(String, nullable=False)
    has_print = Column(Boolean, default=False)
    quantity = Column(Integer, nullable=False)
    total_price = Column(Float, nullable=False)
    status = Column(String, default="new")
    created_at = Column(DateTime, default=datetime.utcnow)
