"""API 依赖：鉴权、DB 会话引用、公共工具。

SSRF 校验在此实现（安全方案 §7），供 providers 接口复用。
"""
import ipaddress
import socket
from urllib.parse import urlparse

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select

from app.core.security import decode_access_token
from app.db.session import get_db


async def current_user(request: Request) -> dict:
    """控制台 JWT 鉴权。返回 {sub, role}。"""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail={"code": 1001, "message": "未认证"})
    payload = decode_access_token(auth[7:])
    if payload is None:
        raise HTTPException(status_code=401, detail={"code": 1001, "message": "凭证无效或已过期"})
    return {"sub": payload.get("sub"), "role": payload.get("role")}


async def require_admin(user: dict = Depends(current_user)) -> dict:
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail={"code": 1002, "message": "只读账号无写权限"})
    return user


_PRIVATE_NETS = [
    ipaddress.ip_network(n)
    for n in (
        "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
        "127.0.0.0/8", "169.254.0.0/16", "::1/128", "fc00::/7",
    )
]


def validate_base_url(url: str, *, allow_local: bool = False) -> str:
    """SSRF 防护：scheme 白名单 + 私网段拒绝（安全方案 §7）。"""
    parsed = urlparse(url)
    scheme_ok = parsed.scheme == "https" or (allow_local and parsed.scheme == "http")
    if not scheme_ok:
        raise HTTPException(status_code=422, detail={"code": 1003, "message": "base_url 仅允许 https（开发环境允许 http://localhost）"})
    host = parsed.hostname or ""
    if allow_local and (host in ("localhost", "127.0.0.1") or host.endswith(".local")):
        return url
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        raise HTTPException(status_code=422, detail={"code": 1003, "message": "base_url 域名无法解析"})
    for info in infos:
        addr = ipaddress.ip_address(info[4][0])
        for net in _PRIVATE_NETS:
            if addr in net:
                raise HTTPException(status_code=422, detail={"code": 1003, "message": "base_url 禁止指向内网地址"})
    return url


async def load_routable_models(session) -> dict[int, "Model"]:
    """加载**可路由**的模型：模型启用 且 其厂商已接入（启用 + 密钥可用）。

    注意这里比「模型启用」严一档。候选池是路由的输入，凡是能进池的模型都必须是
    「现在真的调得通」的；否则选中即失败，降级链会把失败转嫁给下一个候选，
    最终对外表现为随机 502（缺陷 D-25）。

    过滤放在入口而不是调用处，是为了让所有使用方（/v1 与试跑台）自动一致 ——
    「同一份决策内核」的前提是「同一份候选池」。
    """
    from app.data.provider_catalog import ROUTABLE_ACCESS_KINDS, SUPPORTED_PROTOCOLS
    from app.db.tables import Model, Provider
    from app.services.provider_access import has_usable_key

    rows = (await session.execute(
        select(Model, Provider)
        .join(Provider, Model.provider_id == Provider.id)
        .where(
            Model.enabled.is_(True),
            Provider.enabled.is_(True),
            # 通道能力过滤必须在 SQL 层与 is_* 判定保持一致，否则
            # 「试跑台能选、线上不能调」这类偏差会悄悄出现（同一份候选池是前提）。
            # 目前会拦下两类通道：编程订阅套餐（coding_plan）与尚无适配器的协议。
            Provider.access_kind.in_(tuple(ROUTABLE_ACCESS_KINDS)),
            Provider.protocol.in_(tuple(SUPPORTED_PROTOCOLS)),
        )
    )).all()
    return {m.id: m for m, p in rows if has_usable_key(p.api_key_encrypted)}
