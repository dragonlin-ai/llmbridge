"""用量与成本聚合接口（/admin/usage/*）。

RequestLog 无 tenant 字段，故按「模型（final_model_key）+ 时段（按日）+ 路由层」三维聚合，
不做租户维度（避免编造不存在的口径）。

两个**必须与概览页同源**的口径约束（原先本文件两处都缺，属真实缺陷）：
1. 排除试跑台诊断流量（`trace_id LIKE 'preview-%'`）。概览页 R-01 已排除，用量页若不排除
   就会把「试跑台 execute 模式」产生的成本算进生产用量 —— 实测本库 all_cost=0.000394
   而 live_cost=0.000124，**相差 3.2 倍**，两页数字对不上，使用者无法判断哪个是真的。
2. `created_at` 是 **DB 侧 UTC**（库时区 Etc/UTC），故窗口起点用 `datetime.utcnow()`；
   按日分桶由 SQL 的 `date()` 在 UTC 下完成，前端只做字符串展示，不再做时区二次换算。
   （若前端把 naive 时间串交给 `new Date()` 会按本地时区解释，趋势图整体偏移 8 小时。）

另：RequestLog 是按「每次请求一行」落库的，**并非每条都有用量数据**（L1/L3 与失败请求
往往没有 token/成本）。因此响应里额外给出 `data_quality`，让界面如实说明「多少条真有
用量数据」，而不是把 0 当成真实成本展示出去。
"""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.db.session import get_db
from app.db.tables import RequestLog

router = APIRouter(prefix="/admin/usage", tags=["usage"])

# status 落库取值仅 success / error（见 app/api/v1/chat.py）
_OK = RequestLog.status == "success"
# 与 /admin/stats/overview 同源的「线上流量」口径（R-01）
_LIVE = RequestLog.trace_id.not_like("preview-%")


def _window_start(days: int) -> datetime:
    return datetime.utcnow() - timedelta(days=max(1, days))


def _rate(part: int, whole: int) -> float:
    return round(part / whole, 4) if whole else 0.0


