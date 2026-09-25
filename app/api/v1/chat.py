"""对外统一入口：POST /v1/chat/completions（非流式 + SSE）。

硬约束（基线 3.1.1 / 接口设计说明书 §2.2）：
- 路由决策在首个 token 下发前完成；
- x-router-* 元信息头恒返回 4 项（trace-id / layer / model / confidence）；
  第 5 项 task-type 仅 L2 命中时返回——L1 短路与「显式指定 model」都不经判定器，故无此项；
- 上游失败内部降级，绝不向第三方透出 5xx 裸栈（兜底率 100%）。
"""
import json
import logging
import time

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters import UpstreamError, get_adapter
from app.api.deps import load_routable_models
from app.core.config import get_settings
from app.db.session import get_db
from app.db.tables import Provider, RequestLog, RouteRule
from app.observability import trace
from app.router_engine.context import ModelRef, RouterContext
from app.router_engine.pipeline import route
from app.schemas import ChatCompletionRequest
from app.services import logbuffer
from app.services.tool_calls import (
    ToolCallError,
    append_tool_results,
    execute_tool_call,
    extract_tool_calls,
    filter_registered,
    strip_tool_xml,
)
from app.services.apikeys import authenticate_key, touch_last_used
from app.services.billing import calc_cost, estimate_tokens
from app.services.quota_cache import cache as qcache

logger = logging.getLogger("api.v1.chat")
router = APIRouter(prefix="/v1", tags=["v1"])


def _error(status: int, code: int, message: str, etype: str = "invalid_request_error") -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"message": message, "type": etype, "code": code}})


def _router_headers(ctx: RouterContext, tools: int | None = None) -> dict[str, str]:
    headers = {
        "x-router-trace-id": ctx.trace_id,
        "x-router-layer": ctx.hit_layer or "L3",
        "x-router-model": ctx.final_model.model_name if ctx.final_model else "",
    }
    if tools:  # 仅在真的执行过工具时返回，避免给纯文本调用方增加噪声
        headers["x-router-tools"] = str(tools)
    if ctx.decision is not None:  # 仅 L2：L1 短路不经判定器
        headers["x-router-task-type"] = ctx.decision.task_type
        headers["x-router-confidence"] = f"{ctx.decision.confidence:.4f}"
    else:
        headers["x-router-confidence"] = "1.0"  # L1 恒 1.0；L3 无判定值亦按兜底口径
    return headers


def _log_entry(ctx: RouterContext, input_text: str, model: ModelRef | None, *,
               status: str, reason: str | None, started: float,
               prompt_tokens: int = 0, completion_tokens: int = 0, cost: float = 0.0) -> dict:
    """构造 request_log 条目 —— **集中构造**，避免各处字段漂移。

    必须同时写两个模型字段：
    - `final_model_id`：外键，供统计与关联查询；
    - `final_model_key`：模型名快照。外键会在「删除模型」时被解绑成 NULL，
      只靠外键会让历史日志永远查不出当时真实调用了谁。
    """
    return {
        "trace_id": ctx.trace_id, "input_text": input_text,
        "router_output_json": json.dumps(_decision_snapshot(ctx), ensure_ascii=False),
        "router_layer": ctx.hit_layer or "L3",
        "final_model_id": model.id if model else None,
        "final_model_key": model.model_name if model else None,
        "latency_ms": int((time.monotonic() - started) * 1000),
        "route_latency_ms": ctx.route_latency_ms,
        "prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
        "cost": cost, "status": status, "fallback_reason": reason,
    }


async def _load_route_materials(db: AsyncSession):
    models = await load_routable_models(db)
    refs: dict[int, ModelRef] = {
        mid: ModelRef(
            id=m.id, provider_id=m.provider_id, model_name=m.model_name,
            display_name=m.display_name, capabilities=json.loads(m.capabilities or "[]"),
            input_price=m.input_price, output_price=m.output_price, priority=m.priority,
        )
        for mid, m in models.items()
    }
    rules = (
        await db.execute(select(RouteRule).where(RouteRule.enabled.is_(True)).order_by(RouteRule.priority))
    ).scalars().all()
    providers = {
        p.id: p for p in (
            await db.execute(select(Provider).where(Provider.enabled.is_(True)))
        ).scalars().all()
    }
    candidates = sorted(refs.values(), key=lambda r: r.priority)
    return refs, list(rules), providers, candidates


