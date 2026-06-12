import os
import json
import logging
from datetime import datetime
from typing import Optional

import httpx
from lxml import etree
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, update

from app.models.models import Product, SyncLog
from app.models.database import AsyncSessionLocal

logger = logging.getLogger(__name__)

AVITO_FEED_URL = os.getenv("AVITO_FEED_URL", "")


async def run_catalog_sync(feed_url: Optional[str] = None) -> SyncLog:
    """Main entry point for catalog synchronization"""
    url = feed_url or AVITO_FEED_URL
    async with AsyncSessionLocal() as db:
        log = SyncLog(started_at=datetime.utcnow(), status="running")
        db.add(log)
        await db.commit()
        await db.refresh(log)

        try:
            content = await fetch_feed(url)
            items = parse_feed(content)

            added, updated, removed = await update_catalog(items)

            log.status = "success"
            log.products_added = added
            log.products_updated = updated
            log.products_removed = removed
            log.finished_at = datetime.utcnow()
            await db.commit()

            logger.info(f"Sync done: +{added} ~{updated} -{removed}")

            # Notify admin
            await notify_admin_sync_success(added, updated, removed)

        except Exception as e:
            log.status = "error"
            log.error_message = str(e)
            log.finished_at = datetime.utcnow()
            await db.commit()
            logger.error(f"Sync failed: {e}")
            await notify_admin_sync_error(str(e))

        return log


async def fetch_feed(url: str) -> bytes:
    if not url:
        raise ValueError("AVITO_FEED_URL not configured")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "*/*",
    }
    async with httpx.AsyncClient(timeout=60, headers=headers) as client:
        response = await client.get(url, follow_redirects=True)
        response.raise_for_status()
        if len(response.content) < 10:
            raise ValueError("Feed is empty")
        return response.content


