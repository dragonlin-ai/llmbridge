"""决策样本管理 + 调用日志 + 统计（合并为观测域接口）。"""
import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user, require_admin
from app.db.session import get_db
from app.db.tables import Model, RequestLog, RouteRule
from app.schemas import SampleIn

router = APIRouter(prefix="/admin", tags=["admin-observe"])


# ---------------- 决策样本 ----------------

@router.get("/samples")
async def list_samples(page: int = 1, page_size: int = 20, task_type: str | None = None,
                       db: AsyncSession = Depends(get_db), _u: dict = Depends(current_user)):
    from app.db.tables import DecisionSample

    q = select(DecisionSample)
    if task_type:
        q = q.where(DecisionSample.task_type == task_type)
    total = len((await db.execute(select(DecisionSample.id))).all())
    rows = (await db.execute(q.order_by(DecisionSample.id.desc())
                             .offset((page - 1) * page_size).limit(page_size))).scalars().all()
    items = [{"id": s.id, "input_text": s.input_text[:200], "task_type": s.task_type,
              "probabilities_json": json.loads(s.probabilities_json or "{}"),
              "chosen_model_id": s.chosen_model_id, "source": s.source,
              "created_at": str(s.created_at)} for s in rows]
    return {"code": 0, "message": "ok", "data": {"total": total, "page": page, "page_size": page_size, "items": items}}


@router.post("/samples")
async def create_sample(body: SampleIn, db: AsyncSession = Depends(get_db), _u: dict = Depends(require_admin)):
    from app.db.tables import DecisionSample

    s = DecisionSample(input_text=body.input_text[:2000], task_type=body.task_type,
                       probabilities_json=json.dumps(body.probabilities_json, ensure_ascii=False),
                       chosen_model_id=body.chosen_model_id, source="manual")
    db.add(s)
    await db.commit()
    return {"code": 0, "message": "ok", "data": {"id": s.id}}


# ---------------- 调用日志 ----------------

def _model_fields(model_id: int | None, snapshot: str | None, models_map: dict) -> dict:
    """日志里的模型字段：同时给显示名与真实标识。

    取值优先级：**落库快照 > 外键 join**。
    外键会被「删除模型时的解绑」清空，只靠它会丢失历史事实；快照是既成事实，优先级更高。
    只给 display_name 也不行——它是运营别名，可能与上游实际调用的 `model_name` 不同。
    """
    m = models_map.get(model_id) if model_id else None
    return {
        "final_model_id": model_id,
        "final_model_name": (m.display_name if m else None) or snapshot,
        "final_model_key": (m.model_name if m else None) or snapshot,
    }


@router.get("/logs")
async def list_logs(page: int = 1, page_size: int = 20,
                    trace_id: str | None = None, router_layer: str | None = None,
                    status: str | None = None, model_id: int | None = None,
                    has_fallback: bool | None = None, source: str | None = None,
                    db: AsyncSession = Depends(get_db), _u: dict = Depends(current_user)):
    # 筛选条件集中构造，列表查询与总数查询共用，避免「筛选后总数仍是全表数」的分页错乱。
    def _apply_filters(q):
        if trace_id:
            q = q.where(RequestLog.trace_id == trace_id)
        if router_layer:
            q = q.where(RequestLog.router_layer == router_layer)
        if status:
            q = q.where(RequestLog.status == status)
        if model_id:
            q = q.where(RequestLog.final_model_id == model_id)
        if has_fallback:
            q = q.where(RequestLog.fallback_reason.is_not(None))
        # 来源筛选：live = 线上 /v1；preview = 试跑台「执行」调用（trace_id 以 preview- 开头）
        if source == "preview":
            q = q.where(RequestLog.trace_id.like("preview-%"))
        elif source == "live":
            q = q.where(RequestLog.trace_id.not_like("preview-%"))
        return q

    total = (await db.execute(_apply_filters(select(func.count(RequestLog.id))))).scalar() or 0
    q = _apply_filters(select(RequestLog))
    rows = (await db.execute(q.order_by(RequestLog.id.desc())
                             .offset((page - 1) * page_size).limit(page_size))).scalars().all()
    models_map = {m.id: m for m in (await db.execute(select(Model))).scalars()}
    items = [{"id": r.id, "trace_id": r.trace_id, "router_layer": r.router_layer,
              **_model_fields(r.final_model_id, r.final_model_key, models_map),
              "route_latency_ms": r.route_latency_ms, "latency_ms": r.latency_ms,
              "prompt_tokens": r.prompt_tokens, "completion_tokens": r.completion_tokens,
              "cost": r.cost, "status": r.status, "fallback_reason": r.fallback_reason,
              "created_at": str(r.created_at)} for r in rows]
    return {"code": 0, "message": "ok", "data": {"total": total, "page": page, "page_size": page_size, "items": items}}