async def _why_not_routable(db: AsyncSession, model_name: str) -> str | None:
    """模型在库中但不在候选池时给出原因；库里压根没有该模型则返回 None。"""
    from app.db.tables import Model as ModelTable
    from app.db.tables import Provider as ProviderTable
    from app.services.provider_access import provider_unavailable_reason

    row = (await db.execute(
        select(ModelTable, ProviderTable)
        .join(ProviderTable, ModelTable.provider_id == ProviderTable.id)
        .where(ModelTable.model_name == model_name)
    )).first()
    if row is None:
        return None
    model_row, provider_row = row
    # 先判厂商，再判模型。顺序不能反：目录预置的模型天然是「停用」状态
    # （随厂商接入而自动启用），若先报「模型已停用」，使用者会跑去模型页找启用开关，
    # 而真正该做的动作是去「厂商接入」填 Key —— 错误信息必须指向正确的动作。
    reason = provider_unavailable_reason(provider_row)
    if reason:
        return reason
    if not model_row.enabled:
        return "模型已停用"
    return "模型未进入候选池"


MAX_TOOL_ROUNDS = 3
MAX_TOOL_CALLS = 5

_WEB_FETCH_TOOL = {
    "type": "function",
    "function": {
        "name": "WebFetch",
        "description": "抓取指定 URL 的网页内容，并基于该页面回答问题。",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "要抓取的 http/https 公网 URL"},
                "prompt": {"type": "string", "description": "要基于页面内容回答的问题"},
            },
            "required": ["url"],
        },
    },
}


def _strip_pending(result: dict) -> None:
    """把「未能执行」的工具语法从正文摘掉。

    不摘的话，调用方收到的「答案」是一段它无法执行的 XML —— 这正是本次要修的现象。
    """
    choices = result.get("choices") or []
    if not choices:
        return
    message = choices[0].get("message") or {}
    message.pop("tool_calls", None)
    message["content"] = strip_tool_xml(message.get("content"))
    choices[0]["message"] = message