def parse_feed(content: bytes):
    """Parse XML/YML/CSV/XLS/XLSX Avito feed. Returns an iterator/generator of product dicts."""
    # Detect XLS/XLSX by magic bytes
    if (content[:8] == b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1') or content[:2] == b'PK':
        return parse_xls_feed(content)

    # Try XML
    try:
        root = etree.fromstring(content)
    except etree.XMLSyntaxError:
        if b'\xd0\xcf\x11\xe0' in content[:8] or content[:4] == b'PK\x03\x04':
            return parse_xls_feed(content)
        return parse_csv_feed(content)

    items = []
    # Support standard Avito XML and YML (Yandex Market) formats
    for ad in root.iter("Ad"):
        items.append(parse_avito_xml_ad(ad))
    if not items:
        # YML format
        for offer in root.iter("offer"):
            items.append(parse_yml_offer(offer))
    if not items:
        raise ValueError("No items found in feed. Check feed format.")
    return iter(items)


def parse_xls_feed(content: bytes):
    """Parse XLS/XLSX Avito export file as a generator (memory efficient)."""
    import io

    # Try XLSX first (newer format)
    try:
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        ws = wb.active
        row_iter = ws.iter_rows(values_only=True)
        headers = None
        for row in row_iter:
            if headers is None:
                headers = [str(h).strip() if h else "" for h in row]
                continue
            if not any(row):
                continue
            item = _row_to_item(headers, row)
            if item:
                yield item
        wb.close()
        return
    except Exception as e:
        logger.info(f"openpyxl failed ({e}), trying xlrd")

    # Try XLS (old format) - xlrd loads whole workbook into memory regardless,
    # but we still yield row by row to avoid duplicating into a big list
    import xlrd
    wb = xlrd.open_workbook(file_contents=content)
    ws = wb.sheet_by_index(0)
    headers = [str(ws.cell_value(0, c)).strip() for c in range(ws.ncols)]
    for r in range(1, ws.nrows):
        row = [ws.cell_value(r, c) for c in range(ws.ncols)]
        if not any(row):
            continue
        item = _row_to_item(headers, row)
        if item:
            yield item


# Column name mappings for Avito XLS export
_COL_MAP = {
    "id": ["АРТИКУЛ", "АРТИКУЛ AVITO", "Id", "ID", "id"],
    "title": ["ЗАПЧАСТЬ", "ПРИМЕЧАНИЕ", "Title", "Название", "Наименование"],
    "description": ["ПРИМЕЧАНИЕ", "Description", "Описание"],
    "price": ["ЦЕНА", "ЦЕНА В РА", "Price", "Цена"],
    "photos": ["ФОТО", "ImageUrls", "Images", "Фото", "Изображения"],
    "category": ["АВТО", "МАРКА", "Category", "Категория"],
    "article": ["АРТИКУЛ AVITO", "ОРИГИНАЛЬНЫЙ НОМЕР", "АРТИКУЛ", "Article"],
    "avito_url": ["Url", "URL", "Ссылка"],
    "availability": ["В СБОРЕ", "Availability", "Наличие"],
}


def _row_to_item(headers: list, row: tuple) -> dict | None:
    row_dict = {headers[i]: row[i] for i in range(min(len(headers), len(row)))}

    def get(*keys):
        for k in keys:
            v = row_dict.get(k)
            if v is not None and str(v).strip():
                return str(v).strip()
        return None

    def get_col(field):
        return get(*_COL_MAP.get(field, []))

    ext_id = get_col("id")

    # Build title from МАРКА + МОДЕЛЬ + ЗАПЧАСТЬ
    marka = get("МАРКА") or ""
    model = get("МОДЕЛЬ") or ""
    zapchast = get("ЗАПЧАСТЬ") or ""
    god = get("ГОД") or ""
    title_parts = [p for p in [marka, model, zapchast, god] if p]
    title = " ".join(title_parts) if title_parts else get_col("title")

    if not ext_id and not title:
        return None

    # Build characteristics from available columns
    chars = {}
    for col in ["МАРКА", "МОДЕЛЬ", "ПОКОЛЕНИЕ", "ГОД", "ТИП ТОПЛИВА", "ОБЪЕМ", "ДВИГАТЕЛЬ", "ВПРЫСК", "ТОРМОЗА", "ТИП КУЗОВА", "РУЛЬ", "ПРИВОД", "ЦВЕТ", "СТРАНА"]:
        v = get(col)
        if v:
            chars[col] = v

    # Photos: may be comma/semicolon separated
    photos_raw = get_col("photos") or ""
    photos = [p.strip() for p in photos_raw.replace(";", ",").split(",") if p.strip()]

    return {
        "external_id": ext_id or title,
        "title": title or "Без названия",
        "description": get("ПРИМЕЧАНИЕ"),
        "price": _parse_price(get_col("price")),
        "photos": json.dumps(photos),
        "characteristics": json.dumps(chars, ensure_ascii=False),
        "category": get("МАРКА") or get_col("category"),
        "article": get("АРТИКУЛ AVITO") or get("ОРИГИНАЛЬНЫЙ НОМЕР") or get("АРТИКУЛ"),
        "avito_url": get_col("avito_url"),
        "availability": get("В СБОРЕ") or "в наличии",
    }


def parse_avito_xml_ad(ad) -> dict:
    def get(tag):
        el = ad.find(tag)
        return el.text.strip() if el is not None and el.text else None

    photos = []
    for img in ad.iter("Image"):
        url = img.get("url") or img.text
        if url:
            photos.append(url.strip())

    chars = {}
    for param in ad.iter("Param"):
        name = param.get("name") or param.findtext("Name")
        value = param.get("value") or param.text
        if name and value:
            chars[name.strip()] = value.strip()

    return {
        "external_id": get("Id"),
        "title": get("Title"),
        "description": get("Description"),
        "price": _parse_price(get("Price")),
        "photos": json.dumps(photos),
        "characteristics": json.dumps(chars),
        "category": get("Category"),
        "article": get("Article") or get("VendorCode"),
        "avito_url": get("Url"),
        "availability": get("Availability") or "в наличии",
    }


def parse_yml_offer(offer) -> dict:
    def get(tag):
        el = offer.find(tag)
        return el.text.strip() if el is not None and el.text else None

    photos = [pic.text.strip() for pic in offer.findall("picture") if pic.text]
    chars = {}
    for param in offer.findall("param"):
        name = param.get("name")
        if name and param.text:
            chars[name.strip()] = param.text.strip()

    return {
        "external_id": offer.get("id"),
        "title": get("name") or get("model"),
        "description": get("description"),
        "price": _parse_price(get("price")),
        "photos": json.dumps(photos),
        "characteristics": json.dumps(chars),
        "category": get("categoryId"),
        "article": get("vendorCode"),
        "avito_url": get("url"),
        "availability": "в наличии",
    }


def parse_csv_feed(content: bytes) -> list[dict]:
    import csv
    import io
    text = content.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    items = []
    for row in reader:
        items.append({
            "external_id": row.get("Id") or row.get("id"),
            "title": row.get("Title") or row.get("Название"),
            "description": row.get("Description") or row.get("Описание"),
            "price": _parse_price(row.get("Price") or row.get("Цена")),
            "photos": json.dumps([row.get("ImageUrls", "")]),
            "characteristics": json.dumps({}),
            "category": row.get("Category") or row.get("Категория"),
            "article": row.get("Article") or row.get("Артикул"),
            "avito_url": row.get("Url"),
            "availability": row.get("Availability", "в наличии"),
        })
    return items


def _parse_price(value) -> Optional[float]:
    if not value:
        return None
    try:
        return float(str(value).replace(" ", "").replace(",", ".").replace("₽", ""))
    except (ValueError, TypeError):
        return None


async def update_catalog(items) -> tuple[int, int, int]:
    """
    Memory-efficient catalog update.
    `items` can be a list or a generator yielding product dicts.
    Processes in small batches in its own DB session so we never hold
    the full feed (or all products) in memory at once.
    """
    now = datetime.utcnow()
    BATCH = 200

    async with AsyncSessionLocal() as db:
        # Snapshot counts before sync (for stats)
        total_before = (await db.execute(select(func.count()).select_from(Product))).scalar() or 0
        active_before = (await db.execute(
            select(func.count()).select_from(Product).where(Product.is_active == True)
        )).scalar() or 0
        inactive_before = total_before - active_before

        # Mark everything inactive first - sync will reactivate what's still present.
        await db.execute(update(Product).values(is_active=False))
        await db.commit()

        updated = 0
        batch: list[dict] = []

        async def flush_batch(batch_items: list[dict]):
            nonlocal updated
            if not batch_items:
                return
            ext_ids = [i["external_id"] for i in batch_items]
            result = await db.execute(
                select(Product).where(Product.external_id.in_(ext_ids))
            )
            existing = {p.external_id: p for p in result.scalars().all()}

            for item in batch_items:
                ext_id = item["external_id"]
                if ext_id in existing:
                    p = existing[ext_id]
                    p.title = item["title"]
                    p.description = item.get("description") or p.description
                    p.price = item.get("price") or p.price
                    p.photos = item.get("photos") or p.photos
                    p.characteristics = item.get("characteristics") or p.characteristics
                    p.category = item.get("category") or p.category
                    p.article = item.get("article") or p.article
                    p.avito_url = item.get("avito_url") or p.avito_url
                    p.availability = item.get("availability") or p.availability
                    p.is_active = True
                    p.updated_at = now
                    updated += 1
                else:
                    p = Product(
                        external_id=ext_id,
                        title=item["title"],
                        description=item.get("description"),
                        price=item.get("price"),
                        photos=item.get("photos", "[]"),
                        characteristics=item.get("characteristics", "{}"),
                        category=item.get("category"),
                        article=item.get("article"),
                        avito_url=item.get("avito_url"),
                        availability=item.get("availability", "в наличии"),
                        is_active=True,
                        updated_at=now,
                    )
                    db.add(p)

            await db.commit()
            # Release references so they can be garbage collected before next batch
            existing.clear()
            db.expunge_all()

        for item in items:
            if not item.get("external_id") or not item.get("title"):
                continue
            batch.append(item)
            if len(batch) >= BATCH:
                await flush_batch(batch)
                batch = []

        # Flush remaining
        await flush_batch(batch)

        total_after = (await db.execute(select(func.count()).select_from(Product))).scalar() or 0
        inactive_after = (await db.execute(
            select(func.count()).select_from(Product).where(Product.is_active == False)
        )).scalar() or 0

    added = total_after - total_before
    removed = max(inactive_after - inactive_before, 0)
    # `updated` may double-count items that appear more than once in the feed; clamp for sanity
    updated = max(updated - added, 0) if updated >= added else updated

    return added, updated, removed


async def notify_admin_sync_success(added: int, updated: int, removed: int):
    try:
        from bot.bot import send_admin_message
        await send_admin_message(
            f"✅ Каталог обновлён\n+{added} добавлено | ~{updated} обновлено | -{removed} скрыто"
        )
    except Exception:
        pass


async def notify_admin_sync_error(error: str):
    try:
        from bot.bot import send_admin_message
        await send_admin_message(f"❌ Ошибка обновления каталога:\n{error}")
    except Exception:
        pass