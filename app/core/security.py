"""安全组件：JWT 签发校验 + bcrypt 口令哈希。

注：直接用 bcrypt 库而非 passlib——passlib 1.7 与 bcrypt>=4.1 不兼容
（__about__ 缺失导致后端探测崩溃）。bcrypt 本身限制 72 字节，这里显式截断。
"""
from datetime import datetime, timedelta, timezone

import bcrypt
from jose import JWTError, jwt

from app.core.config import get_settings

ALGORITHM = "HS256"


def hash_password(plain: str) -> str:
    # bcrypt 上限 72 字节，截断防 ValueError
    data = plain.encode("utf-8")[:72]
    return bcrypt.hashpw(data, bcrypt.gensalt(rounds=12)).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8")[:72], hashed.encode())
    except Exception:
        return False


def create_access_token(sub: str, role: str) -> str:
    settings = get_settings()
    expire = datetime.now(timezone.utc) + timedelta(seconds=settings.jwt_expire_seconds)
    payload = {"sub": sub, "role": role, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict | None:
    """返回 payload；无效/过期返回 None。"""
    try:
        return jwt.decode(token, get_settings().jwt_secret, algorithms=[ALGORITHM])
    except JWTError:
        return None
