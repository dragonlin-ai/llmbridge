"""厂商接入点管理：CRUD + 连通性测试。密钥只存密文、只回掩码。"""
import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user, require_admin, validate_base_url
from app.core.config import get_settings
from app.core.crypto import encrypt_api_key, mask_token
from app.db.session import get_db
from app.db.tables import Model, Provider
from app.schemas import ProviderIn, ProviderUpdate
from app.data.provider_catalog import ACCESS_KINDS, PROTOCOLS
from app.services.provider_access import (
    access_kind_label,
    access_kind_of,
    has_usable_key,
    is_channel_supported,
    is_provider_routable,
    is_subscription_channel,
    protocol_label,
    protocol_of,
    routable_blockers,
    terms_note_of,
)

logger = logging.getLogger("api.admin.providers")
router = APIRouter(prefix="/admin/providers", tags=["admin-providers"])


def _mask(p: Provider) -> str:
    return mask_token(p.api_key_encrypted)


def _dump(p: Provider, model_count: int = 0) -> dict:
    """厂商通道对外表示。

    三个状态字段刻意分开，因为它们是三个不同的问题：

    - `has_key`  「凭证配好了吗」——与路由能力无关
    - `enabled`  「开关打开了吗」
    - `routable` 「真的能进候选池吗」= 已启用 + 密钥可用 + 形态/协议被支持

    只用一个 `routable` 会让使用者不知道「为什么不可路由、该改什么」；
    所以另给 `routable_blockers`，把**配置解决不了**的原因直接列出来，
    避免把人引向「再填个 Key 试试」这种无效动作。

    `terms_note` 是厂商官方条款警示（订阅类通道通常有值）。
    订阅套餐已纳入路由，风险从「被系统挡住」变成「使用者自己承担」，
    所以这条警示必须能到达界面——否则就是默默替使用者做了决定。
    `is_subscription` 让前端把「单价只是参照值、不是真实边际成本」讲清楚。
    """
    has_key = has_usable_key(p.api_key_encrypted)
    return {"id": p.id, "name": p.name, "base_url": p.base_url,
            "vendor": p.vendor,
            "access_kind": access_kind_of(p),
            "access_kind_label": access_kind_label(p),
            "protocol": protocol_of(p),
            "protocol_label": protocol_label(p),
            "api_key_masked": _mask(p), "enabled": p.enabled,
            "remark": p.remark,
            "terms_note": terms_note_of(p),
            "is_subscription": is_subscription_channel(p),
            "has_key": has_key,
            "routable": is_provider_routable(p),
            "routable_blockers": routable_blockers(p),
            "model_count": model_count,
            "created_at": str(p.created_at)}


def _validate_channel_enums(access_kind: str | None, protocol: str | None) -> None:
    """校验接入形态与协议取值。

    数据库虽有两个 CHECK 约束兜底，但撞约束会变成 500，看不出是哪个字段填错了。
    在这里先拦下才能给出「可选值是哪些」这种可行动的提示。
    """
    if access_kind is not None and access_kind not in ACCESS_KINDS:
        raise HTTPException(status_code=400, detail={
            "code": 1006,
            "message": f"access_kind 非法：{access_kind}（可选 {'/'.join(ACCESS_KINDS)}）"})
    if protocol is not None and protocol not in PROTOCOLS:
        raise HTTPException(status_code=400, detail={
            "code": 1006,
            "message": f"protocol 非法：{protocol}（可选 {'/'.join(PROTOCOLS)}）"})


