"""路由试跑接口：与线上同一 pipeline（基线 3.11 内核唯一）。

两种模式：
- **仅决策（默认）**：`execute=false`。不调上游、不落主表、零成本。
- **决策 + 调用**：`execute=true`。在决策基础上**真实调用**选中模型并把输出原样带回。

两条硬约束：
1. trace_id 前缀 `preview-`（设计审核 R-01：与线上 trace 语义隔离）；**两种模式都不落 `request_log`**，
   故试跑产生的调用不计入线上统计——这是刻意的，避免诊断流量污染成功率口径。
2. 执行模式**不做降级**：降级是线上保护，试跑台的职责是如实暴露「这个模型到底通不通」。
   自动降级会让「选中的模型不可用」被另一个模型的成功掩盖，诊断价值归零。
"""
import json
import logging
import time

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user, load_routable_models
from app.core.config import get_settings
from app.db.session import get_db
from app.db.tables import Provider, RouteRule
from app.observability import trace
from app.router_engine.context import ModelRef, RouterContext
from app.router_engine.pipeline import route, score_candidates, selection_basis
from app.schemas import PreviewRequest
from app.services import logbuffer
from app.services.billing import calc_cost, estimate_tokens

logger = logging.getLogger("api.admin.preview")
router = APIRouter(prefix="/admin/route", tags=["admin-route"])