@router.get("/report")
async def usage_report(
    days: int = Query(30, ge=1, le=365, description="统计窗口（天）"),
    db: AsyncSession = Depends(get_db),
    _user=Depends(current_user),
):
    """按模型 / 路由层聚合 token 与成本，另附按日趋势（近 N 天，UTC 日切）。"""
    start = _window_start(days)
    scope = (_LIVE, RequestLog.created_at >= start)

    # ---------- 汇总 ----------
    total_row = (await db.execute(
        select(
            func.count(RequestLog.id).label("calls"),
            func.coalesce(func.sum(case((_OK, 1), else_=0)), 0).label("success_count"),
            func.coalesce(func.sum(case((RequestLog.fallback_reason.is_not(None), 1), else_=0)), 0)
            .label("fallback_count"),
            func.coalesce(func.sum(RequestLog.cost), 0.0).label("cost"),
            func.coalesce(func.sum(RequestLog.prompt_tokens), 0).label("prompt_tokens"),
            func.coalesce(func.sum(RequestLog.completion_tokens), 0).label("completion_tokens"),
            func.coalesce(func.avg(RequestLog.latency_ms), 0.0).label("avg_latency_ms"),
            func.coalesce(func.sum(case((RequestLog.prompt_tokens > 0, 1), else_=0)), 0)
            .label("with_tokens"),
            func.coalesce(func.sum(case((RequestLog.cost > 0, 1), else_=0)), 0).label("with_cost"),
        ).where(*scope)
    )).mappings().one()

    calls = int(total_row["calls"] or 0)
    prompt_tokens = int(total_row["prompt_tokens"] or 0)
    completion_tokens = int(total_row["completion_tokens"] or 0)

    # ---------- 按模型 ----------
    # final_model_key 为空 = 该请求未落模型快照（多见于 L1 规则命中 / L3 兜底失败路径），
    # 单列一组而不是丢掉，否则「总调用数」与明细对不上。
    model_rows = (await db.execute(
        select(
            RequestLog.final_model_key.label("model_key"),
            func.count(RequestLog.id).label("calls"),
            func.coalesce(func.sum(case((_OK, 1), else_=0)), 0).label("success_count"),
            func.coalesce(func.sum(RequestLog.prompt_tokens), 0).label("prompt_tokens"),
            func.coalesce(func.sum(RequestLog.completion_tokens), 0).label("completion_tokens"),
            func.coalesce(func.sum(RequestLog.cost), 0.0).label("cost"),
            func.coalesce(func.avg(RequestLog.latency_ms), 0.0).label("avg_latency_ms"),
        ).where(*scope).group_by(RequestLog.final_model_key)
    )).all()

    by_model = []
    for r in model_rows:
        n = int(r.calls or 0)
        p_tok = int(r.prompt_tokens or 0)
        c_tok = int(r.completion_tokens or 0)
        cost = float(r.cost or 0.0)
        by_model.append({
            "model_key": r.model_key,
            "calls": n,
            "success_count": int(r.success_count or 0),
            "success_rate": _rate(int(r.success_count or 0), n),
            "prompt_tokens": p_tok,
            "completion_tokens": c_tok,
            "total_tokens": p_tok + c_tok,
            "cost": round(cost, 6),
            "avg_cost": round(cost / n, 6) if n else 0.0,
            "avg_latency_ms": round(float(r.avg_latency_ms or 0.0), 1),
        })
    by_model.sort(key=lambda m: (-m["cost"], -m["calls"]))

    # ---------- 按路由层（兜底成本是降级链的真实代价，单列一维） ----------
    layer_rows = (await db.execute(
        select(
            RequestLog.router_layer.label("layer"),
            func.count(RequestLog.id).label("calls"),
            func.coalesce(func.sum(case((_OK, 1), else_=0)), 0).label("success_count"),
            func.coalesce(func.sum(case((RequestLog.fallback_reason.is_not(None), 1), else_=0)), 0)
            .label("fallback_count"),
            func.coalesce(func.sum(RequestLog.cost), 0.0).label("cost"),
            func.coalesce(func.avg(RequestLog.latency_ms), 0.0).label("avg_latency_ms"),
        ).where(*scope).group_by(RequestLog.router_layer)
    )).all()

    layer_map = {r.layer or "L3": r for r in layer_rows}
    by_layer = []
    for key in ("L1", "L2", "L3"):  # 固定顺序，缺项补 0，避免图表跳动
        r = layer_map.get(key)
        n = int(r.calls or 0) if r is not None else 0
        ok = int(r.success_count or 0) if r is not None else 0
        fc = int(r.fallback_count or 0) if r is not None else 0
        by_layer.append({
            "layer": key,
            "calls": n,
            "success_count": ok,
            "success_rate": _rate(ok, n),
            "fallback_count": fc,
            "cost": round(float(r.cost or 0.0), 6) if r is not None else 0.0,
            "avg_latency_ms": round(float(r.avg_latency_ms or 0.0), 1) if r is not None else 0.0,
        })

    # ---------- 按日趋势（UTC 日切，与 DB 一致） ----------
    day = func.date(RequestLog.created_at)
    day_rows = (await db.execute(
        select(
            day.label("day"),
            func.count(RequestLog.id).label("calls"),
            func.coalesce(func.sum(case((_OK, 1), else_=0)), 0).label("success_count"),
            func.coalesce(func.sum(RequestLog.cost), 0.0).label("cost"),
            func.coalesce(func.sum(RequestLog.prompt_tokens), 0).label("prompt_tokens"),
            func.coalesce(func.sum(RequestLog.completion_tokens), 0).label("completion_tokens"),
        ).where(*scope).group_by(day).order_by(day)
    )).all()

    trend = [{
        # 直接给 ISO 日期串：不再让前端做时区换算（否则偏移 8 小时）
        "day": r.day.isoformat() if hasattr(r.day, "isoformat") else str(r.day),
        "calls": int(r.calls or 0),
        "success_count": int(r.success_count or 0),
        "cost": round(float(r.cost or 0.0), 6),
        "prompt_tokens": int(r.prompt_tokens or 0),
        "completion_tokens": int(r.completion_tokens or 0),
    } for r in day_rows]

    # ---------- 状态分布 ----------
    status_rows = (await db.execute(
        select(RequestLog.status.label("status"), func.count(RequestLog.id).label("calls"))
        .where(*scope).group_by(RequestLog.status)
    )).all()
    by_status = [{"status": r.status or "unknown", "calls": int(r.calls or 0)} for r in status_rows]

    return {
        "code": 0,
        "message": "ok",
        "data": {
            "window_days": days,
            # 窗口起点如实回传：DB 为 UTC，前端可按需展示（不做隐式换算）
            "window_start": start.isoformat(),
            "excludes_preview": True,
            "summary": {
                "calls": calls,
                "success_count": int(total_row["success_count"] or 0),
                "success_rate": _rate(int(total_row["success_count"] or 0), calls),
                "fallback_count": int(total_row["fallback_count"] or 0),
                "fallback_rate": _rate(int(total_row["fallback_count"] or 0), calls),
                "cost": round(float(total_row["cost"] or 0.0), 6),
                "avg_cost": round(float(total_row["cost"] or 0.0) / calls, 6) if calls else 0.0,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
                "avg_latency_ms": round(float(total_row["avg_latency_ms"] or 0.0), 1),
                "models": len([m for m in by_model if m["model_key"]]),
            },
            # 诚实标注数据覆盖度：不是每条请求都有用量，避免把「缺数据」读成「零成本」
            "data_quality": {
                "calls": calls,
                "with_token_data": int(total_row["with_tokens"] or 0),
                "with_cost_data": int(total_row["with_cost"] or 0),
            },
            "by_model": by_model,
            "by_layer": by_layer,
            "by_status": by_status,
            "trend": trend,
        },
    }
