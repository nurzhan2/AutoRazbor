import os
import random
import string
from datetime import datetime, timedelta
from typing import Optional

from jose import JWTError, jwt
import hashlib
import hmac
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.models import User

SECRET_KEY = os.getenv("SECRET_KEY", "changeme_secret_key_32chars_here")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 days


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return hmac.compare_digest(hash_password(plain_password), hashed_password)


def hash_password(password: str) -> str:
    return hashlib.sha256((SECRET_KEY + password).encode()).hexdigest()


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None


def generate_login() -> str:
    return "user" + "".join(random.choices(string.digits, k=6))


def generate_password() -> str:
    chars = string.ascii_letters + string.digits
    return "".join(random.choices(chars, k=10))


async def get_user_by_login(db: AsyncSession, login: str) -> Optional[User]:
    result = await db.execute(select(User).where(User.login == login))
    return result.scalar_one_or_none()


async def get_user_by_telegram_id(db: AsyncSession, telegram_id: str) -> Optional[User]:
    result = await db.execute(select(User).where(User.telegram_id == telegram_id))
    return result.scalar_one_or_none()


async def authenticate_user(db: AsyncSession, login: str, password: str) -> Optional[User]:
    user = await get_user_by_login(db, login)
    if not user:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


async def create_user_for_telegram(db: AsyncSession, telegram_id: str) -> tuple[User, str]:
    """Create new user after payment, return (user, plain_password)"""
    login = generate_login()
    # ensure unique login
    while await get_user_by_login(db, login):
        login = generate_login()

    password = generate_password()
    password_hash = hash_password(password)
    access_until = datetime.utcnow() + timedelta(days=30)

    user = User(
        telegram_id=str(telegram_id),
        login=login,
        password_hash=password_hash,
        access_until=access_until,
        last_paid_at=datetime.utcnow(),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user, password


async def extend_user_access(db: AsyncSession, user: User) -> User:
    """Extend access by 30 days from now or from current expiry"""
    now = datetime.utcnow()
    base = user.access_until if user.access_until and user.access_until > now else now
    user.access_until = base + timedelta(days=30)
    user.last_paid_at = now
    user.is_active = True
    await db.commit()
    await db.refresh(user)
    return user