@router.get("")
async def list_providers(page: int = 1, page_size: int = 20,
                         db: AsyncSession = Depends(get_db), _u: dict = Depends(current_user)):
    """厂商通道列表。

    排序刻意按 (vendor, id)：同一厂商的多条接入通道在列表里天然相邻，
    前端据此直接聚成一张厂商卡片，无需在客户端再分组排序。
    """
    total = len((await db.execute(select(Provider.id))).all())
    rows = (await db.execute(
        select(Provider)
        .order_by(Provider.vendor.asc().nulls_last(), Provider.id.asc())
        .offset((page - 1) * page_size).limit(page_size)
    )).scalars().all()
    counts = dict((await db.execute(
        select(Model.provider_id, func.count(Model.id)).group_by(Model.provider_id)
    )).all())
    return {"code": 0, "message": "ok", "data": {"total": total, "page": page,
            "page_size": page_size, "items": [_dump(r, counts.get(r.id, 0)) for r in rows]}}


@router.post("")
async def create_provider(body: ProviderIn, db: AsyncSession = Depends(get_db), _u: dict = Depends(require_admin)):
    validate_base_url(body.base_url, allow_local=get_settings().allow_local_base_url)
    _validate_channel_enums(body.access_kind, body.protocol)
    exists = (await db.execute(select(Provider).where(Provider.name == body.name))).scalar_one_or_none()
    if exists:
        raise HTTPException(status_code=409, detail={"code": 1005, "message": "厂商名称已存在"})
    p = Provider(name=body.name, base_url=body.base_url,
                 api_key_encrypted=encrypt_api_key(body.api_key), remark=body.remark,
                 terms_note=body.terms_note,
                 vendor=body.vendor, access_kind=body.access_kind, protocol=body.protocol)
    db.add(p)
    await db.commit()
    await db.refresh(p)
    return {"code": 0, "message": "ok", "data": _dump(p)}


@router.put("/{provider_id}")
async def update_provider(provider_id: int, body: ProviderUpdate,
                          db: AsyncSession = Depends(get_db), _u: dict = Depends(require_admin)):
    """更新厂商。

    特殊行为（「只填一个 Key 就能接入」的落点）：当本次是**首次**为该厂商录入密钥
    （此前无可用密钥 → 现在可用），并且请求没有显式指定 `enabled` 时，
    自动把厂商置为启用，并同时启用该厂商名下尚未启用的目录模型；
    响应里用 `auto_enabled` 如实回报这次顺手改了什么。

    为什么需要它：目录预置的厂商与模型初始都是停用状态。如果填完 Key 还得再去
    逐个点「启用」，「接入成本 = 一个 Key」这个承诺就不成立。
    副作用不静默——被启用的模型名会列在响应里，界面据此提示。

    例外：若这条通道的形态/协议本身不参与路由（当前目录内已无此类通道，
    但保留该分支以防将来出现未支持的形态），则只记录密钥、不自动启用，
    并在 `auto_enabled.skipped_reason` 里说明原因。
    否则界面会显示「已接入」，而它的模型永远进不了候选池——状态在骗人。

    订阅类套餐现在是**会**被自动启用的（它们已纳入路由）。为了不把合规风险
    埋进「顺手启用」这个动作里，`auto_enabled.terms_note` 会带上厂商官方条款原文，
    由界面在同一时刻提示——启用与知情应当同时发生。
    """
    p = await db.get(Provider, provider_id)
    if p is None:
        raise HTTPException(status_code=404, detail={"code": 1004, "message": "provider 不存在"})

    had_key = has_usable_key(p.api_key_encrypted)

    if body.base_url:
        validate_base_url(body.base_url, allow_local=get_settings().allow_local_base_url)
        p.base_url = body.base_url
    if body.name:
        p.name = body.name
    if body.vendor is not None:
        p.vendor = body.vendor or None          # 空串 = 清空分组，退化为独立厂商
    if body.access_kind is not None:
        _validate_channel_enums(body.access_kind, None)
        p.access_kind = body.access_kind
    if body.protocol is not None:
        _validate_channel_enums(None, body.protocol)
        p.protocol = body.protocol
    if body.remark is not None:
        p.remark = body.remark
    if body.terms_note is not None:
        p.terms_note = body.terms_note or None
    if body.enabled is not None:
        p.enabled = body.enabled
    if body.api_key:  # 不传 = 不修改（安全方案 §2.2）
        p.api_key_encrypted = encrypt_api_key(body.api_key.strip())

    auto_enabled: dict | None = None
    if body.api_key and not had_key and has_usable_key(p.api_key_encrypted):
        blockers = routable_blockers(p)
        if blockers:
            # 形态/协议不被支持的通道**不**自动启用。
            # 自动打开一批永远进不了候选池的模型，只会制造「看起来已接入」的假象——
            # 使用者以为配好了，实际一次都调不通（D-28 同类问题）。
            auto_enabled = {"provider_enabled": p.enabled, "models_enabled": [],
                            "skipped_reason": blockers[0]}
            logger.info("provider %s 首次录入密钥，但通道不参与路由，跳过自动启用：%s",
                        p.name, blockers[0])
        else:
            rows = (await db.execute(
                select(Model).where(Model.provider_id == provider_id)
            )).scalars().all()
            activated = [m.model_name for m in rows if not m.enabled]
            for m in rows:
                m.enabled = True
            if body.enabled is None:
                p.enabled = True
            auto_enabled = {"provider_enabled": p.enabled, "models_enabled": activated}
            if terms_note_of(p):
                auto_enabled["terms_note"] = terms_note_of(p)
            logger.info("provider %s 首次接入：自动启用 %d 个模型", p.name, len(activated))

    await db.commit()
    return {"code": 0, "message": "ok", "data": {**_dump(p), "auto_enabled": auto_enabled}}


