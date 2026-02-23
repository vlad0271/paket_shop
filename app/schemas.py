from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime

class PackageBase(BaseModel):
    name: str
    bottles: int
    paper_type: str
    color: str
    handle_type: str
    has_print: bool
    image_url: Optional[str] = None
    base_price: float

class Package(PackageBase):
    id: int

    class Config:
        from_attributes = True

class OptionBase(BaseModel):
    category: str
    name: str
    value: str
    price_modifier: float = 0.0

class Option(OptionBase):
    id: int

    class Config:
        from_attributes = True

class CalculateRequest(BaseModel):
    bottles: int
    paper_type: str
    color: str
    handle_type: str
    has_print: bool
    quantity: int

class CalculateResponse(BaseModel):
    unit_price: float
    total_price: float
    quantity: int
    discount_percent: float = 0.0

class OrderCreate(BaseModel):
    customer_name: str
    customer_phone: str
    customer_email: Optional[EmailStr] = None
    bottles: int
    bag_size: Optional[str] = None
    custom_width: Optional[int] = None
    custom_length: Optional[int] = None
    custom_height: Optional[int] = None
    paper_type: str
    color: str
    handle_type: str
    has_print: bool
    quantity: int
    total_price: float

class Order(OrderCreate):
    id: int
    status: str
    created_at: datetime

    class Config:
        from_attributes = True
