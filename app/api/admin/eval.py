"""评测看板：用 eval_case 真值样本对比 Mock / Jev 两个判定器的路由表现。

每次调用即时执行（不落库、不进统计）：对每条样本分别用 MockDecider 与 JevDecider
跑完整三层 pipeline（与线上同源），输出两侧的：
- 任务类型准确率（predicted task_type == expected_task_type）
- 模型选择准确率（final_model.id == expected_model_id，无真值模型的样本跳过）
- expected × predicted 混淆矩阵
- 逐条明细（层、判定器、confidence、选中模型、是否命中）

三条实现硬约束：
1. **绕过全局配置**：直接实例化 MockDecider / JevDecider，不受 settings.judge_provider
   影响——评测结果必须与「当前生效的判定器」解耦，才能横向对比两侧。
2. **两侧之间清路由缓存**：pipeline 按输入文本 hash 命中缓存（pipeline._cache_key），
   不清缓存则第二个判定器直接读到第一个的结果，两侧同分，对比失效。
3. **样本并发 + 数量上限**：Jev 侧是真实网络调用（实测约 1.5s/条）。原先串行跑全部样本，
   样本到 20 条就撞上前端 30s 超时 —— 页面直接报错，评测不可用。故改为有界并发
   （`_CONCURRENCY`）+ `limit` 上限，并把 `elapsed_ms` / `total_cases` / `used_cases`
   如实回传，让界面能说清「这次到底评了多少条、花了多久」。
"""
import asyncio
import json
import logging
import time

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user, load_routable_models
from app.db.session import get_db
from app.db.tables import EvalCase, RouteRule
from app.observability import trace
from app.router_engine.context import ModelRef, RouterContext
from app.router_engine.pipeline import route
from app.services.billing import estimate_tokens
from app.services.quota_cache import flush_route_cache

logger = logging.getLogger("api.admin.eval")
router = APIRouter(prefix="/admin/eval", tags=["admin-eval"])

# Jev 是外部 HTTP 服务：并发度取 5，再高容易触发上游限流，反而更慢。
_CONCURRENCY = 5
# 单次评测的样本上限：防止 eval_case 涨到几百条时把请求拖死（超出部分不评，如实上报）。
_MAX_CASES = 50


async def _run_side(cases, refs: dict[int, ModelRef], rules, decider) -> list[dict]:
    """对同一批样本用一个判定器跑 pipeline，返回逐条结果（有界并发）。

    route() 内部已兜底（任何异常都转为 L3 路径），此处 try 只是双保险。
    """
    model_of = refs.get
    cands = sorted(refs.values(), key=lambda r: r.priority)  # 候选池提出来排一次
    sem = asyncio.Semaphore(_CONCURRENCY)

    async def _one(case) -> dict:
        ctx = RouterContext(
            trace_id=trace.new_trace_id(prefix="eval-"),
            input_text=case.input_text,
            token_len=estimate_tokens(case.input_text),
            candidates=cands,
        )
        async with sem:
            try:
                ctx = await route(ctx, decider, rules, model_of)
            except Exception:
                logger.exception("eval route error for case %s", case.id)
        task_type = ctx.decision.task_type if ctx.decision else None
        model_id = ctx.final_model.id if ctx.final_model else None
        return {
            "case_id": case.id,
            "input_text": (case.input_text or "")[:120],
            "expected_task_type": case.expected_task_type,
            "expected_model_id": case.expected_model_id,
            "hit_layer": ctx.hit_layer,
            "predicted_task_type": task_type,
            "confidence": ctx.decision.confidence if ctx.decision else None,
            "selected_model_id": model_id,
            "selected_model_name": ctx.final_model.model_name if ctx.final_model else None,
            "task_ok": bool(task_type and task_type == case.expected_task_type),
            # 无模型真值（expected_model_id 为空）的样本：模型维度记 None，汇总时跳过
            "model_ok": (model_id == case.expected_model_id) if case.expected_model_id else None,
            "fallback_reason": ctx.fallback_reason,
        }

    # gather 保序：返回顺序与 cases 一致，明细表不会因并发而乱序
    return list(await asyncio.gather(*(_one(c) for c in cases)))


