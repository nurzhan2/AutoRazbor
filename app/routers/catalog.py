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
    make: str = "",
    model: str = "",
    generation: str = "",
    spare_part_type: str = "",
    oem: str = "",
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

    # Structured carro.by-style filters
    if make:
        query = query.where(Product.make == make)
    if model:
        query = query.where(Product.model == model)
    if generation:
        query = query.where(Product.generation == generation)
    if spare_part_type:
        query = query.where(Product.spare_part_type == spare_part_type)
    if oem.strip():
        oem_term = oem.strip()
        query = query.where(
            or_(
                Product.oem.ilike(f"%{oem_term}%"),
                Product.article.ilike(f"%{oem_term}%"),
                Product.description.ilike(f"%{oem_term}%"),
            )
        )

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

    # --- Dropdown options for carro.by-style filter form ---

    # Марка (brand) - all active products
    make_result = await db.execute(
        select(Product.make).distinct()
        .where(Product.is_active == True, Product.make != None, Product.make != "")
        .order_by(Product.make)
    )
    makes = [r[0] for r in make_result.fetchall()]

    # Модель - depends on selected Марка
    model_query = select(Product.model).distinct().where(
        Product.is_active == True, Product.model != None, Product.model != ""
    )
    if make:
        model_query = model_query.where(Product.make == make)
    model_result = await db.execute(model_query.order_by(Product.model))
    models = [r[0] for r in model_result.fetchall()]

    # Поколение - depends on selected Марка + Модель
    gen_query = select(Product.generation).distinct().where(
        Product.is_active == True, Product.generation != None, Product.generation != ""
    )
    if make:
        gen_query = gen_query.where(Product.make == make)
    if model:
        gen_query = gen_query.where(Product.model == model)
    gen_result = await db.execute(gen_query.order_by(Product.generation))
    generations = [r[0] for r in gen_result.fetchall()]

    # Категория запчастей
    spt_result = await db.execute(
        select(Product.spare_part_type).distinct()
        .where(Product.is_active == True, Product.spare_part_type != None, Product.spare_part_type != "")
        .order_by(Product.spare_part_type)
    )
    spare_part_types = [r[0] for r in spt_result.fetchall()]

    # Legacy category dropdown (kept for backward compatibility)
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
            "make": make,
            "model": model,
            "generation": generation,
            "spare_part_type": spare_part_type,
            "oem": oem,
            "category": category,
            "min_price": min_price,
            "max_price": max_price,
            "sort": sort,
            "makes": makes,
            "models": models,
            "generations": generations,
            "spare_part_types": spare_part_types,
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