async def _chat_with_tools(*, adapter, provider, api_key, model, payload, request, ctx) -> tuple[dict, dict]:
    """工具执行循环：模型请求工具 → 网关执行 → 结果回灌 → 直至给出最终回答。

    为什么放在网关：下游模型的工具语法不统一（原生 `tool_calls` 与 Qwen 系
    正文 `<tool_call>` 混用），调用方要自己认两种格式才能干活。网关把差异收敛掉，
    对外仍是标准 OpenAI 响应。

    安全边界：只执行白名单工具（当前仅 WebFetch），且目标必须是公网 http/https。
    零命中白名单时**完全不动正文**，退回纯透传语义。
    """
    settings = get_settings()
    client = request.app.state.http_client
    messages: list[dict] = list(payload.get("messages") or [])
    tools = payload.get("tools")
    rounds = executed = 0
    source: str | None = None
    usage_total = {"prompt_tokens": 0, "completion_tokens": 0}

    if not settings.enable_tool_execution:
        # 代执行关闭 = 纯透传：payload 原样下发，上游响应原样返回，一处不改。
        result = await adapter.chat(
            base_url=provider.base_url, api_key=api_key, model_name=model.model_name,
            payload=payload, timeout_ms=settings.request_timeout_ms, client=client,
        )
        return result, {"rounds": 0, "executed": 0, "source": None}

    result: dict = {}
    for _ in range(MAX_TOOL_ROUNDS + 1):
        body = {**payload, "messages": messages}
        if tools:
            body["tools"] = tools
        result = await adapter.chat(
            base_url=provider.base_url, api_key=api_key, model_name=model.model_name,
            payload=body, timeout_ms=settings.request_timeout_ms, client=client,
        )
        usage = result.get("usage") or {}
        usage_total["prompt_tokens"] += usage.get("prompt_tokens", 0) or 0
        usage_total["completion_tokens"] += usage.get("completion_tokens", 0) or 0

        calls, kind = extract_tool_calls(result)
        calls = filter_registered(calls)  # 未注册工具不接管，保持透传
        if not calls:
            break
        if rounds >= MAX_TOOL_ROUNDS or executed + len(calls) > MAX_TOOL_CALLS:
            logger.warning("tool loop limit reached rounds=%s executed=%s", rounds, executed)
            _strip_pending(result)
            break

        source = source or kind
        message = ((result.get("choices") or [{}])[0].get("message")) or {}
        # 回灌历史一律用原生 tool_calls 形态：XML 派生的调用也还原成原生，
        # 否则模型看到自己上一条仍是 XML，会继续按 XML 吐，循环停不下来。
        # content 用空串而非 null：带 tool_calls 的 assistant 消息，部分上游（通义）
        # 对 `content: null` 会直接 400，空串则被普遍接受。
        cleaned = strip_tool_xml(message.get("content")) or ""
        messages.append({"role": "assistant", "content": cleaned, "tool_calls": calls})
        if not tools:
            tools = [_WEB_FETCH_TOOL]  # 模型自发调用：补上工具定义，让续写有据可依
            body["tools"] = tools

        results = []
        for call in calls:
            fn = (call.get("function") or {}).get("name")
            try:
                out = await execute_tool_call(call, client, settings.request_timeout_ms)
                logger.info("tool ok trace=%s tool=%s arg=%s bytes=%s",
                            ctx.trace_id, fn,
                            (call.get("function") or {}).get("arguments", "")[:200], len(out))
                results.append(out)
            except ToolCallError as e:
                # 工具失败同样回灌：模型必须知道「取不到」，才能改口径或换 URL，
                # 而不是继续假装手里有数据。
                logger.info("tool fail trace=%s tool=%s err=%s", ctx.trace_id, fn, e)
                results.append(json.dumps({"error": str(e)}, ensure_ascii=False))
            except Exception as e:
                logger.exception("tool execute unexpected error")
                results.append(json.dumps({"error": f"{type(e).__name__}: {e}"}, ensure_ascii=False))
        append_tool_results(messages, calls, results)
        executed += len(calls)
        rounds += 1

    if usage_total["prompt_tokens"] or usage_total["completion_tokens"]:
        # 工具循环是多轮上游调用，用量必须累计 —— 只报最后一轮会系统性少算成本。
        # total_tokens 必须跟着重算：直接沿用末轮的 total 会出现「prompt(546) > total(355)」
        # 这种自相矛盾的账单，上游与我们的口径都对不上。
        merged = {**(result.get("usage") or {}), **usage_total}
        merged["total_tokens"] = merged["prompt_tokens"] + merged["completion_tokens"]
        result["usage"] = merged
    return result, {"rounds": rounds, "executed": executed, "source": source}