@router.get("/logs/{trace_id}")
async def get_trace(trace_id: str, db: AsyncSession = Depends(get_db), _u: dict = Depends(current_user)):
    r = (await db.execute(select(RequestLog).where(RequestLog.trace_id == trace_id))).scalar_one_or_none()
    if r is None:
        raise HTTPException(status_code=404, detail={"code": 1004, "message": "trace 不存在"})
    models_map = {m.id: m for m in (await db.execute(select(Model))).scalars()}
    return {"code": 0, "message": "ok", "data": {
        "trace_id": r.trace_id, "router_layer": r.router_layer,
        "router_output_json": json.loads(r.router_output_json or "{}"),
        **_model_fields(r.final_model_id, r.final_model_key, models_map),
        "route_latency_ms": r.route_latency_ms,
        "latency_ms": r.latency_ms, "cost": r.cost, "status": r.status,
        "fallback_reason": r.fallback_reason, "created_at": str(r.created_at)}}


# ---------------- 统计 ----------------

@router.get("/stats/overview")
async def stats_overview(db: AsyncSession = Depends(get_db), _u: dict = Depends(current_user)):
    # 排除试跑台「执行」模式产生的诊断流量（trace_id 以 `preview-` 开头），
    # 保持线上成功率 / 兜底率 / 成本口径纯净（R-01）。日志列表页仍展示全部。
    live = RequestLog.trace_id.not_like("preview-%")
    total = (await db.execute(
        select(func.count(RequestLog.id)).where(live))).scalar() or 0
    ok = (await db.execute(
        select(func.count(RequestLog.id)).where(live, RequestLog.status == "success"))).scalar() or 0
    fallback = (await db.execute(select(func.count(RequestLog.id)).where(
        live, RequestLog.fallback_reason.is_not(None)))).scalar() or 0
    layer_rows = (await db.execute(select(RequestLog.router_layer, func.count(RequestLog.id))
                                   .where(live).group_by(RequestLog.router_layer))).all()
    route_latencies = (await db.execute(select(RequestLog.route_latency_ms)
                                        .where(live).order_by(RequestLog.route_latency_ms))).scalars().all()
    p95 = route_latencies[int(len(route_latencies) * 0.95) - 1] if route_latencies else 0
    total_cost = (await db.execute(
        select(func.coalesce(func.sum(RequestLog.cost), 0)).where(live))).scalar() or 0
    return {"code": 0, "message": "ok", "data": {
        "total_requests": total,
        "success_rate": round(ok / total, 4) if total else 0,
        "p95_route_latency_ms": p95,
        "fallback_rate": round(fallback / total, 4) if total else 0,
        "total_cost": round(total_cost, 4),
        "layer_distribution": {layer or "L3": n for layer, n in layer_rows},
    }}


# ---------------- 引用辅助：模型/规则选项 ----------------

@router.get("/options")
async def options(db: AsyncSession = Depends(get_db), _u: dict = Depends(current_user)):
    models = (await db.execute(select(Model).where(Model.enabled.is_(True)).order_by(Model.priority))).scalars().all()
    rules_count = (await db.execute(select(func.count(RouteRule.id)))).scalar() or 0
    # 判定器现状：必须同时给出「配置值」与「实际生效值」。
    # judge_provider=jev 但 JEV_API_KEY 为空时 build_decider 会静默退回 mock，
    # 只报配置值会让看板显示 jev 而实际跑 mock —— 调试时最容易被误导的地方。
    from app.core.config import get_settings
    from app.deciders import build_decider

    settings = get_settings()
    return {"code": 0, "message": "ok", "data": {
        "models": [{"id": m.id, "display_name": m.display_name, "model_name": m.model_name,
                    "capabilities": json.loads(m.capabilities or "[]"), "priority": m.priority} for m in models],
        "rules_total": rules_count,
        "judge_provider": settings.judge_provider,
        "active_decider": build_decider().name}}