@router.delete("/{provider_id}")
async def delete_provider(provider_id: int, db: AsyncSession = Depends(get_db), _u: dict = Depends(require_admin)):
    p = await db.get(Provider, provider_id)
    if p is None:
        raise HTTPException(status_code=404, detail={"code": 1004, "message": "provider 不存在"})
    linked = (await db.execute(select(Model).where(Model.provider_id == provider_id))).scalars().first()
    if linked:
        raise HTTPException(status_code=409, detail={"code": 1005, "message": "存在关联模型，禁止删除"})
    await db.delete(p)
    await db.commit()
    return {"code": 0, "message": "ok", "data": None}


@router.post("/{provider_id}/test")
async def test_provider(provider_id: int,
                        db: AsyncSession = Depends(get_db), _u: dict = Depends(current_user)):
    """连通性测试：GET {base_url}/models 探活。

    这套探法只对 OpenAI 兼容协议成立。其它协议（如 Anthropic）根本没有 /models 端点，
    照发请求只会得到一个与真实可用性无关的 404——所以直接回报「本测试不适用」，
    而不是给一个会把人引偏的「不可达」。
    """
    p = await db.get(Provider, provider_id)
    if p is None:
        raise HTTPException(status_code=404, detail={"code": 1004, "message": "provider 不存在"})
    if protocol_of(p) != "openai":
        return {"code": 0, "message": "ok",
                "data": {"ok": False, "applicable": False, "latency_ms": 0,
                         "detail": f"本测试仅适用于 OpenAI 兼容协议；该通道为 {protocol_label(p)}"}}
    if not has_usable_key(p.api_key_encrypted):
        return {"code": 0, "message": "ok",
                "data": {"ok": False, "applicable": False, "latency_ms": 0,
                         "detail": "尚未配置密钥，无法测试"}}

    import time

    from app.core.crypto import decrypt_api_key

    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(
                f"{p.base_url.rstrip('/')}/models",
                headers={"Authorization": f"Bearer {decrypt_api_key(p.api_key_encrypted)}"},
            )
        latency = int((time.monotonic() - started) * 1000)
        ok = resp.status_code < 400
        return {"code": 0, "message": "ok",
                "data": {"ok": ok, "applicable": True, "latency_ms": latency,
                         "detail": "可达" if ok else f"HTTP {resp.status_code}"}}
    except Exception as e:
        return {"code": 0, "message": "ok",
                "data": {"ok": False, "applicable": True,
                         "latency_ms": int((time.monotonic() - started) * 1000),
                         "detail": f"连接失败: {type(e).__name__}"}}