@router.post("/chat/completions")
async def chat_completions(body: ChatCompletionRequest, request: Request, db: AsyncSession = Depends(get_db)):
    settings = get_settings()
    # ---- 鉴权：校验第三方调用密钥（api_key 表；管理端「第三方接入」页生成） ----
    auth = request.headers.get("Authorization", "")
    token = auth[7:] if auth.startswith("Bearer ") else None
    if not token:
        return _error(401, 1001, "missing or invalid API key", "authentication_error")
    api_key_row = await authenticate_key(db, token)
    if api_key_row is None:
        # 不区分「不存在 / 已停用 / 已过期」——细节只回给攻击者，调用方统一只需「Key 无效」
        return _error(401, 1001, "invalid API key", "authentication_error")
    await touch_last_used(db, api_key_row.id)  # 供控制台识别 Key 是否真的在用

    # ---- 限流（Redis 可降级）：按 key 记录的前缀分桶，与 Key 本身等值隔离 ----
    ok, _count = await qcache.incr_window(f"ratelimit:{api_key_row.key_hash[:12]}", 60, 60)
    if not ok:
        return _error(429, 2001, "rate limit exceeded", "rate_limit_error")

    input_text = "\n".join(m.content for m in body.messages if m.role == "user")
    refs, rules, providers, candidates = await _load_route_materials(db)

    # ---- 显式指定模型：跳过路由（基线：L1 的「显式指定」形态） ----
    if body.model != "auto":
        target = next((r for r in refs.values() if r.model_name == body.model), None)
        if target is None:
            # 区分「池里根本没有这个模型」与「模型在、但厂商未接入」。
            # 内置厂商目录预置后，后者会非常常见（只是还没填 Key）。若一律回 not found，
            # 使用者会去反复核对模型名，而不是去补密钥——错误信息必须把人指向正确的动作。
            blocked = await _why_not_routable(db, body.model)
            if blocked is None:
                return _error(404, 1004, f"model '{body.model}' not found in pool")
            return _error(503, 3002, f"model '{body.model}' is not routable: {blocked}", "api_error")
        ctx = RouterContext(trace_id=trace.new_trace_id(), input_text=input_text,
                            token_len=estimate_tokens(input_text), candidates=[target])
        ctx.hit_layer = "L1"
        ctx.final_model = target
    else:
        if not candidates:
            return _error(503, 3002, "no available model in pool", "api_error")
        from app.deciders import build_decider

        ctx = RouterContext(trace_id=trace.new_trace_id(), input_text=input_text,
                            token_len=estimate_tokens(input_text), candidates=candidates)
        ctx = await route(ctx, build_decider(), rules, refs.get)

    if ctx.final_model is None:  # 理论不可达（pipeline 恒产出），保险丝
        return _error(503, 3002, "routing failed", "api_error")

    model = ctx.final_model
    # 故障转移候选：仅 auto 路由模式参与 failover；显式指定 model 时尊重用户选择，不顺带其他模型
    fallback_candidates = candidates if body.model == "auto" else []
    provider = providers.get(model.provider_id)
    if provider is None:
        return _error(503, 3002, "model provider unavailable", "api_error")

    from app.core.crypto import decrypt_api_key

    started = time.monotonic()
    payload = body.upstream_payload()

    # ---- 非流式 ----
    if not body.stream:
        try:
            api_key = decrypt_api_key(provider.api_key_encrypted)
        except ValueError:
            # 密文非法/密钥不匹配 = 上游不可用，走降级而非 5xx 裸抛
            logbuffer.enqueue(_log_entry(ctx, input_text, model, status="error",
                                         reason="KEY_DECRYPT_FAILED", started=started))
            return await _chat_with_fallback(body, request, db, ctx, refs, rules, providers, fallback_candidates, started)
        try:
            adapter = get_adapter()
            result, tool_stats = await _chat_with_tools(
                adapter=adapter, provider=provider, api_key=api_key, model=model,
                payload=payload, request=request, ctx=ctx,
            )
            ctx.tool_stats = tool_stats
            usage = result.get("usage", {})
            cost = calc_cost(model.input_price, model.output_price,
                             usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0))
            logbuffer.enqueue(_log_entry(
                ctx, input_text, model, status="success", reason=ctx.fallback_reason,
                started=started,
                prompt_tokens=usage.get("prompt_tokens", 0) or 0,
                completion_tokens=usage.get("completion_tokens", 0) or 0,
                cost=cost))
            return JSONResponse(content=result,
                                headers=_router_headers(ctx, tools=tool_stats["executed"]))
        except UpstreamError as e:
            # 必须留下上游原文：否则「首选失败 → 降级 → 最终 502」这条链上
            # 一点线索都没有，只能靠猜（本轮就踩过：NameError 被兜底成 502）。
            logger.warning("primary upstream failed trace=%s model=%s detail=%s",
                           ctx.trace_id, model.model_name, e)
            return await _chat_with_fallback(body, request, db, ctx, refs, rules, providers, fallback_candidates, started)
        except Exception:
            logger.exception("upstream unexpected error")
            logbuffer.enqueue(_log_entry(ctx, input_text, model, status="error",
                                         reason=ctx.fallback_reason or "UPSTREAM_ERROR",
                                         started=started))
            return JSONResponse(status_code=502,
                                content={"error": {"message": "all candidates failed",
                                                   "type": "api_error", "code": 3002}},
                                headers=_router_headers(ctx))

    # ---- 流式（SSE）---- 含候选池故障转移（failover）
    return await _stream_response(body, request, ctx, started, input_text, fallback_candidates, providers)


