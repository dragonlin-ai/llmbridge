"""三层路由编排：L1 规则短路 → L2 Jev 判定 → L3 组合兜底。

不变式（基线 3.11）：
- 本模块全项目唯一——试跑台与线上请求共用同一 pipeline；
- 任一层异常都不允许抛出：全部转为 L3 兜底路径（兜底率 100%）。
"""
import asyncio
import hashlib
import json
import logging

from app.core.config import get_settings
from app.deciders.base import BaseDecider
from app.router_engine.context import Decision, ModelRef, RouterContext

logger = logging.getLogger("router.pipeline")


# ---------------------------------------------------------------- L1 规则短路

def _match_condition(cond: dict, text: str, token_len: int) -> bool:
    """condition_json Schema 校验在保存入口（Pydantic）；此处尽力求值，异常=不命中。"""
    try:
        for clause in cond.get("all", []):
            field, op, value = clause.get("field"), clause.get("op"), clause.get("value")
            if field == "text":
                hit = {
                    "contains": lambda: str(value) in text,
                    "not_contains": lambda: str(value) not in text,
                    "regex": lambda: re_search(str(value), text),
                }.get(op, lambda: False)()
            elif field == "token_len":
                cmp = {"gt": token_len > value, "gte": token_len >= value,
                       "lt": token_len < value, "lte": token_len <= value}
                hit = cmp.get(op, False)
            else:
                hit = False
            if not hit:
                return False
        return bool(cond.get("all"))
    except Exception:
        return False


def _re_search(pattern: str, text: str) -> bool:
    import re

    try:
        return re.search(pattern, text) is not None
    except re.error:
        return False


def _rule_get(rule, key: str):
    """规则行兼容三种形态：dict 取键；RowMapping 取键（sq 索引安全）；ORM 对象取属性。"""
    if isinstance(rule, dict):
        return rule.get(key)
    try:  # RowMapping / Row：支持键访问
        return rule[key]
    except (KeyError, TypeError):
        pass
    return getattr(rule, key, None)


async def l1_match(rules: list[dict], ctx: RouterContext, model_of) -> ModelRef | None:
    """rules: 已按 priority 升序的 enabled 规则（dict/RowMapping/ORM 均可）；model_of: id→ModelRef。"""
    for rule in rules:
        try:
            raw = _rule_get(rule, "condition_json")
            cond = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            continue
        if _match_condition(cond, ctx.input_text, ctx.token_len):
            target = model_of(_rule_get(rule, "target_model_id"))
            if target is not None:
                try:  # 命中规则快照（试跑台可解释性）
                    ctx.hit_rule = {
                        "id": _rule_get(rule, "id"), "name": _rule_get(rule, "name"),
                        "priority": _rule_get(rule, "priority"),
                    }
                except Exception:
                    ctx.hit_rule = None
            return target
    return None


# ---------------------------------------------------------------- L3 组合兜底

_W_ACC, _W_COST, _W_LAT = 0.6, 0.25, 0.15  # 设计审核 R-07：初值，可配置后调


def score_candidates(task_type: str | None, candidates: list[ModelRef]) -> list[dict]:
    """候选模型的统一打分 —— **路由选择的唯一依据**。

    返回行按 `(-score, priority)` 排序，`l3_pick` 取首行即选中模型。
    试跑台的候选列表必须复用本函数：此前试跑台自带一套 `prob * 0.75` 的独立公式，
    与真实决策不同源，导致「打分表第一名的模型 ≠ 实际选中/调用的模型」——
    同一屏上显示两个互相打架的结论。打分逻辑只允许有一个来源。

    行的字段：
    - `model`：ModelRef
    - `score`：加权总分（能力 0.6 / 成本 0.25 / 延迟 0.15）
    - `acc` / `cost` / `lat`：三项因子原始得分，供界面解释分数构成
    - `eligible`：`task_type` 是否命中该模型的 capabilities
    - `in_pool`：是否进入实际挑选池（无人命中能力标签时，pool 回退为全量）
    """
    if not candidates:
        return []
    pool = [m for m in candidates if task_type and task_type in m.capabilities] or candidates
    max_price = max((m.input_price for m in pool), default=1) or 1
    rows: list[dict] = []
    for m in pool:
        hit_cap = bool(task_type and task_type in m.capabilities)
        acc = 1.0 if hit_cap else 0.5
        cost = 1.0 - (m.input_price / max_price)
        lat = 1.0  # MVP 无延迟画像，占位均匀
        rows.append({
            "model": m, "score": _W_ACC * acc + _W_COST * cost + _W_LAT * lat,
            "acc": acc, "cost": cost, "lat": lat,
            "eligible": hit_cap, "in_pool": True,
        })
    pool_ids = {m.id for m in pool}
    for m in candidates:  # 池外候选：存在能力命中者时，无能力标签的模型不参与挑选
        if m.id not in pool_ids:
            rows.append({"model": m, "score": 0.0, "acc": 0.0, "cost": 0.0, "lat": 0.0,
                         "eligible": False, "in_pool": False})
    rows.sort(key=lambda r: (-r["score"], r["model"].priority))
    return rows


