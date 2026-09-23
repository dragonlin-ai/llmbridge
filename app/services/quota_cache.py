"""Redis 缓存/限流/配额：失败即降级，绝不阻断主链路（TR-012）。"""
import json
import logging

from app.core.config import get_settings

logger = logging.getLogger("services.cache")

_client = None
_ok = False
_warned = False


async def _get_client():
    global _client, _ok, _warned
    settings = get_settings()
    if not settings.redis_url:
        _ok = False
        return None
    if _client is None:
        try:
            import redis.asyncio as aioredis

            _client = aioredis.from_url(settings.redis_url, decode_responses=True)
            await _client.ping()
            _ok = True
            logger.info("redis connected")
        except Exception:
            _client = None
            _ok = False
    return _client if _ok else None


def _degrade_warn():
    global _warned
    if not _warned:
        logger.warning("redis unavailable - degrading to no-cache mode")
        _warned = True


async def get_json(key: str) -> dict | None:
    try:
        client = await _get_client()
        if client is None:
            _degrade_warn()
            return None
        raw = await client.get(key)
        return json.loads(raw) if raw else None
    except Exception:
        _ok = False
        _degrade_warn()
        return None


async def set_json(key: str, payload: dict, ttl: int) -> None:
    try:
        client = await _get_client()
        if client is None:
            return
        await client.set(key, json.dumps(payload, ensure_ascii=False), ex=ttl)
    except Exception:
        global _ok
        _ok = False
        _degrade_warn()


async def incr_window(key: str, window_seconds: int, limit: int) -> tuple[bool, int]:
    """滑动窗口计数。返回 (放行?, 当前计数)。降级=恒放行。"""
    try:
        client = await _get_client()
        if client is None:
            return True, 0
        count = await client.incr(key)
        if count == 1:
            await client.expire(key, window_seconds)
        return count <= limit, count
    except Exception:
        global _ok
        _ok = False
        _degrade_warn()
        return True, 0


async def flush_route_cache() -> int:
    """模型/规则变更时清空全部路由缓存（设计审核 R-05 整改项）。返回清除数量。"""
    try:
        client = await _get_client()
        if client is None:
            return 0
        keys = [k async for k in client.scan_iter(match="route:cache:*", count=500)]
        if keys:
            await client.delete(*keys)
        return len(keys)
    except Exception:
        return 0


class _CacheNamespace:
    get_json = staticmethod(get_json)
    set_json = staticmethod(set_json)
    incr_window = staticmethod(incr_window)
    flush_route_cache = staticmethod(flush_route_cache)


cache = _CacheNamespace()