def _summarize(items: list[dict]) -> dict:
    """从逐条结果汇总准确率、混淆矩阵、层分布。"""
    task_total = len(items)
    task_ok = sum(1 for i in items if i["task_ok"])
    model_pairs = [i for i in items if i["model_ok"] is not None]
    model_ok = sum(1 for i in model_pairs if i["model_ok"])
    matrix: dict[str, dict[str, int]] = {}
    for i in items:
        exp = i["expected_task_type"] or "unknown"
        pred = i["predicted_task_type"] or "(未判定)"
        matrix.setdefault(exp, {})
        matrix[exp][pred] = matrix[exp].get(pred, 0) + 1
    layer_dist: dict[str, int] = {}
    for i in items:
        layer = i["hit_layer"] or "L3"
        layer_dist[layer] = layer_dist.get(layer, 0) + 1
    return {
        "task_total": task_total,
        "task_ok": task_ok,
        "task_accuracy": round(task_ok / task_total, 4) if task_total else None,
        "model_total": len(model_pairs),
        "model_ok": model_ok,
        "model_accuracy": round(model_ok / len(model_pairs), 4) if model_pairs else None,
        "confusion_matrix": matrix,
        "layer_distribution": layer_dist,
    }


@router.get("/report")
async def eval_report(
    limit: int = Query(_MAX_CASES, ge=1, le=200, description="最多评测的样本条数"),
    db: AsyncSession = Depends(get_db),
    _u: dict = Depends(current_user),
):
    started = time.perf_counter()
    all_cases = (await db.execute(select(EvalCase).order_by(EvalCase.id))).scalars().all()
    cases = list(all_cases[:limit])
    if not cases:
        return {"code": 0, "message": "ok", "data": {
            "empty": True,
            "message": "评测样本为空：请先向 eval_case 表添加带 expected_task_type 真值的样本",
            "total_cases": 0, "used_cases": 0, "truncated": False,
            "mock": _summarize([]), "jev": _summarize([]), "items": [],
        }}

    models = await load_routable_models(db)
    refs: dict[int, ModelRef] = {
        mid: ModelRef(
            id=m.id, provider_id=m.provider_id, model_name=m.model_name,
            display_name=m.display_name, capabilities=json.loads(m.capabilities or "[]"),
            input_price=m.input_price, output_price=m.output_price, priority=m.priority,
        ) for mid, m in models.items()
    }
    rules = list((await db.execute(
        select(RouteRule).where(RouteRule.enabled.is_(True)).order_by(RouteRule.priority)
    )).scalars().all())

    from app.deciders import MockDecider  # 延迟导入，与工厂同口径
    from app.deciders.jev_decider import JevDecider

    # 先跑 Mock，清缓存后跑 Jev：同一批样本、同一候选池、同一条 pipeline。
    # 两次跑完各清一次缓存，避免把评测流量留在路由缓存里影响线上判定。
    mock_items = await _run_side(cases, refs, rules, MockDecider())
    await flush_route_cache()
    jev_decider = JevDecider()
    jev_items = await _run_side(cases, refs, rules, jev_decider)
    await flush_route_cache()

    # 明细以 Mock 为主行，附上 Jev 侧的对应结果，前端一行看两侧对比
    jev_by_case = {i["case_id"]: i for i in jev_items}
    for mi in mock_items:
        ji = jev_by_case.get(mi["case_id"]) or {}
        mi["jev_task_ok"] = ji.get("task_ok")
        mi["jev_predicted_task_type"] = ji.get("predicted_task_type")
        mi["jev_selected_model_id"] = ji.get("selected_model_id")

    return {"code": 0, "message": "ok", "data": {
        "empty": False,
        "case_count": len(cases),
        # 样本总量与本次实际评测量分开报：样本被 limit 截断时必须让界面看得出来，
        # 否则「准确率」会被误读成「全量样本的准确率」。
        "total_cases": len(all_cases),
        "used_cases": len(cases),
        "truncated": len(all_cases) > len(cases),
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
        # 候选池规模：评测只在「可路由」模型里选，池子过小时准确率不具代表性，
        # 界面需要据此提示使用者（本库曾长期只有 3 个可路由模型）。
        "routable_models": len(refs),
        # 无模型真值的样本条数：模型维度准确率恒为 null 的根因，单独暴露
        "model_truth_cases": sum(1 for c in cases if c.expected_model_id),
        "jev_healthy": await jev_decider.health_check(),
        "jev_last_error": getattr(jev_decider, "last_error", None),
        "mock": _summarize(mock_items),
        "jev": _summarize(jev_items),
        "items": mock_items,
    }}
