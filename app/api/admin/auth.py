"""控制台：登录 + JWT 签发。连续失败 5 次锁定 10 分钟（内存计数）。"""
import time

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, verify_password
from app.db.session import get_db
from app.db.tables import AdminUser
from app.schemas import LoginRequest

router = APIRouter(prefix="/admin/auth", tags=["admin-auth"])

_fail: dict[str, list[float]] = {}
_LOCK_WINDOW = 600
_MAX_FAILS = 5


@router.post("/login")
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    now = time.monotonic()
    history = [t for t in _fail.get(body.username, []) if now - t < _LOCK_WINDOW]
    if len(history) >= _MAX_FAILS:
        raise HTTPException(status_code=401, detail={"code": 1001, "message": "失败次数过多，账号已锁定 10 分钟"})

    user = (await db.execute(select(AdminUser).where(AdminUser.username == body.username))).scalar_one_or_none()
    if user is None or not user.enabled or not verify_password(body.password, user.password_hash):
        history.append(now)
        _fail[body.username] = history
        raise HTTPException(status_code=401, detail={"code": 1001, "message": "用户名或密码错误"})

    _fail.pop(body.username, None)
    from datetime import datetime, timezone

    user.last_login_at = datetime.now(timezone.utc)
    await db.commit()
    token = create_access_token(user.username, user.role)
    return {"code": 0, "message": "ok",
            "data": {"access_token": token, "token_type": "bearer",
                     "expires_in": 86400, "role": user.role}}