@router.post("/preview")
async def route_preview(body: PreviewRequest, request: Request,
                        db: AsyncSession = Depends(get_db), _u: dict = Depends(current_user)):
    settings = get_settings()
    models = await load_routable_models(db)
    refs: dict[int, ModelRef] = {
        mid: ModelRef(
            id=m.id, provider_id=m.provider_id, model_name=m.model_name,
            display_name=m.display_name, capabilities=json.loads(m.capabilities or "[]"),
            input_price=m.input_price, output_price=m.output_price, priority=m.priority,
        ) for mid, m in models.items()
    }
    rules = (await db.execute(
        select(RouteRule).where(RouteRule.enabled.is_(True)).order_by(RouteRule.priority)
    )).scalars().all()
    # 仅在执行模式下需要（取 base_url 与密钥）；决策阶段不查厂商，零成本路径不引入多余 IO
    providers = {
        p.id: p for p in (
            await db.execute(select(Provider).where(Provider.enabled.is_(True)))
        ).scalars().all()
    } if body.execute else {}

    # 候选池可见性：库里的模型数往往远大于实际可路由数（目录预置的模型随厂商一起待接入）。
    # 不把这个差额说清楚，使用者会以为「预置的厂商没生效」，然后去反复检查目录，
    # 而不是去补 Key。三项互斥且覆盖全部：routable + disabled + blocked = total。
    from app.db.tables import Model as ModelTable
    from app.db.tables import Provider as ProviderTable
    from app.services.provider_access import is_channel_supported, is_provider_routable

    all_rows = (await db.execute(
        select(ModelTable, ProviderTable)
        .join(ProviderTable, ModelTable.provider_id == ProviderTable.id)
    )).all()
    total_models = len(all_rows)
    # 归因顺序刻意如此：**先看厂商，再看模型自身开关**。
    # 目录预置的模型同时满足「模型停用」与「厂商未接入」，若按后者归因，
    # 这 25 个模型会被报成「模型已停用」，使用者于是去模型页逐个点启用，
    # 却发现启用了照样调不通（厂商还没填 Key）——归因必须指向那个唯一有效的动作。
    # 归因拆成四条，因为「下一步该做什么」完全不同：
    #   blocked_by_provider —— 通道本身能路由，只是凭证没配好 → 去填 Key（可行动）
    #   excluded_channel    —— 通道形态/协议不支持路由 → 填 Key 也没用，别白费力气
    #   disabled_models     —— 厂商就绪、模型被单独停用 → 去模型页启用
    # 把前两者合成一条的话，使用者会在「编程订阅套餐」那些行上反复填 Key，
    # 却永远看不到生效——错误提示把人引向了无效动作。
    blocked_by_provider = sum(1 for _m, p in all_rows
                              if is_channel_supported(p) and not is_provider_routable(p))
    excluded_channel = sum(1 for _m, p in all_rows if not is_channel_supported(p))
    disabled_models = sum(1 for m, p in all_rows
                          if is_provider_routable(p) and not m.enabled)

    ctx = RouterContext(trace_id=trace.new_trace_id(prefix="preview-"),
                        input_text=body.text, token_len=estimate_tokens(body.text),
                        session_id=body.session_id, candidates=sorted(refs.values(), key=lambda r: r.priority))
    from app.deciders import build_decider

    decider_impl = build_decider()
    ctx = await route(ctx, decider_impl, list(rules), refs.get)

    # 候选打分行：**必须复用 pipeline 的 score_candidates**，
    # 否则界面显示的分数与真实选中的模型不同源（曾出现「打分第一 ≠ 实际调用」）。
    candidates: list[dict] = []
    if ctx.hit_layer == "L1" and ctx.final_model:
        candidates.append({"model_id": ctx.final_model.id, "model_name": ctx.final_model.model_name,
                           "display_name": ctx.final_model.display_name, "score": 1.0,
                           "input_price": ctx.final_model.input_price,
                           "eligibility": None, "in_pool": True,
                           "picked": True, "matched_rule": ctx.hit_rule})
        basis = "L1 规则短路：命中路由规则，直接指定目标模型，不经过打分"
    else:
        task_type = ctx.decision.task_type if ctx.decision else None
        rows = score_candidates(task_type, list(ctx.candidates))
        picked_id = ctx.final_model.id if ctx.final_model else None
        for r in rows:
            m = r["model"]
            candidates.append({
                "model_id": m.id, "model_name": m.model_name, "display_name": m.display_name,
                "score": round(r["score"], 4),
                "input_price": m.input_price,
                # 无能力标签 = 该模型不声明自己能干这类活；此时仍可能被成本兜底选中，
                # 界面必须把这点显式说清，否则「为什么是它」无从解释。
                "eligibility": "hit" if r["eligible"] else "none",
                "in_pool": r["in_pool"],
                "picked": m.id == picked_id,
                "matched_rule": None,
            })
        basis = selection_basis(task_type, rows)

    selected = None
    if ctx.final_model:
        selected = {"model_id": ctx.final_model.id, "model_name": ctx.final_model.model_name,
                    "display_name": ctx.final_model.display_name}

    # 执行模式：决策完成后真实调用选中模型（不做降级，成功/失败如实返回）
    execution = None
    if body.execute and ctx.final_model:
        execution = await _execute_selected(ctx, providers, body, request)

    return {"code": 0, "message": "ok", "data": {
        "hit_layer": ctx.hit_layer,
        "task_type": ctx.decision.task_type if ctx.decision else None,
        "selected_model": selected,
        "confidence": ctx.decision.confidence if ctx.decision else (1.0 if ctx.hit_layer == "L1" else None),
        "probabilities": ctx.decision.probabilities if ctx.decision else None,
        "features": ctx.decision.features if ctx.decision else None,
        "candidates": candidates,
        # 候选池口径：routable 才是本次真正参与路由的模型数。
        # 四项互斥且覆盖全部：routable + disabled + blocked + excluded = total_models。
        #   blocked_by_provider = 通道可路由但凭证未配好（缺密钥 / 厂商停用）→ 去填 Key
        #   excluded_channel    = 通道形态或协议不支持路由（编程订阅套餐、暂无适配器的协议）
        "pool": {
            "routable": len(refs),
            "total_models": total_models,
            "disabled_models": disabled_models,
            "blocked_by_provider": blocked_by_provider,
            "excluded_channel": excluded_channel,
        },
        # 一句话解释「为什么是它」：无能力标签时会说明退化为按成本选
        "selection_basis": basis,
        "hit_rule": ctx.hit_rule,
        "fallback_reason": ctx.fallback_reason,
        "latency_ms": ctx.route_latency_ms,
        "trace_id": ctx.trace_id,
        # 调试可观测性：judge_provider 是「配置值」，decider 是「实际产出判定的实现」。
        # 两者不一致（如配置 jev 但 decider 为 None）即表示判定器未生效，不能只看配置。
        "judge_provider": settings.judge_provider,
        "decider": ctx.decision.decider if ctx.decision else None,
        "active_decider": getattr(decider_impl, "name", None),
        "decider_error": getattr(decider_impl, "last_error", None),
        # 执行模式才有值；None = 本次仅决策，未调用上游
        "execution": execution,
    }}


