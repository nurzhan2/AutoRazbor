import json
import os
from datetime import datetime
from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.models.database import get_db
from app.models.models import User, Product, Video, SyncLog, Payment
from app.services.auth import hash_password, generate_password
from app.services.catalog import run_catalog_sync

router = APIRouter(prefix="/admin")
templates = Jinja2Templates(directory="app/templates")

ADMIN_LOGIN = os.getenv("ADMIN_LOGIN", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")


def check_admin(request: Request):
    return request.cookies.get("admin_auth") == "true"


@router.get("/login", response_class=HTMLResponse)
async def admin_login_page(request: Request):
    if check_admin(request):
        return RedirectResponse("/admin", status_code=302)
    return templates.TemplateResponse("admin/login.html", {"request": request, "error": None})


@router.post("/login")
async def admin_login(request: Request, login: str = Form(...), password: str = Form(...)):
    if login == ADMIN_LOGIN and password == ADMIN_PASSWORD:
        response = RedirectResponse("/admin", status_code=302)
        response.set_cookie("admin_auth", "true", httponly=True, max_age=60 * 60 * 8)
        return response
    return templates.TemplateResponse(
        "admin/login.html", {"request": request, "error": "Неверные данные"}
    )


@router.get("/logout")
async def admin_logout():
    response = RedirectResponse("/admin/login", status_code=302)
    response.delete_cookie("admin_auth")
    return response


@router.get("", response_class=HTMLResponse)
async def admin_index(request: Request, db: AsyncSession = Depends(get_db)):
    if not check_admin(request):
        return RedirectResponse("/admin/login", status_code=302)

    users_count = (await db.execute(select(func.count()).select_from(User))).scalar()
    products_count = (
        await db.execute(select(func.count()).select_from(Product).where(Product.is_active == True))
    ).scalar()
    last_sync = (
        await db.execute(
            select(SyncLog).where(SyncLog.status == "success").order_by(SyncLog.finished_at.desc()).limit(1)
        )
    ).scalar_one_or_none()

    return templates.TemplateResponse(
        "admin/index.html",
        {"request": request, "users_count": users_count, "products_count": products_count, "last_sync": last_sync},
    )


@router.get("/users", response_class=HTMLResponse)
async def admin_users(request: Request, db: AsyncSession = Depends(get_db)):
    if not check_admin(request):
        return RedirectResponse("/admin/login", status_code=302)
    result = await db.execute(select(User).order_by(User.registered_at.desc()))
    users = result.scalars().all()
    return templates.TemplateResponse("admin/users.html", {"request": request, "users": users})


@router.post("/users/{user_id}/extend")
async def admin_extend_user(user_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    if not check_admin(request):
        return RedirectResponse("/admin/login", status_code=302)
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user:
        from app.services.auth import extend_user_access
        await extend_user_access(db, user)
    return RedirectResponse("/admin/users", status_code=302)


@router.post("/users/{user_id}/disable")
async def admin_disable_user(user_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    if not check_admin(request):
        return RedirectResponse("/admin/login", status_code=302)
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user:
        user.is_active = False
        await db.commit()
    return RedirectResponse("/admin/users", status_code=302)


@router.post("/users/{user_id}/reset-password")
async def admin_reset_password(user_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    if not check_admin(request):
        return RedirectResponse("/admin/login", status_code=302)
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    new_pass = None
    if user:
        new_pass = generate_password()
        user.password_hash = hash_password(new_pass)
        await db.commit()
    return templates.TemplateResponse(
        "admin/users.html",
        {
            "request": request,
            "users": (await db.execute(select(User).order_by(User.registered_at.desc()))).scalars().all(),
            "new_pass_info": f"Новый пароль для {user.login}: {new_pass}" if new_pass else None,
        },
    )


@router.get("/videos", response_class=HTMLResponse)
async def admin_videos(request: Request, db: AsyncSession = Depends(get_db)):
    if not check_admin(request):
        return RedirectResponse("/admin/login", status_code=302)
    result = await db.execute(select(Video).order_by(Video.order))
    videos = result.scalars().all()
    return templates.TemplateResponse("admin/videos.html", {"request": request, "videos": videos})


@router.post("/videos/add")
async def admin_add_video(
    request: Request,
    db: AsyncSession = Depends(get_db),
    title: str = Form(...),
    description: str = Form(""),
    video_url: str = Form(...),
    order: int = Form(0),
):
    if not check_admin(request):
        return RedirectResponse("/admin/login", status_code=302)
    video = Video(title=title, description=description, video_url=video_url, order=order)
    db.add(video)
    await db.commit()
    return RedirectResponse("/admin/videos", status_code=302)


@router.post("/videos/{video_id}/toggle")
async def admin_toggle_video(video_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    if not check_admin(request):
        return RedirectResponse("/admin/login", status_code=302)
    result = await db.execute(select(Video).where(Video.id == video_id))
    video = result.scalar_one_or_none()
    if video:
        video.is_published = not video.is_published
        await db.commit()
    return RedirectResponse("/admin/videos", status_code=302)


@router.post("/videos/{video_id}/delete")
async def admin_delete_video(video_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    if not check_admin(request):
        return RedirectResponse("/admin/login", status_code=302)
    result = await db.execute(select(Video).where(Video.id == video_id))
    video = result.scalar_one_or_none()
    if video:
        await db.delete(video)
        await db.commit()
    return RedirectResponse("/admin/videos", status_code=302)


@router.get("/catalog", response_class=HTMLResponse)
async def admin_catalog(request: Request, db: AsyncSession = Depends(get_db)):
    if not check_admin(request):
        return RedirectResponse("/admin/login", status_code=302)

    products_result = await db.execute(
        select(Product).order_by(Product.updated_at.desc()).limit(50)
    )
    products = products_result.scalars().all()

    logs_result = await db.execute(
        select(SyncLog).order_by(SyncLog.started_at.desc()).limit(10)
    )
    logs = logs_result.scalars().all()

    return templates.TemplateResponse(
        "admin/catalog.html",
        {"request": request, "products": products, "logs": logs},
    )


@router.post("/catalog/sync")
async def admin_sync_now(request: Request):
    if not check_admin(request):
        return RedirectResponse("/admin/login", status_code=302)
    import asyncio
    asyncio.create_task(run_catalog_sync())
    return RedirectResponse("/admin/catalog?syncing=1", status_code=302)


@router.post("/catalog/{product_id}/hide")
async def admin_hide_product(product_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    if not check_admin(request):
        return RedirectResponse("/admin/login", status_code=302)
    result = await db.execute(select(Product).where(Product.id == product_id))
    product = result.scalar_one_or_none()
    if product:
        product.is_active = False
        await db.commit()
    return RedirectResponse("/admin/catalog", status_code=302)
