"""路由规则管理（L1）。含条件编辑器契约校验、优先级批量重排、冲突拦截。"""
import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user, require_admin
from app.db.session import get_db
from app.db.tables import RouteRule
from app.schemas import RuleCondition, RuleIn, RulePrioritiesIn, RuleUpdate
from app.services.quota_cache import cache as qcache

router = APIRouter(prefix="/admin/rules", tags=["admin-rules"])

_TEXT_OPS = {"contains", "not_contains", "regex"}
_LEN_OPS = {"gt", "gte", "lt", "lte"}
# type 只是 condition 的分类标签（匹配只读 condition，见 pipeline._match_condition）；
# 三者必须忠实描述条件，否则列表页「类型」列会与实际条件自相矛盾。
_TYPE_SPEC = {
    "keyword": ("text", {"contains", "not_contains"}),
    "regex": ("text", {"regex"}),
    "token_len": ("token_len", _LEN_OPS),
}


def _validate_condition(cond: RuleCondition) -> None:
    """接口说明书 §3.4：field/op 合法组合 + regex 可编译。"""
    import re as _re

    for c in cond.all:
        if c.field == "text" and c.op not in _TEXT_OPS:
            raise HTTPException(status_code=422, detail={"code": 1003, "message": f"text 不支持 op={c.op}"})
        if c.field == "token_len":
            if c.op not in _LEN_OPS:
                raise HTTPException(status_code=422, detail={"code": 1003, "message": f"token_len 不支持 op={c.op}"})
            if not isinstance(c.value, (int, float)):
                raise HTTPException(status_code=422, detail={"code": 1003, "message": "token_len 的 value 必须为数值"})
        if c.field not in ("text", "token_len"):
            raise HTTPException(status_code=422, detail={"code": 1003, "message": f"未知 field={c.field}"})
        if c.field == "text" and c.op == "regex":
            try:
                _re.compile(str(c.value))
            except _re.error:
                raise HTTPException(status_code=422, detail={"code": 1003, "message": f"非法正则: {c.value}"})


def _validate_type_condition(rule_type: str, cond: RuleCondition) -> None:
    """type ↔ condition 一致性（接口说明书 §3.4 延伸）。

    仅约束控制台开放的三种类型；tenant_whitelist / session_pin 等未开放类型跳过，
    由 DB CHECK 管取值合法性。不一致返回 422，防止「类型列说 A、条件实际是 B」的数据入库。
    """
    spec = _TYPE_SPEC.get(rule_type)
    if spec is None:
        return
    field, ops = spec
    for c in cond.all:
        if c.field != field or c.op not in ops:
            raise HTTPException(status_code=422, detail={
                "code": 1003,
                "message": f"type={rule_type} 要求 field={field} 且 op∈{sorted(ops)}，"
                           f"实际 field={c.field}, op={c.op}（规则类型与条件不一致）",
            })


def _dump(r: RouteRule) -> dict:
    return {"id": r.id, "name": r.name, "priority": r.priority, "type": r.type,
            "condition_json": json.loads(r.condition_json), "target_model_id": r.target_model_id,
            "enabled": r.enabled, "remark": r.remark, "updated_at": str(r.updated_at)}


@router.get("")
async def list_rules(db: AsyncSession = Depends(get_db), _u: dict = Depends(current_user)):
    rows = (await db.execute(select(RouteRule).order_by(RouteRule.priority, RouteRule.id))).scalars().all()
    return {"code": 0, "message": "ok", "data": {"total": len(rows), "items": [_dump(r) for r in rows]}}


@router.post("")
async def create_rule(body: RuleIn, db: AsyncSession = Depends(get_db), _u: dict = Depends(require_admin)):
    _validate_condition(body.condition)
    _validate_type_condition(body.type, body.condition)
    # 冲突拦截：同 priority + 完全相同条件（设计审核 R-02）
    existing = (await db.execute(select(RouteRule).where(RouteRule.priority == body.priority,
                                                         RouteRule.enabled.is_(True)))).scalars().all()
    serialized = json.dumps(body.condition.model_dump(), sort_keys=True)
    for r in existing:
        try:
            if json.dumps(json.loads(r.condition_json), sort_keys=True) == serialized:
                raise HTTPException(status_code=409, detail={"code": 1005,
                                       "message": f"与规则「{r.name}」条件相同且优先级冲突"})
        except (json.JSONDecodeError, TypeError):
            continue
    rule = RouteRule(name=body.name, priority=body.priority, type=body.type,
                     condition_json=serialized, target_model_id=body.target_model_id,
                     enabled=body.enabled, remark=body.remark)
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    await qcache.flush_route_cache()
    return {"code": 0, "message": "ok", "data": _dump(rule)}


@router.put("/{rule_id}")
async def update_rule(rule_id: int, body: RuleUpdate,
                      db: AsyncSession = Depends(get_db), _u: dict = Depends(require_admin)):
    rule = await db.get(RouteRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail={"code": 1004, "message": "rule 不存在"})
    if body.condition is not None:
        _validate_condition(body.condition)
    if body.condition is not None or body.type is not None:
        # 动了「类型」或「条件」任一方 → 按合并后的最终态校验一致性
        final_type = body.type if body.type is not None else rule.type
        if body.condition is not None:
            final_cond = body.condition
        else:  # 只改类型没带条件 → 用库内现有条件比对
            try:
                final_cond = RuleCondition(**json.loads(rule.condition_json))
            except Exception:
                final_cond = None  # 库内条件本身已损坏 → 交给 L1 不命中的既有行为，不拦本次请求
        if final_cond is not None:
            _validate_type_condition(final_type, final_cond)
    if body.condition is not None:
        rule.condition_json = json.dumps(body.condition.model_dump(), sort_keys=True)
    for field in ("name", "priority", "type", "target_model_id", "enabled", "remark"):
        v = getattr(body, field)
        if v is not None:
            setattr(rule, field, v)
    await db.commit()
    # updated_at 是 server onupdate 列，flush 后被标记过期；
    # 不 refresh 就 _dump 会触发同步懒加载 → MissingGreenlet（与 create 同理）。
    await db.refresh(rule)
    await qcache.flush_route_cache()
    return {"code": 0, "message": "ok", "data": _dump(rule)}


@router.put("/priorities")
async def reorder(body: RulePrioritiesIn, db: AsyncSession = Depends(get_db), _u: dict = Depends(require_admin)):
    """按数组顺序重排 priority=10,20,30...（拖拽排序持久化）。"""
    for idx, rid in enumerate(body.ordered_ids, start=1):
        rule = await db.get(RouteRule, rid)
        if rule is None:
            raise HTTPException(status_code=404, detail={"code": 1004, "message": f"rule {rid} 不存在"})
        rule.priority = idx * 10
    await db.commit()
    await qcache.flush_route_cache()
    return {"code": 0, "message": "ok", "data": None}


@router.delete("/{rule_id}")
async def delete_rule(rule_id: int, db: AsyncSession = Depends(get_db), _u: dict = Depends(require_admin)):
    rule = await db.get(RouteRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail={"code": 1004, "message": "rule 不存在"})
    await db.delete(rule)
    await db.commit()
    await qcache.flush_route_cache()
    return {"code": 0, "message": "ok", "data": None}
