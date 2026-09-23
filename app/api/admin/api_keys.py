"""控制台：第三方调用密钥管理（生成 / 列表 / 查看明文 / 启停 / 删除）。

设计取舍：
- **创建时返回明文**，之后随时可「查看」回显 —— 第三方接入是按调用方分发的，
  调用方随时可能换机器重配，只给一次会逼出「把 Key 存聊天记录里」这种更差的做法。
  安全性靠 AES 加密落库 + 控制台本身有登录态兜底（与厂商 Key 的掩码策略不同，
  因为这里明文对使用者有真实用途）。
- 删除前不做强引用预检：`request_log` 不存 api_key 外键（日志记录的是路由事实，
  不是调用方身份）。若未来要按调用方统计用量，再加引用列并复用 409 语义。
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user, require_admin
from app.core.crypto import decrypt_api_key, mask_api_key
from app.db.session import get_db
from app.db.tables import ApiKey
from app.services.apikeys import create_api_key

router = APIRouter(prefix="/admin/api-keys", tags=["api-keys"])


class CreateKeyRequest(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    expires_at: datetime | None = None


def _dump(row: ApiKey, reveal: bool = False) -> dict:
    out = {
        "id": row.id,
        "name": row.name,
        "key_prefix": row.key_prefix,
        "enabled": row.enabled,
        "last_used_at": row.last_used_at.isoformat() if row.last_used_at else None,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
    if reveal:
        # 解密失败不 500：回显是便利功能，失败时给掩码即可（主密钥轮换期会短暂发生）
        try:
            out["key"] = decrypt_api_key(row.key_encrypted)
        except ValueError:
            out["key"] = mask_api_key(row.key_prefix)
            out["key_recoverable"] = False
    return out


@router.get("")
async def list_keys(user: dict = Depends(current_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(ApiKey).order_by(ApiKey.id.desc()))).scalars().all()
    return {"total": len(rows), "items": [_dump(r) for r in rows]}


@router.post("", status_code=201)
async def create_key(body: CreateKeyRequest, user: dict = Depends(require_admin),
                     db: AsyncSession = Depends(get_db)):
    row, plaintext = await create_api_key(db, name=body.name.strip(), expires_at=body.expires_at)
    out = _dump(row)
    out["key"] = plaintext  # 明文仅此响应返回一次（列表接口不带）
    out["note"] = "请立即复制保存：该明文由加密副本支持随时在控制台再次查看。"
    return out


@router.get("/{key_id}")
async def reveal_key(key_id: int, user: dict = Depends(require_admin),
                     db: AsyncSession = Depends(get_db)):
    row = (await db.execute(select(ApiKey).where(ApiKey.id == key_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail={"code": 1004, "message": "密钥不存在"})
    return _dump(row, reveal=True)


class UpdateKeyRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    enabled: bool | None = None


@router.put("/{key_id}")
async def update_key(key_id: int, body: UpdateKeyRequest, user: dict = Depends(require_admin),
                     db: AsyncSession = Depends(get_db)):
    row = (await db.execute(select(ApiKey).where(ApiKey.id == key_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail={"code": 1004, "message": "密钥不存在"})
    if body.name is not None:
        row.name = body.name.strip()
    if body.enabled is not None:
        row.enabled = body.enabled
    await db.commit()
    return _dump(row)


@router.delete("/{key_id}")
async def delete_key(key_id: int, user: dict = Depends(require_admin),
                     db: AsyncSession = Depends(get_db)):
    row = (await db.execute(select(ApiKey).where(ApiKey.id == key_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail={"code": 1004, "message": "密钥不存在"})
    await db.delete(row)
    await db.commit()
    return {"deleted": True}
