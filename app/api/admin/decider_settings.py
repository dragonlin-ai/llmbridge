"""判定器设置（Jev 5 项配置入界面）：回显 / 保存 / 连通性测试。

契约：
- GET  回显生效值（密钥掩码）+ 每项来源（db/env）+ 实际生效判定器；
- PUT  partial 更新，校验后落库并**即时生效**（清 get_settings 缓存，免重启）；
- POST /test 用真实 JevDecider.health_check 探活当前生效配置（非 mock 自嗨）。

校验口径与 providers 对齐：SSRF 走 validate_base_url，枚举/范围在此层拦，
服务层只管存取（app/services/sys_config.py）。
"""
import time

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import current_user, require_admin, validate_base_url
from app.core.config import get_settings
from app.schemas import DeciderSettingsIn
from app.services import sys_config

router = APIRouter(prefix="/admin/decider", tags=["admin-decider"])


@router.get("/settings")
async def get_decider_settings(_u: dict = Depends(current_user)):
    return {"code": 0, "message": "ok", "data": sys_config.get_decider_display()}


def _clean(body: DeciderSettingsIn) -> dict:
    """校验并产出待保存键值；None=不修改、掩码值=不修改，均不入 clean。"""
    clean: dict = {}
    if body.judge_provider is not None:
        if body.judge_provider not in ("mock", "jev"):
            raise HTTPException(status_code=422, detail={
                "code": 1003, "message": "judge_provider 仅允许 mock / jev"})
        clean["judge_provider"] = body.judge_provider
    if body.jev_api_key is not None:
        v = body.jev_api_key.strip()
        if "****" in v:
            pass  # 前端把回显掩码原样提交 = 用户没改密钥，忽略
        elif v == "":
            clean["jev_api_key"] = ""  # 显式清空 → 删行回落 .env
        elif len(v) < 8:
            raise HTTPException(status_code=422, detail={
                "code": 1003, "message": "JEV_API_KEY 至少 8 字符"})
        else:
            clean["jev_api_key"] = v
    if body.jev_base_url is not None:
        u = body.jev_base_url.strip()
        # SSRF：https 白名单 + 私网拒绝（安全方案 §7），与厂商通道同一把尺
        validate_base_url(u, allow_local=get_settings().allow_local_base_url)
        clean["jev_base_url"] = u
    if body.decider_timeout_ms is not None:
        clean["decider_timeout_ms"] = body.decider_timeout_ms
    if body.route_confidence_threshold_t2 is not None:
        clean["route_confidence_threshold_t2"] = body.route_confidence_threshold_t2
    return clean


@router.put("/settings")
async def put_decider_settings(body: DeciderSettingsIn, _u: dict = Depends(require_admin)):
    clean = _clean(body)
    if clean:
        await sys_config.save_decider_values(clean)  # 落库 + 清缓存，即时生效
    return {"code": 0, "message": "ok", "data": sys_config.get_decider_display()}


@router.post("/settings/test")
async def test_decider_settings(_u: dict = Depends(require_admin)):
    """连通性测试：直接复用 JevDecider.health_check 真实探活当前生效配置。

    前端流程 = 「保存」→「测试」（测试不接受未保存值，避免测的不是生效的）。
    """
    from app.deciders.jev_decider import JevDecider

    if not get_settings().jev_api_key:
        return {"code": 0, "message": "ok", "data": {
            "healthy": False, "latency_ms": None,
            "reason": "未配置 JEV_API_KEY（库与 .env 均为空）"}}
    decider = JevDecider()
    started = time.monotonic()
    healthy = await decider.health_check()
    return {"code": 0, "message": "ok", "data": {
        "healthy": healthy,
        "latency_ms": int((time.monotonic() - started) * 1000),
        "reason": None if healthy else (decider.last_error or "探活失败，详见后端日志")}}
