import os
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

AVITO_UPDATE_HOUR = int(os.getenv("AVITO_UPDATE_HOUR", "3"))
AVITO_UPDATE_MINUTE = int(os.getenv("AVITO_UPDATE_MINUTE", "0"))

scheduler = AsyncIOScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Init DB
    from app.models.database import init_db
    await init_db()
    logger.info("Database initialized")

    # Schedule daily catalog sync
    from app.services.catalog import run_catalog_sync
    scheduler.add_job(
        run_catalog_sync,
        "cron",
        hour=AVITO_UPDATE_HOUR,
        minute=AVITO_UPDATE_MINUTE,
        id="catalog_sync",
    )

    # Schedule daily subscription checks
    from app.services.notifications import check_expiring_subscriptions
    scheduler.add_job(
        check_expiring_subscriptions,
        "cron",
        hour=10,
        minute=0,
        id="sub_check",
    )

    scheduler.start()
    logger.info(f"Scheduler started — catalog sync at {AVITO_UPDATE_HOUR:02d}:{AVITO_UPDATE_MINUTE:02d}")

    # Start bot in background
    bot_task = None
    if os.getenv("BOT_TOKEN"):
        from bot.bot import start_bot
        bot_task = asyncio.create_task(start_bot())
        logger.info("Telegram bot started")

    yield

    scheduler.shutdown()
    if bot_task:
        bot_task.cancel()


app = FastAPI(lifespan=lifespan, title="АвтоЗапчасти")

# Static files
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Routers
from app.routers import auth, dashboard, catalog, admin

app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(catalog.router)
app.include_router(admin.router)


@app.get("/")
async def root():
    return RedirectResponse("/login")