def l3_pick(task_type: str | None, candidates: list[ModelRef]) -> ModelRef | None:
    """按 capabilities 匹配 + 成本/延迟权重选模型；空集返回 None 由上层走默认。"""
    rows = score_candidates(task_type, candidates)
    return rows[0]["model"] if rows else None


def selection_basis(task_type: str | None, rows: list[dict]) -> str:
    """用一句话说明「这次为什么是这个模型」——试跑台的可解释性文案。"""
    if not rows:
        return "模型池为空，无法选择"
    if task_type and any(r["eligible"] for r in rows):
        return f"有模型声明了「{task_type}」能力标签，按能力命中 + 成本加权选出"
    if task_type:
        return (f"模型池中没有任何模型声明「{task_type}」能力标签，"
                f"退化为按成本排序（单价越低得分越高，同价按 priority 取先）")
    return "无任务类型判定结果，按全部候选的成本加权兜底"


# ---------------------------------------------------------------- pipeline 主体

async def route(ctx: RouterContext, decider: BaseDecider, rules: list[dict], model_of) -> RouterContext:
    """执行三层路由。恒返回含 final_model 的 ctx（除非模型池为空）。"""
    settings = get_settings()
    try:
        # ---- 缓存（可降级） ----
        cached = await _cache_get(ctx)
        if cached is not None:
            return _apply_cached(ctx, cached, model_of)

        # ---- L1 ----
        hit = await l1_match(rules, ctx, model_of)
        if hit is not None:
            ctx.hit_layer = "L1"
            ctx.final_model = hit
            ctx.fallback_reason = None
            await _cache_put(ctx, settings.route_cache_ttl)
            return ctx

        # ---- L2（判定器独立超时，异常/超时=未命中） ----
        decision: Decision | None = None
        try:
            decision = await asyncio.wait_for(decider.decide(ctx), settings.decider_timeout_ms / 1000)
        except (TimeoutError, asyncio.TimeoutError):
            ctx.fallback_reason = "DECIDER_UNAVAILABLE"
        except Exception:
            logger.warning("decider error, fallback to L3", exc_info=True)
            ctx.fallback_reason = "DECIDER_UNAVAILABLE"

        if decision is not None and decision.confidence >= settings.route_confidence_threshold_t2:
            ctx.hit_layer = "L2"
            ctx.decision = decision
            ctx.final_model = l3_pick(decision.task_type, ctx.candidates)
        else:
            if decision is not None:
                ctx.decision = decision
                ctx.fallback_reason = ctx.fallback_reason or "LOW_CONFIDENCE"
            ctx.hit_layer = "L3"
            if ctx.final_model is None:
                ctx.final_model = l3_pick(decision.task_type if decision else None, ctx.candidates)
        await _cache_put(ctx, settings.route_cache_ttl)
        return ctx
    except Exception:  # 兜底的兜底：任何意外不冒泡
        logger.exception("pipeline unexpected error")
        ctx.hit_layer = "L3"
        ctx.fallback_reason = ctx.fallback_reason or "PIPELINE_ERROR"
        ctx.final_model = ctx.final_model or l3_pick(None, ctx.candidates)
        return ctx


def _norm_text(text: str) -> str:
    return " ".join(text.split()).strip().lower()


def _cache_key(ctx: RouterContext) -> str:
    return "route:cache:" + hashlib.sha256(_norm_text(ctx.input_text).encode()).hexdigest()


async def _cache_get(ctx: RouterContext) -> dict | None:
    from app.services.quota_cache import cache

    return await cache.get_json(_cache_key(ctx))


async def _cache_put(ctx: RouterContext, ttl: int) -> None:
    from app.services.quota_cache import cache

    payload = {
        "hit_layer": ctx.hit_layer,
        "model_id": ctx.final_model.id if ctx.final_model else None,
        "decision": ctx.decision.__dict__ if ctx.decision else None,
        "fallback_reason": ctx.fallback_reason,
    }
    await cache.set_json(_cache_key(ctx), payload, ttl)


def _apply_cached(ctx: RouterContext, payload: dict, model_of) -> RouterContext:
    ctx.hit_layer = payload.get("hit_layer") or "L3"
    if payload.get("decision"):
        ctx.decision = Decision(**payload["decision"])
    if payload.get("model_id"):
        ctx.final_model = model_of(payload["model_id"]) or ctx.final_model
    ctx.fallback_reason = payload.get("fallback_reason")
    return ctx