async def _chat_with_fallback(body, request, db, ctx, refs, rules, providers, candidates, started):
    """目标模型失败 → 按 priority 遍历候选池逐个重试，直到命中一个可用或穷尽。

    故障转移（failover）与「路由判定」是两回事：判定（L1/L2/L3）在首 token 前已定死首选，
    这里只在首选不可用时换一个候选执行，不改变判定结果。候选按 priority 升序尝试，
    命中第一个可用的即返回，满足「一个模型不通自动切到好的」。

    注意 id 空间：`candidates` 是 ModelRef（键为 **model_id**），
    `providers` 是以 **provider_id** 为键的字典——必须用 `candidate.provider_id` 查厂商。
    """
    settings = get_settings()
    input_text = "\n".join(m.content for m in body.messages if m.role == "user")
    tried = {ctx.final_model.id}
    for candidate in candidates:
        if candidate.id in tried or candidate.provider_id not in providers:
            continue
        tried.add(candidate.id)
        provider = providers[candidate.provider_id]
        # 注意：此处**不**提前改写 ctx.final_model。
        # 它是决策结果，也是 502 响应头 x-router-model 与落库 final_model_id 的取值来源；
        # 提前覆盖会让「最后尝试但失败的候选」冒充决策结果，导致响应头与日志对不上。
        ctx.fallback_reason = f"UPSTREAM_UNAVAILABLE:{candidate.model_name}"
        from app.core.crypto import decrypt_api_key

        # 密文非法 = 该候选上游不可用，跳到下一个候选（不得中断整条降级链）
        try:
            api_key = decrypt_api_key(provider.api_key_encrypted)
        except ValueError:
            logger.warning("fallback: key decrypt failed, model=%s", candidate.model_name)
            continue

        try:
            result, tool_stats = await _chat_with_tools(
                adapter=get_adapter(), provider=provider, api_key=api_key,
                model=candidate, payload=body.upstream_payload(), request=request, ctx=ctx,
            )
            ctx.final_model = candidate  # 仅成功后更新：响应头即实际 Serving 的模型
            usage = result.get("usage") or {}
            pt = usage.get("prompt_tokens", 0) or 0
            ct = usage.get("completion_tokens", 0) or 0
            # 降级成功同样必须落 token 与成本：此前这条路径不记用量，
            # 于是「用量与成本」长期漏掉所有「首选失败、降级成功」的请求。
            logbuffer.enqueue(_log_entry(
                ctx, input_text, candidate, status="success", reason=ctx.fallback_reason,
                started=started, prompt_tokens=pt, completion_tokens=ct,
                cost=calc_cost(candidate.input_price, candidate.output_price, pt, ct)))
            return JSONResponse(content=result,
                                headers=_router_headers(ctx, tools=tool_stats["executed"]))
        except UpstreamError:
            continue
        except Exception:
            logger.exception("fallback unexpected error, model=%s", candidate.model_name)
            continue
    # 基线 3.1.1：x-router-* 恒返回，全失败也不例外。
    # 但「全失败」同样是既成事实的调用，必须落一条 error 日志 ——
    # 此前这条路径什么都不写，日志里会凭空少掉请求（调用发生过、日志里查不到）。
    logbuffer.enqueue(_log_entry(
        ctx, input_text, ctx.final_model, status="error",
        reason=ctx.fallback_reason or "UPSTREAM_UNAVAILABLE", started=started))
    return JSONResponse(status_code=502,
                        content={"error": {"message": "all candidates failed",
                                           "type": "api_error", "code": 3002}},
                        headers=_router_headers(ctx))


def _rebuild_chunk(chunk: dict | None, content: str, finish_reason: str | None = None) -> bytes:
    """重建一个 SSE chunk（仅用于「工具轮超限」这类必须把正文补发的兜底场景）。"""
    base = chunk or {}
    payload = {
        "id": base.get("id") or "chatcmpl-llmbridge",
        "object": "chat.completion.chunk",
        "created": base.get("created") or int(time.time()),
        "model": base.get("model") or "",
        "choices": [{"index": 0,
                     "delta": {"role": "assistant", "content": content},
                     "finish_reason": finish_reason}],
    }
    return b"data: " + json.dumps(payload, ensure_ascii=False).encode("utf-8") + b"\n\n"


def _extract_stream_usage(chunk: bytes) -> dict:
    """从 SSE 数据块里取出 `usage`（OpenAI 兼容：末尾 chunk 带 usage、choices 为空数组）。

    仅用于落库记账；非 SSE 行、[DONE]、解析失败一律返回 {} ——
    记账失败绝不能影响转发。
    """
    try:
        line = chunk.decode("utf-8", "ignore").strip()
        if line.startswith("data:"):
            line = line[5:].strip()
        if not line or line == "[DONE]":
            return {}
        return json.loads(line).get("usage") or {}
    except Exception:
        return {}


