"""第三方调用密钥（`api_key` 表）的生成与鉴权。

与 `core/crypto.py`（上游厂商 Key）方向相反：
这里是**本网关发给外部调用方**的凭证，`/v1` 每次请求用它验明正身。

安全基线：
- 明文只在生成瞬间存在于内存与 API 响应，落库一律 sha256 摘要；
- 加密副本仅用于控制台回显（调用方需要完整 Key 配进自己的系统）；
- 鉴权用 `hmac.compare_digest` 比较摘要，避免逐字节短路带来的时序侧信道
  （虽然 sha256 等值查询本身已把比较收敛到索引命中后的一次摘要比对）。
"""
import hashlib
import hmac
import secrets
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import encrypt_api_key
from app.db.tables import ApiKey

KEY_PREFIX = "sk-lb-"  # llmbridge；与厂商的 sk- 前缀区分，便于在日志/配置里一眼认出来源


def generate_key() -> str:
    """生成 `sk-lb-` + 48 位十六进制（192 bit 熵）。

    足够抗暴力枚举；十六进制便于复制（无易混淆字符），前缀让泄露的 Key
    可被识别归属（secret scanning 可按前缀告警）。
    """
    return KEY_PREFIX + secrets.token_hex(24)


def hash_key(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def key_prefix_of(plaintext: str) -> str:
    """列表页掩码展示用前缀：取前 12 位（含 sk-lb- 即 6 位随机），不足以碰撞。"""
    return plaintext[:12]


async def create_api_key(db: AsyncSession, *, name: str, expires_at: datetime | None = None) -> tuple[ApiKey, str]:
    """新建密钥，返回 (记录, 明文)。**明文只在此刻可得**，之后只能走回显解密。"""
    plaintext = generate_key()
    row = ApiKey(
        name=name,
        key_hash=hash_key(plaintext),
        key_prefix=key_prefix_of(plaintext),
        key_encrypted=encrypt_api_key(plaintext),
        enabled=True,
        expires_at=expires_at,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row, plaintext


async def authenticate_key(db: AsyncSession, presented: str | None) -> ApiKey | None:
    """`/v1` 鉴权：明文 Key -> 命中的启用记录，无效/停用/过期一律 None。

    查找按 sha256 等值命中唯一索引（不遍历），命中后再做一次 compare_digest ——
    摘要本身即判据，第二次比较防的是「数据库驱动做了什么奇怪的类型归一化」这类
    意外放宽，属于纵深防御。
    """
    if not presented or not presented.startswith(KEY_PREFIX):
        return None
    digest = hash_key(presented)
    row = (await db.execute(
        select(ApiKey).where(ApiKey.key_hash == digest)
    )).scalar_one_or_none()
    if row is None or not row.enabled:
        return None
    if not hmac.compare_digest(row.key_hash, digest):
        return None
    if row.expires_at is not None:
        exp = row.expires_at
        if exp.tzinfo is None:  # DB 存的是 naive UTC
            exp = exp.replace(tzinfo=timezone.utc)
        if exp <= datetime.now(timezone.utc):
            return None
    return row


async def touch_last_used(db: AsyncSession, key_id: int) -> None:
    """记录最近使用时间。失败不影响请求（调用方不应为审计字段的写入买单）。"""
    try:
        await db.execute(
            update(ApiKey).where(ApiKey.id == key_id).values(last_used_at=func_now())
        )
        await db.commit()
    except Exception:
        pass


def func_now():
    from sqlalchemy import func
    return func.current_timestamp()
