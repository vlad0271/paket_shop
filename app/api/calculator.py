from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app import schemas, crud
from app.database import get_db

router = APIRouter(prefix="/api", tags=["calculator"])

@router.post("/calculate", response_model=schemas.CalculateResponse)
def calculate_price(request: schemas.CalculateRequest, db: Session = Depends(get_db)):
    pricing = crud.get_pricing(db, request.bottles, request.quantity)

    if not pricing:
        base_price = 100.0
        discount_percent = 0.0
    else:
        base_price = pricing.base_price
        discount_percent = pricing.discount_percent

    price_modifiers = 0.0
    options = crud.get_options(db)

    for option in options:
        if option.category == "paper" and option.value == request.paper_type:
            price_modifiers += option.price_modifier
        elif option.category == "color" and option.value == request.color:
            price_modifiers += option.price_modifier
        elif option.category == "handle" and option.value == request.handle_type:
            price_modifiers += option.price_modifier
        elif option.category == "print" and request.has_print and option.value == "yes":
            price_modifiers += option.price_modifier

    unit_price = base_price + price_modifiers
    total_before_discount = unit_price * request.quantity
    total_price = total_before_discount * (1 - discount_percent / 100)

    return schemas.CalculateResponse(
        unit_price=unit_price,
        total_price=total_price,
        quantity=request.quantity,
        discount_percent=discount_percent
    )
