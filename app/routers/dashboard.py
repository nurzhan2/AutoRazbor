import json
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

from app.models.database import get_db
from app.models.models import User, Video, Product, FavoriteProduct, FavoriteVideo, ViewHistory
from app.routers.auth import get_current_user_from_cookie

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


async def require_user(request: Request, db: AsyncSession):
    token_data = get_current_user_from_cookie(request)
    if not token_data:
        return None, RedirectResponse("/login", status_code=302)
    result = await db.execute(select(User).where(User.id == token_data["user_id"]))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        return None, RedirectResponse("/login", status_code=302)
    return user, None


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, db: AsyncSession = Depends(get_db)):
    user, redirect = await require_user(request, db)
    if redirect:
        return redirect

    # История просмотров (последние 10)
    history_result = await db.execute(
        select(Product, ViewHistory.viewed_at)
        .join(ViewHistory, ViewHistory.product_id == Product.id)
        .where(ViewHistory.user_id == user.id)
        .order_by(ViewHistory.viewed_at.desc())
        .limit(10)
    )
    history = []
    for product, viewed_at in history_result.fetchall():
        try:
            product._photos_list = json.loads(product.photos or "[]")[:1]
        except:
            product._photos_list = []
        history.append((product, viewed_at))

    # Избранные товары (последние 10)
    fav_products_result = await db.execute(
        select(Product, FavoriteProduct.created_at)
        .join(FavoriteProduct, FavoriteProduct.product_id == Product.id)
        .where(FavoriteProduct.user_id == user.id)
        .order_by(FavoriteProduct.created_at.desc())
        .limit(10)
    )
    fav_products = []
    for product, created_at in fav_products_result.fetchall():
        try:
            product._photos_list = json.loads(product.photos or "[]")[:1]
        except:
            product._photos_list = []
        fav_products.append(product)

    # Избранные видео
    fav_videos_result = await db.execute(
        select(Video)
        .join(FavoriteVideo, FavoriteVideo.video_id == Video.id)
        .where(FavoriteVideo.user_id == user.id)
        .order_by(FavoriteVideo.created_at.desc())
    )
    fav_videos = fav_videos_result.scalars().all()

    return templates.TemplateResponse("dashboard/index.html", {
        "request": request,
        "user": user,
        "history": history,
        "fav_products": fav_products,
        "fav_videos": fav_videos,
    })


@router.get("/videos", response_class=HTMLResponse)
async def videos(request: Request, db: AsyncSession = Depends(get_db)):
    user, redirect = await require_user(request, db)
    if redirect:
        return redirect
    if not user.has_active_subscription:
        return templates.TemplateResponse("videos/expired.html", {"request": request, "user": user})

    result = await db.execute(select(Video).where(Video.is_published == True).order_by(Video.order))
    videos_list = result.scalars().all()

    # Избранные видео ids
    fav_result = await db.execute(
        select(FavoriteVideo.video_id).where(FavoriteVideo.user_id == user.id)
    )
    fav_ids = {r[0] for r in fav_result.fetchall()}

    return templates.TemplateResponse("videos/list.html", {
        "request": request, "user": user, "videos": videos_list, "fav_ids": fav_ids
    })


@router.post("/favorites/product/{product_id}/toggle")
async def toggle_fav_product(product_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    user, redirect = await require_user(request, db)
    if redirect:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    result = await db.execute(
        select(FavoriteProduct).where(
            FavoriteProduct.user_id == user.id,
            FavoriteProduct.product_id == product_id
        )
    )
    fav = result.scalar_one_or_none()
    if fav:
        await db.delete(fav)
        await db.commit()
        return JSONResponse({"status": "removed"})
    else:
        db.add(FavoriteProduct(user_id=user.id, product_id=product_id))
        await db.commit()
        return JSONResponse({"status": "added"})


@router.post("/favorites/video/{video_id}/toggle")
async def toggle_fav_video(video_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    user, redirect = await require_user(request, db)
    if redirect:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    result = await db.execute(
        select(FavoriteVideo).where(
            FavoriteVideo.user_id == user.id,
            FavoriteVideo.video_id == video_id
        )
    )
    fav = result.scalar_one_or_none()
    if fav:
        await db.delete(fav)
        await db.commit()
        return JSONResponse({"status": "removed"})
    else:
        db.add(FavoriteVideo(user_id=user.id, video_id=video_id))
        await db.commit()
        return JSONResponse({"status": "added"})
