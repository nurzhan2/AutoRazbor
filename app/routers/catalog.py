import json
from fastapi import APIRouter, Request, Depends, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, func

from app.models.database import get_db
from app.models.models import Product, SyncLog
from app.routers.auth import get_current_user_from_cookie
from app.routers.dashboard import require_user

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

ITEMS_PER_PAGE = 100


@router.get("/catalog", response_class=HTMLResponse)
async def catalog(
    request: Request,
    db: AsyncSession = Depends(get_db),
    search: str = "",
    category: str = "",
    min_price: str = "",
    max_price: str = "",
    sort: str = "updated_desc",
    page: int = 1,
):
    user, redirect = await require_user(request, db)
    if redirect:
        return redirect

    query = select(Product).where(Product.is_active == True)

    if search:
        # Transliteration map: russian brand names -> english
        translit = {
            "вольво": "volvo", "волво": "volvo", "volvo": "volvo",
            "бмв": "bmw", "мерседес": "mercedes", "мерс": "mercedes",
            "ауди": "audi", "тойота": "toyota", "киа": "kia",
            "хонда": "honda", "ниссан": "nissan", "митсубиси": "mitsubishi",
            "лексус": "lexus", "порше": "porsche", "фольксваген": "volkswagen",
            "шкода": "skoda", "рено": "renault", "пежо": "peugeot",
            "лэнд ровер": "land rover", "ленд ровер": "land rover",
            "рейндж ровер": "range rover", "рендж ровер": "range rover",
            "хюндай": "hyundai", "хундай": "hyundai", "хендай": "hyundai",
            "джип": "jeep", "форд": "ford", "опель": "opel",
            "сузуки": "suzuki", "мазда": "mazda", "субару": "subaru",
            "инфинити": "infiniti", "акура": "acura", "бентли": "bentley",
            # Parts transliteration - normalize common misspellings
            "полуось": "полус", "полусь": "полус", "полось": "полус",
            "рычаг": "рычаг", "амортизатор": "амортизатор",
            "двигатель": "двигател", "коробка": "коробк",
            "кузов": "кузов", "фара": "фар", "капот": "капот",
            "крыло": "крыл", "дверь": "двер", "стекло": "стекл",
            "бампер": "бампер", "колесо": "колес", "колёса": "колес",
            "диск": "диск", "тормоз": "тормоз", "подвеска": "подвеск",
        }
        search_lower = search.lower()
        words = [w.strip() for w in search_lower.split() if len(w.strip()) >= 2]

        for word in words:
            # Build variants: original word + transliterated version (if different)
            variants = {word}
            translated = word
            for ru, en in translit.items():
                translated = translated.replace(ru, en)
            variants.add(translated)

            conditions = []
            for variant in variants:
                conditions.extend([
                    Product.title.ilike(f"%{variant}%"),
                    Product.article.ilike(f"%{variant}%"),
                    Product.description.ilike(f"%{variant}%"),
                ])
            # AND between words, OR between variants/fields
            query = query.where(or_(*conditions))
    if category:
        query = query.where(Product.category == category)
    if min_price.strip():
        try:
            mp = float(min_price)
            if mp > 0:
                query = query.where(Product.price >= mp)
        except ValueError:
            pass
    if max_price.strip():
        try:
            mxp = float(max_price)
            if mxp > 0:
                query = query.where(Product.price <= mxp)
        except ValueError:
            pass

    if sort == "price_asc":
        query = query.order_by(Product.price.asc())
    elif sort == "price_desc":
        query = query.order_by(Product.price.desc())
    else:
        query = query.order_by(Product.updated_at.desc())

    # Total count
    count_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = count_result.scalar()

    # Pagination
    offset = (page - 1) * ITEMS_PER_PAGE
    query = query.offset(offset).limit(ITEMS_PER_PAGE)
    result = await db.execute(query)
    products = result.scalars().all()

    # Decode photos
    for p in products:
        try:
            p._photos_list = json.loads(p.photos or "[]")[:1]
        except Exception:
            p._photos_list = []

    # Categories for filter
    cat_result = await db.execute(
        select(Product.category).distinct().where(Product.is_active == True, Product.category != None)
    )
    categories = [r[0] for r in cat_result.fetchall()]

    # Last sync
    sync_result = await db.execute(
        select(SyncLog).where(SyncLog.status == "success").order_by(SyncLog.finished_at.desc()).limit(1)
    )
    last_sync = sync_result.scalar_one_or_none()

    total_pages = (total + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE

    return templates.TemplateResponse(
        "catalog/list.html",
        {
            "request": request,
            "user": user,
            "products": products,
            "search": search,
            "category": category,
            "min_price": min_price,
            "max_price": max_price,
            "sort": sort,
            "categories": categories,
            "page": page,
            "total_pages": total_pages,
            "total": total,
            "last_sync": last_sync,
        },
    )


@router.get("/catalog/{product_id}", response_class=HTMLResponse)
async def product_detail(
    product_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user, redirect = await require_user(request, db)
    if redirect:
        return redirect

    result = await db.execute(select(Product).where(Product.id == product_id))
    product = result.scalar_one_or_none()
    if not product or not product.is_active:
        return RedirectResponse("/catalog", status_code=302)

    try:
        product._photos_list = json.loads(product.photos or "[]")
    except Exception:
        product._photos_list = []
    try:
        raw_chars = json.loads(product.characteristics or "{}")
    except Exception:
        raw_chars = {}

    CHAR_LABELS = {
        "Make": "Марка",
        "Model": "Модель",
        "Generation": "Поколение",
        "Year": "Год",
        "Condition": "Состояние",
        "GoodsType": "Тип товара",
        "ProductType": "Категория",
        "SparePartType": "Тип запчасти",
        "OEM": "OEM номер",
        "Brand": "Бренд",
        "EngineType": "Тип двигателя",
        "BodyType": "Тип кузова",
        "FuelType": "Тип топлива",
        "Transmission": "Коробка передач",
        "Color": "Цвет",
        "Country": "Страна",
        "EngineVolume": "Объём двигателя",
        # XLS-feed columns (Cyrillic) pass through as-is
    }
    product._chars = {}
    for key, val in raw_chars.items():
        # Drop noisy "*SparePartType" sub-fields that just repeat SparePartType info
        if key.endswith("SparePartType") and key != "SparePartType":
            label = "Узел"
        else:
            label = CHAR_LABELS.get(key, key)
        product._chars[label] = val

    # Записать в историю просмотров
    from app.models.models import ViewHistory
    db.add(ViewHistory(user_id=user.id, product_id=product.id))
    await db.commit()

    # Получить статус избранного
    from app.models.models import FavoriteProduct
    fav_result = await db.execute(
        select(FavoriteProduct).where(
            FavoriteProduct.user_id == user.id,
            FavoriteProduct.product_id == product.id
        )
    )
    is_favorite = fav_result.scalar_one_or_none() is not None

    return templates.TemplateResponse(
        "catalog/detail.html",
        {"request": request, "user": user, "product": product, "is_favorite": is_favorite},
    )