def _usage_chunk(usage: dict, model_name: str) -> bytes:
    """流式收尾的用量包（choices 为空数组，OpenAI 兼容惯例）。

    工具循环会产生多轮上游调用，逐轮透传 usage 会让调用方按单轮记账、
    而我们按累计记账——同一次请求两个成本数字。故统一在末尾发一次累计值。
    """
    payload = {
        "id": "chatcmpl-llmbridge-usage", "object": "chat.completion.chunk",
        "created": int(time.time()), "model": model_name, "choices": [], "usage": usage,
    }
    return b"data: " + json.dumps(payload, ensure_ascii=False).encode("utf-8") + b"\n\n"


async def _stream_round(*, adapter, provider, api_key, model, payload, request, outcome: dict,
                        detect_tools: bool = True):
    """跑一轮上游流式调用；判定为文本轮时增量下行，工具轮则整轮静默吞掉。

    为什么需要「探测窗」：工具语法是通过 `delta.content` 逐字下发的，等整轮收完再判断
    就已经把 `<tool_call>` 吐给调用方了。因此在开头 24 字符内先攒着不发，
    一旦确认是正常回答就立刻补发并回归逐 chunk 透传——流式体验几乎无损。

    `detect_tools=False`（代执行关闭）时直接按文本轮处理：不做判定、不做缓冲，
    与改动前的纯透传行为完全一致。
    """
    settings = get_settings()
    mode = "text" if not detect_tools else "undecided"
    pending: list[bytes] = []
    content_parts: list[str] = []
    tool_acc: dict[int, dict] = {}
    usage: dict = {}
    outcome.update(kind=None, content="", tool_calls=[], usage={}, had_usage=False)

    async for raw_line in adapter.chat_stream(
        base_url=provider.base_url, api_key=api_key, model_name=model.model_name,
        payload=payload, timeout_ms=settings.request_timeout_ms,
        client=request.app.state.http_client,
    ):
        line = raw_line.strip()
        if not line.startswith(b"data:"):
            continue
        body_bytes = line[5:].strip()
        if not body_bytes or body_bytes == b"[DONE]":
            continue  # [DONE] 由外层在所有轮次结束后统一发一次
        try:
            chunk = json.loads(body_bytes)
        except Exception:
            continue
        if chunk.get("usage"):
            usage = chunk["usage"]
            outcome["had_usage"] = True
            if not chunk.get("choices"):
                continue  # 用量单独成包：不转发，由外层统一发累计值
            # 夹带 finish_reason 的末包：掐掉 usage 再转发，避免调用方按单轮值记账，
            # 而我们按累计值记账 —— 同一次请求两个数字。
            chunk = {k: v for k, v in chunk.items() if k != "usage"}
            line = b"data: " + json.dumps(chunk, ensure_ascii=False).encode("utf-8")
        choice = (chunk.get("choices") or [{}])[0]
        delta = choice.get("delta") or {}

        for tc in (delta.get("tool_calls") or []) if detect_tools else []:
            slot = tool_acc.setdefault(tc.get("index", 0), {
                "id": "", "type": "function", "function": {"name": "", "arguments": ""}})
            if tc.get("id"):
                slot["id"] = tc["id"]
            fn = tc.get("function") or {}
            if fn.get("name"):
                slot["function"]["name"] = fn["name"]
            if fn.get("arguments"):
                slot["function"]["arguments"] += fn["arguments"]
            mode = "tool"

        text = delta.get("content")
        if text:
            content_parts.append(text)
        if mode == "undecided" and text:
            joined = "".join(content_parts)
            if "<tool_call>" in joined or joined.lstrip().startswith("<tool"):
                mode = "tool"
            elif len(joined) >= 24 or "\n" in joined:
                mode = "text"
                for piece in pending:  # 补发探测期攒下的原始行，字段（finish_reason 等）不丢
                    yield piece
                pending.clear()

        if mode == "text":
            yield line.rstrip(b"\n") + b"\n\n"
        elif mode == "undecided":
            pending.append(line.rstrip(b"\n") + b"\n\n")

    if mode == "undecided":
        for piece in pending:
            yield piece
        pending.clear()

    joined = "".join(content_parts)
    outcome["content"] = joined
    if tool_acc:
        outcome["tool_calls"] = [tool_acc[i] for i in sorted(tool_acc)]
    outcome["usage"] = usage
    outcome["kind"] = "tool" if (outcome["tool_calls"] or mode == "tool") else "text"


