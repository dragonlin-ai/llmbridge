"""模型池管理（业务概念「下游大模型」）。写操作清路由缓存（R-05 整改）。"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user, require_admin
from app.db.session import get_db
from app.db.tables import DecisionSample, EvalCase, Model, RequestLog, RouteRule
from app.schemas import ModelIn, ModelUpdate
from app.services.quota_cache import cache as qcache

logger = logging.getLogger("api.admin.models")
router = APIRouter(prefix="/admin/models", tags=["admin-models"])


def _dump(m: Model) -> dict:
    import json

    return {"id": m.id, "provider_id": m.provider_id, "model_name": m.model_name,
            "display_name": m.display_name, "capabilities": json.loads(m.capabilities or "[]"),
            "input_price": m.input_price, "output_price": m.output_price,
            "context_window": m.context_window, "priority": m.priority,
            "enabled": m.enabled, "created_at": str(m.created_at)}


@router.get("")
async def list_models(page: int = 1, page_size: int = 20,
                      db: AsyncSession = Depends(get_db), _u: dict = Depends(current_user)):
    total = len((await db.execute(select(Model.id))).all())
    rows = (await db.execute(select(Model).order_by(Model.priority, Model.id)
                             .offset((page - 1) * page_size).limit(page_size))).scalars().all()
    return {"code": 0, "message": "ok", "data": {"total": total, "page": page,
            "page_size": page_size, "items": [_dump(r) for r in rows]}}


@router.post("")
async def create_model(body: ModelIn, db: AsyncSession = Depends(get_db), _u: dict = Depends(require_admin)):
    dup = (await db.execute(select(Model).where(
        Model.provider_id == body.provider_id, Model.model_name == body.model_name))).scalar_one_or_none()
    if dup:
        raise HTTPException(status_code=409, detail={"code": 1005, "message": "该厂商下模型名已存在"})
    import json

    m = Model(provider_id=body.provider_id, model_name=body.model_name,
              display_name=body.display_name, capabilities=json.dumps(body.capabilities),
              input_price=body.input_price, output_price=body.output_price,
              context_window=body.context_window, priority=body.priority, enabled=body.enabled)
    db.add(m)
    await db.commit()
    await db.refresh(m)
    await qcache.flush_route_cache()
    return {"code": 0, "message": "ok", "data": _dump(m)}


@router.put("/{model_id}")
async def update_model(model_id: int, body: ModelUpdate,
                       db: AsyncSession = Depends(get_db), _u: dict = Depends(require_admin)):
    m = await db.get(Model, model_id)
    if m is None:
        raise HTTPException(status_code=404, detail={"code": 1004, "message": "model 不存在"})
    import json

    for field in ("provider_id", "model_name", "display_name", "input_price",
                  "output_price", "context_window", "priority", "enabled"):
        v = getattr(body, field)
        if v is not None:
            setattr(m, field, v)
    if body.capabilities is not None:
        m.capabilities = json.dumps(body.capabilities)
    await db.commit()
    await qcache.flush_route_cache()
    return {"code": 0, "message": "ok", "data": _dump(m)}


@router.delete("/{model_id}")
async def delete_model(model_id: int, force: bool = False, db: AsyncSession = Depends(get_db),
                       _u: dict = Depends(require_admin)):
    """删除模型。外键引用分两类处理（缺陷 D-12，D-16 补充强制删除）：

    - **路由规则引用**（route_rule.target_model_id）：NOT NULL 强引用，解绑不了 → 始终 409，
      需到「路由规则配置」改绑或删除规则；
    - **评测用例引用**（eval_case.expected_model_id）：字段可为空 → 默认 409 给出警告，
      带 `force=true` 时把该字段清空（用例保留，退化为只校验任务类型）后继续删除；
    - **历史类引用**（request_log / decision_sample）：属既成事实，不应阻塞模型下线
      → 解绑为 NULL，历史记录保留。
    """
    m = await db.get(Model, model_id)
    if m is None:
        raise HTTPException(status_code=404, detail={"code": 1004, "message": "model 不存在"})

    # 一、配置类引用：路由规则（NOT NULL 强引用）始终阻止；评测用例（可空）未传 force 时阻止
    n_rules = (await db.execute(
        select(func.count(RouteRule.id)).where(RouteRule.target_model_id == model_id))).scalar_one()
    n_evals = (await db.execute(
        select(func.count(EvalCase.id)).where(EvalCase.expected_model_id == model_id))).scalar_one()
    if n_rules:
        # 路由规则的目标模型是 NOT NULL 强引用，无法解绑，只能阻止（规则页可改绑/删除）
        raise HTTPException(status_code=409, detail={
            "code": 1005,
            "message": f"存在 {n_rules} 条路由规则指定该模型为目标模型，而路由规则不能没有目标模型。"
                       f"请先到「路由规则配置」改绑或删除这些规则，或将该模型改为「禁用」"})
    if n_evals and not force:
        raise HTTPException(status_code=409, detail={
            "code": 1005,
            "message": f"存在 {n_evals} 条评测用例以该模型为「期望模型」，删除后这些用例的期望模型将被清空"
                       f"（用例本身保留）。如确认继续，请使用强制删除"})

    # 二、历史类引用：解绑为 NULL（保留记录），并统计解绑数量回给前端
    n_logs = (await db.execute(
        select(func.count(RequestLog.id)).where(RequestLog.final_model_id == model_id))).scalar_one()
    n_samples = (await db.execute(
        select(func.count(DecisionSample.id)).where(
            or_(DecisionSample.chosen_model_id == model_id,
                DecisionSample.actual_model_id == model_id)))).scalar_one()
    if n_logs:
        await db.execute(update(RequestLog).where(RequestLog.final_model_id == model_id)
                         .values(final_model_id=None))
    if n_samples:
        await db.execute(update(DecisionSample).where(DecisionSample.chosen_model_id == model_id)
                         .values(chosen_model_id=None))
        await db.execute(update(DecisionSample).where(DecisionSample.actual_model_id == model_id)
                         .values(actual_model_id=None))

    # 三、强制删除：解绑评测用例的期望模型（字段可空；用例保留，退化为只校验任务类型）
    n_evals_unbound = 0
    if force and n_evals:
        await db.execute(update(EvalCase).where(EvalCase.expected_model_id == model_id)
                         .values(expected_model_id=None))
        n_evals_unbound = n_evals
        logger.warning("force delete model %s: unbound %s eval_case(s)", model_id, n_evals_unbound)

    await db.delete(m)
    try:
        await db.commit()
    except IntegrityError:
        # 兜底：将来新增引用 model.id 的表时，仍返回可读 409 而非裸 500
        await db.rollback()
        logger.warning("delete model blocked by foreign key, model_id=%s", model_id)
        raise HTTPException(status_code=409, detail={
            "code": 1005, "message": "仍存在引用该模型的数据，请先解除引用或改为禁用"})
    await qcache.flush_route_cache()
    return {"code": 0, "message": "ok",
            "data": {"unbound_logs": n_logs, "unbound_samples": n_samples,
                     "unbound_evals": n_evals_unbound}}


@router.get("/{model_id}/references")
async def model_references(model_id: int, db: AsyncSession = Depends(get_db),
                           _u: dict = Depends(current_user)):
    """删除前引用预检（供前端生成准确的确认文案，避免「先失败再重试」）。

    - `forceable`：无路由规则引用即为 True。路由规则的目标模型是 NOT NULL 强引用，解绑不了；
      评测用例的期望模型可空，故允许强制删除时解绑。
    - 计数为 0 的项不代表无影响，前端应逐项展示非 0 项。
    """
    if await db.get(Model, model_id) is None:
        raise HTTPException(status_code=404, detail={"code": 1004, "message": "model 不存在"})

    n_rules = (await db.execute(
        select(func.count(RouteRule.id)).where(RouteRule.target_model_id == model_id))).scalar_one()
    n_evals = (await db.execute(
        select(func.count(EvalCase.id)).where(EvalCase.expected_model_id == model_id))).scalar_one()
    n_logs = (await db.execute(
        select(func.count(RequestLog.id)).where(RequestLog.final_model_id == model_id))).scalar_one()
    n_samples = (await db.execute(
        select(func.count(DecisionSample.id)).where(
            or_(DecisionSample.chosen_model_id == model_id,
                DecisionSample.actual_model_id == model_id)))).scalar_one()

    return {"code": 0, "message": "ok", "data": {
        "route_rules": n_rules,
        "eval_cases": n_evals,
        "request_logs": n_logs,
        "decision_samples": n_samples,
        "forceable": n_rules == 0,
    }}
