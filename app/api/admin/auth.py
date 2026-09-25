"""控制台：登录 + JWT 签发。连续失败 5 次锁定 10 分钟（内存计数）。"""
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.core.security import create_access_token, verify_password, hash_password
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


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


@router.post("/change-password")
async def change_password(
    body: ChangePasswordRequest,
    user: dict = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    """登录后修改自己的密码：校验原密码 → 写新哈希。新密码至少 6 位。"""
    db_user = (
        await db.execute(select(AdminUser).where(AdminUser.username == user["sub"]))
    ).scalar_one_or_none()
    if db_user is None or not db_user.enabled:
        raise HTTPException(status_code=401, detail={"code": 1001, "message": "账号不存在或已禁用"})
    if not verify_password(body.old_password, db_user.password_hash):
        raise HTTPException(status_code=400, detail={"code": 1004, "message": "原密码错误"})
    if len(body.new_password) < 6:
        raise HTTPException(status_code=422, detail={"code": 1005, "message": "新密码至少 6 位"})
    db_user.password_hash = hash_password(body.new_password)
    await db.commit()
    return {"code": 0, "message": "ok", "data": None}