async def _stream_response(body, request, ctx, started, input_text, candidates, providers):
    """SSE 入口，含候选池故障转移（failover）。

    故障转移语义与非流式一致：路由判定（首 token 前定死首选）不变，仅在首选不可用时
    按顺序（priority 升序）切换候选。流式物理限制：一旦已向调用方下行任何内容，
    便无法重来另一个模型，只能报错结束；因此 failover 只在首内容下行前
    （通常是连接或首包失败）才发生，这也是模型不通最常见的失败点。

    candidates 为空（显式指定 model 的场景）时，ordered 仅含首选，不发生切换。
    """
    settings = get_settings()
    headers = _router_headers(ctx)
    adapter = get_adapter()
    base_payload = body.upstream_payload()
    execute_tools = settings.enable_tool_execution

    ordered = [ctx.final_model] + [c for c in candidates if ctx.final_model and c.id != ctx.final_model.id]
    attempted = set()
    _SSE_NL = bytes((10, 10))  # SSE 分隔符，用 bytes 构造避免转义歧义

    async def gen():
        from app.core.crypto import decrypt_api_key

        usage_acc = {"prompt_tokens": 0, "completion_tokens": 0}
        saw_usage = False
        yielded_any = False
        status, reason = "success", ctx.fallback_reason
        last_reason = None
        attempt = ctx.final_model
        messages = list(base_payload.get("messages") or [])
        tools = base_payload.get("tools")
        executed = rounds = 0

        try:
            for attempt in ordered:
                if attempt is None or attempt.id in attempted:
                    continue
                attempted.add(attempt.id)
                provider = providers.get(attempt.provider_id)
                if provider is None:
                    continue
                try:
                    api_key = decrypt_api_key(provider.api_key_encrypted)
                except ValueError:
                    last_reason = f"KEY_DECRYPT_FAILED:{attempt.model_name}"
                    logger.warning("stream: key decrypt failed, model=%s", attempt.model_name)
                    continue

                if not execute_tools:
                    try:
                        async for chunk in adapter.chat_stream(
                            base_url=provider.base_url, api_key=api_key, model_name=attempt.model_name,
                            payload=base_payload, timeout_ms=settings.request_timeout_ms,
                            client=request.app.state.http_client,
                        ):
                            if b'"usage"' in chunk:
                                usage = _extract_stream_usage(chunk)
                                if usage:
                                    for key in ("prompt_tokens", "completion_tokens"):
                                        usage_acc[key] = usage.get(key, 0) or 0
                            yielded_any = True
                            yield chunk
                        break
                    except UpstreamError:
                        last_reason = f"UPSTREAM_UNAVAILABLE:{attempt.model_name}"
                        logger.warning("stream upstream failed (pass-through), model=%s, yielded=%s", attempt.model_name, yielded_any)
                        if yielded_any:
                            status, reason = "error", last_reason
                            yield b'{"error": {"message": "upstream unavailable", "code": 3002}}' + _SSE_NL
                            return
                        continue
                    except Exception:
                        logger.exception("stream upstream unexpected error (pass-through)")
                        last_reason = f"UPSTREAM_ERROR:{attempt.model_name}"
                        if yielded_any:
                            status, reason = "error", last_reason
                            yield b'{"error": {"message": "upstream error", "code": 3002}}' + _SSE_NL
                            return
                        continue

                try:
                    for _att in range(MAX_TOOL_ROUNDS + 1):
                        round_payload = {**base_payload, "messages": messages}
                        if tools:
                            round_payload["tools"] = tools
                        outcome = {}
                        async for piece in _stream_round(
                            adapter=adapter, provider=provider, api_key=api_key, model=attempt,
                            payload=round_payload, request=request, outcome=outcome,
                            detect_tools=execute_tools,
                        ):
                            yielded_any = True
                            yield piece
                        usage = outcome.get("usage") or {}
                        for key in ("prompt_tokens", "completion_tokens"):
                            usage_acc[key] += usage.get(key, 0) or 0
                        saw_usage = saw_usage or bool(outcome.get("had_usage"))

                        shadow = {"choices": [{"message": {
                            "content": outcome.get("content"),
                            "tool_calls": outcome.get("tool_calls") or None}}]}
                        calls, _kind = extract_tool_calls(shadow)
                        calls = filter_registered(calls) if execute_tools else []
                        if not calls:
                            break
                        if rounds >= MAX_TOOL_ROUNDS or executed + len(calls) > MAX_TOOL_CALLS:
                            logger.warning("stream tool loop limit reached rounds=%s executed=%s", rounds, executed)
                            yield _rebuild_chunk(None, outcome.get("content") or "", finish_reason="stop")
                            break

                        messages.append({
                            "role": "assistant",
                            "content": strip_tool_xml(outcome.get("content")) or "",
                            "tool_calls": calls,
                        })
                        if not tools:
                            tools = [_WEB_FETCH_TOOL]
                        results = []
                        for call in calls:
                            fn = (call.get("function") or {}).get("name")
                            try:
                                out = await execute_tool_call(
                                    call, request.app.state.http_client, settings.request_timeout_ms)
                                logger.info("stream tool ok trace=%s tool=%s arg=%s bytes=%s",
                                            ctx.trace_id, fn,
                                            (call.get("function") or {}).get("arguments", "")[:200], len(out))
                                results.append(out)
                            except ToolCallError as e:
                                logger.info("stream tool fail trace=%s tool=%s err=%s", ctx.trace_id, fn, e)
                                results.append(json.dumps({"error": str(e)}, ensure_ascii=False))
                            except Exception as e:
                                logger.exception("stream tool execute unexpected error")
                                results.append(json.dumps({"error": f"{type(e).__name__}: {e}"}, ensure_ascii=False))
                        append_tool_results(messages, calls, results)
                        executed += len(calls)
                        rounds += 1
                    break
                except UpstreamError:
                    last_reason = f"UPSTREAM_UNAVAILABLE:{attempt.model_name}"
                    logger.warning("stream upstream failed, model=%s, yielded=%s", attempt.model_name, yielded_any)
                    if yielded_any:
                        status, reason = "error", last_reason
                        yield b'{"error": {"message": "upstream unavailable", "code": 3002}}' + _SSE_NL
                        return
                    continue
                except Exception:
                    logger.exception("stream upstream unexpected error")
                    last_reason = f"UPSTREAM_ERROR:{attempt.model_name}"
                    if yielded_any:
                        status, reason = "error", last_reason
                        yield b'{"error": {"message": "upstream error", "code": 3002}}' + _SSE_NL
                        return
                    continue
            else:
                status, reason = "error", last_reason or "UPSTREAM_UNAVAILABLE"
                yield b'{"error": {"message": "all candidates failed", "code": 3002}}' + _SSE_NL
                return

            ctx.tool_stats = {"rounds": rounds, "executed": executed}
            if saw_usage:
                usage_acc["total_tokens"] = usage_acc["prompt_tokens"] + usage_acc["completion_tokens"]
                yield _usage_chunk(usage_acc, attempt.model_name)
            yield b"data: [DONE]" + _SSE_NL
        except Exception:
            logger.exception("stream generator unexpected error")
            status, reason = "error", reason or "UPSTREAM_ERROR"
            if not yielded_any:
                yield b'{"error": {"message": "upstream error", "code": 3002}}' + _SSE_NL
        finally:
            pt = usage_acc.get("prompt_tokens", 0) or 0
            ct = usage_acc.get("completion_tokens", 0) or 0
            logbuffer.enqueue(_log_entry(
                ctx, input_text, attempt, status=status, reason=reason, started=started,
                prompt_tokens=pt, completion_tokens=ct,
                cost=calc_cost(attempt.input_price or 0, attempt.output_price or 0, pt, ct)))

    return StreamingResponse(gen(), media_type="text/event-stream", headers=headers)


def _decision_snapshot(ctx: RouterContext) -> dict:
    snap = {"hit_layer": ctx.hit_layer, "fallback_reason": ctx.fallback_reason}
    # 工具执行情况落进决策快照：否则「这次到底调没调工具」在日志里查无实据，
    # 只能靠成本数字反推。
    stats = getattr(ctx, "tool_stats", None)
    if stats:
        snap["tools"] = stats
    if ctx.decision:
        snap.update({
            "task_type": ctx.decision.task_type,
            "confidence": ctx.decision.confidence,
            "probabilities": ctx.decision.probabilities,  # 概率分布落库 = 可解释性来源
            "features": ctx.decision.features,
            "decider": ctx.decision.decider,
        })
    return snap
