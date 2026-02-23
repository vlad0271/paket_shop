from pathlib import Path
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List
from app import schemas, crud
from app.database import get_db

router = APIRouter(prefix="/api", tags=["packages"])

_IMAGES_DIR = Path(__file__).resolve().parent.parent.parent / "static" / "images"
_IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.webp', '.gif'}


@router.get("/images")
def list_images():
    """Список URL всех изображений из static/images."""
    if not _IMAGES_DIR.exists():
        return []
    files = sorted(f.name for f in _IMAGES_DIR.iterdir() if f.suffix.lower() in _IMAGE_EXTS)
    return [f"/static/images/{name}" for name in files]

@router.get("/packages", response_model=List[schemas.Package])
def list_packages(db: Session = Depends(get_db)):
    return crud.get_packages(db)

@router.get("/packages/{package_id}", response_model=schemas.Package)
def get_package(package_id: int, db: Session = Depends(get_db)):
    return crud.get_package(db, package_id)

@router.get("/options", response_model=List[schemas.Option])
def list_options(db: Session = Depends(get_db)):
    return crud.get_options(db)
