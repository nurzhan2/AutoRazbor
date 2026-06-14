from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import event
from app.models.models import Base
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./autoparts.db")

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


# SQLite's built-in lower()/upper() and LIKE/ILIKE only handle ASCII case-folding,
# so Cyrillic text like "Крышка" vs "крышка" is treated as different -> search fails.
# Override lower()/upper() with Python's Unicode-aware versions on every new
# SQLite DBAPI connection so SQLAlchemy's .ilike() (which compiles to
# lower(col) LIKE lower(:val) on SQLite) works correctly for Cyrillic too.
if DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine.sync_engine, "connect")
    def _register_unicode_functions(dbapi_connection, connection_record):
        dbapi_connection.create_function("lower", 1, lambda s: s.lower() if s is not None else None)
        dbapi_connection.create_function("upper", 1, lambda s: s.upper() if s is not None else None)


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)