async def _execute_selected(ctx: RouterContext, providers: dict, body: PreviewRequest,
                            request: Request) -> dict:
    """真实调用决策选中的模型，返回结构化输出。

    失败不抛异常、不降级：把错误分类后放进 `error_code`/`error` 原样回传，
    让试跑台能回答「选中模型现在到底能不能用、不能用的原因是什么」。
    """
    from app.adapters import UpstreamError, get_adapter
    from app.core.crypto import decrypt_api_key

    settings = get_settings()
    model = ctx.final_model
    out: dict = {
        "attempted": True, "ok": False,
        "model_id": model.id, "model_name": model.model_name, "display_name": model.display_name,
        "provider_id": model.provider_id, "provider_name": None, "base_url": None,
        "latency_ms": None, "content": None, "finish_reason": None,
        "usage": None, "cost": None, "model_echo": None,
        "error_code": None, "error": None,
    }

    provider = providers.get(model.provider_id)
    if provider is None:
        out.update(error_code="PROVIDER_UNAVAILABLE",
                   error=f"厂商 {model.provider_id} 不存在或已禁用，无法调用")
        _emit_log(ctx, model, body.text, out)
        return out
    out["provider_name"], out["base_url"] = provider.name, provider.base_url

    try:
        api_key = decrypt_api_key(provider.api_key_encrypted)
    except ValueError as e:
        out.update(error_code="KEY_DECRYPT_FAILED",
                   error=f"厂商密钥无法解密（{e}）；请在「厂商接入」重新录入密钥")
        _emit_log(ctx, model, body.text, out)
        return out

    payload: dict = {"messages": [{"role": "user", "content": body.text}], "stream": False}
    if body.max_tokens:
        payload["max_tokens"] = body.max_tokens

    started = time.monotonic()
    try:
        result = await get_adapter().chat(
            base_url=provider.base_url, api_key=api_key, model_name=model.model_name,
            payload=payload, timeout_ms=settings.request_timeout_ms,
            client=request.app.state.http_client,
        )
    except UpstreamError as e:
        out.update(latency_ms=int((time.monotonic() - started) * 1000),
                   error_code="UPSTREAM_UNAVAILABLE", error=str(e))
        _emit_log(ctx, model, body.text, out)
        return out
    except Exception as e:  # 保险丝：任何意外都不得让试跑台 500
        logger.exception("preview execute unexpected error")
        out.update(latency_ms=int((time.monotonic() - started) * 1000),
                   error_code="UPSTREAM_ERROR", error=f"{type(e).__name__}: {e}")
        _emit_log(ctx, model, body.text, out)
        return out

    usage = result.get("usage") or {}
    choice = (result.get("choices") or [{}])[0]
    prompt_tokens = usage.get("prompt_tokens", 0) or 0
    completion_tokens = usage.get("completion_tokens", 0) or 0
    # 推理模型（如 qwen 带 reasoning）的 completion_tokens 含推理 token，单独带出来：
    # 否则「max_tokens=8 却消耗 32 tokens」无法解释，会被误判为参数失效。
    reasoning_tokens = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0
    cost = calc_cost(model.input_price, model.output_price, prompt_tokens, completion_tokens)
    out.update(
        ok=True,
        latency_ms=int((time.monotonic() - started) * 1000),
        content=((choice.get("message") or {}).get("content")),
        finish_reason=choice.get("finish_reason"),
        usage={"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
               "total_tokens": usage.get("total_tokens", prompt_tokens + completion_tokens),
               "reasoning_tokens": reasoning_tokens},
        cost=cost,
        model_echo=result.get("model"),
    )
    _emit_log(ctx, model, body.text, out)
    return out


def _emit_log(ctx: RouterContext, model, text: str, out: dict) -> None:
    """试跑台「执行」模式是**真实上游调用**（有真实成本），必须落 request_log，
    否则「调用时日志没生成」会让使用者误以为系统没在记录。

    关键区分（R-01 的口径边界）：
    - 仅决策（execute=false）：零成本、不调上游 → 不落日志（诊断流量不该污染成功率）。
    - 执行（execute=true）：真实调用 → 落日志，但 trace_id 带 `preview-` 前缀，
      使 /admin/stats/overview 能据此排除，线上成功率口径仍保持纯净。
    """
    usage = out.get("usage") or {}
    logbuffer.enqueue({
        "trace_id": ctx.trace_id,
        "input_text": text,
        "router_output_json": json.dumps({
            "hit_layer": ctx.hit_layer,
            "decider": ctx.decision.decider if ctx.decision else None,
            "task_type": ctx.decision.task_type if ctx.decision else None,
        }, ensure_ascii=False),
        "router_layer": ctx.hit_layer or "L3",
        "final_model_id": model.id,
        "final_model_key": model.model_name,
        "latency_ms": out.get("latency_ms") or 0,
        "route_latency_ms": ctx.route_latency_ms,
        "prompt_tokens": usage.get("prompt_tokens", 0) or 0,
        "completion_tokens": usage.get("completion_tokens", 0) or 0,
        "cost": out.get("cost") or 0.0,
        "status": "success" if out.get("ok") else "error",
        # 失败原因用 error_code 原文（KEY_DECRYPT_FAILED / UPSTREAM_UNAVAILABLE / UPSTREAM_ERROR …），
        # 与 /v1 链路落库的 fallback_reason 同口径，日志页无需区分来源。
        "fallback_reason": (out.get("error_code") or None) if not out.get("ok") else None,
    })
