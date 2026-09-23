"""判定器配置服务：sys_config 表读写 + 应用级覆盖（库 > .env > 代码默认）。

职责边界（Jev 5 项配置入界面）：
- refresh_decider_config：启动加载 / 保存后刷新 —— 从库读 5 项 → apply_db_overrides
  使 get_settings 的 lru_cache 失效，切换 mock/jev **免重启即时生效**；
- save_decider_values：已校验键值落库（密钥 AES-256-GCM 加密）后刷新；
- get_decider_display：给设置页回显（密钥只出掩码，绝不明文）。

校验（枚举 / SSRF / 数值范围）在路由层 admin/decider_settings.py 完成，
本模块只管存取 —— 与 providers 的「路由校验、服务存取」分层一致。
"""
import logging

from sqlalchemy import delete, select

from app.core.config import apply_db_overrides, get_settings
from app.core.crypto import decrypt_api_key, encrypt_api_key, mask_api_key
from app.db.session import SessionLocal
from app.db.tables import SysConfig

logger = logging.getLogger("sys_config")

# 迁移范围（用户确认）：只挪 Jev 这 5 项，DEFAULT_MODEL_ID / ROUTE_CACHE_TTL 不进界面。
DECIDER_KEYS = ("judge_provider", "jev_api_key", "jev_base_url",
                "decider_timeout_ms", "route_confidence_threshold_t2")
_SECRET_KEYS = {"jev_api_key"}
_COERCE = {"decider_timeout_ms": int, "route_confidence_threshold_t2": float}
"""数值型键的读取转型。库里一律存字符串，读出后按此还原类型。

不转型的后果：decider_timeout_ms 变成 "3000" 后 `timeout="3000"/1000` 抛 TypeError，
在 httpx 层表现为「判定器莫名不可用」——错误会离病因很远。
"""

_db_keys: set[str] = set()
"""最近一次成功加载时**实际存在于库里**的键。供设置页展示来源（db / env）。"""


def _coerce(key: str, raw: str) -> object:
    fn = _COERCE.get(key)
    if fn is None:
        return raw
    try:
        return fn(raw)
    except (TypeError, ValueError) as e:
        # 脏数值不拖垮整个加载：抛给调用方跳过该键 = 回落 .env（外层统一记日志）
        raise ValueError(f"{key}={raw!r} 非法数值") from e


async def refresh_decider_config() -> None:
    """从库加载判定器 5 项 → 覆盖 Settings 并清缓存。启动与保存后调用。

    表不存在/连接失败时**保持现状不覆盖**（不 apply 空集），回落 .env 行为，
    未跑迁移也能正常启动；单行解密失败（主密钥轮换）只跳过该行。
    """
    global _db_keys
    overrides: dict[str, object] = {}
    loaded: set[str] = set()
    # 用独立会话，避免与调用方会话交叉
    async with SessionLocal() as db:
        rows = (await db.execute(
            select(SysConfig).where(SysConfig.key.in_(DECIDER_KEYS))
        )).scalars().all()
    for r in rows:
        try:
            raw = decrypt_api_key(r.value) if r.encrypted else r.value
            overrides[r.key] = _coerce(r.key, raw)
            loaded.add(r.key)
        except Exception as e:  # 单行失败不拖垮其余键
            logger.warning("sys_config load skip %s: %s", r.key, str(e)[:200])
    _db_keys = loaded
    apply_db_overrides(overrides)


async def save_decider_values(clean: dict) -> None:
    """已校验键值写入 sys_config（密钥加密），随后刷新覆盖使其即时生效。

    `jev_api_key == ""` 语义为**清除**（删行 → 回落 .env），由路由层保证
    空串只可能是用户显式清空，不可能是掩码或漏传（None 在校验层已剔除）。
    """
    async with SessionLocal() as db:
        for k, v in clean.items():
            if k in _SECRET_KEYS and v == "":
                await db.execute(delete(SysConfig).where(SysConfig.key == k))
                continue
            stored = encrypt_api_key(str(v)) if k in _SECRET_KEYS else str(v)
            row = (await db.execute(
                select(SysConfig).where(SysConfig.key == k)
            )).scalar_one_or_none()
            if row is not None:
                row.value, row.encrypted = stored, k in _SECRET_KEYS
            else:
                db.add(SysConfig(key=k, value=stored, encrypted=k in _SECRET_KEYS))
        await db.commit()
    await refresh_decider_config()


def get_decider_display() -> dict:
    """设置页回显：生效值（密钥掩码）+ 每项来源 + 实际生效的判定器。

    来源口径：`db` = 库里有覆盖行；`env` = 库中无此键（.env 或代码默认）。
    active_decider 取 build_decider() 运行时事实 —— judge_provider=jev 但
    密钥缺失时会如实显示 mock，不粉饰配置值（与 /admin/options 同源）。
    """
    from app.deciders import build_decider

    s = get_settings()
    key = s.jev_api_key
    return {
        "judge_provider": s.judge_provider,
        "jev_api_key_masked": mask_api_key(key) if key else None,
        "jev_api_key_set": bool(key),
        "jev_base_url": s.jev_base_url,
        "decider_timeout_ms": s.decider_timeout_ms,
        "route_confidence_threshold_t2": s.route_confidence_threshold_t2,
        "sources": {k: ("db" if k in _db_keys else "env") for k in DECIDER_KEYS},
        "active_decider": build_decider().name,
    }
