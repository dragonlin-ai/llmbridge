"""应用装配：/v1 与 /admin 双入口挂载、lifespan、/health。

依赖方向（后端技术设计说明书 §三）：api ─▶ router_engine ─▶ deciders/adapters；
本文件只做装配，不含业务逻辑。
"""
import asyncio
import logging
import re
import sys
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.admin import router as admin_router
from app.api.v1 import router as v1_router
from app.core.config import get_settings
from app.db.session import engine
from app.services import logbuffer
from app.services.quota_cache import cache as qcache

logging.basicConfig(
    level=logging.INFO,
    format='{"ts":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}',
)
logger = logging.getLogger("app.main")


def _mask_url(url: str) -> str:
    """脱敏连接串里的密码，便于安全地打进日志。"""
    return re.sub(r"://([^:@/]+):[^@]+@", r"://\1:***@", url)


async def _startup_selfcheck(settings) -> None:
    """启动自检：打印**实际生效**的数据库与事件循环，并真实探活一次。

    为什么要打印而不是信任配置：曾出现过「配了某判定器但实际跑的是另一个」这类
    配置值≠生效值的问题（前端还硬编码显示）。数据库同理——判别依据只能是运行时事实。

    为什么要在启动阶段就检查事件循环：Windows 默认的 ProactorEventLoop 会让 psycopg
    在**首次查询时**才抛 InterfaceError，表现为「服务起来了，但一登录就 500」。
    在这里提前打成 ERROR，故障从「运行时随机 500」变成「启动即显性」。
    """
    loop = asyncio.get_running_loop()
    loop_name = type(loop).__name__
    # 不要用类名做等值比较：Windows 上 asyncio.SelectorEventLoop 的实际运行时类型是
    # 子类 `_WindowsSelectorEventLoop`，拿 "SelectorEventLoop" 去比会把**正常情况误报成错误**
    # （实测踩过）。用 isinstance 判层次，类名只作兜底。
    loop_ok = isinstance(loop, asyncio.SelectorEventLoop) or "Selector" in loop_name
    logger.info("db dialect=%s url=%s", engine.dialect.name, _mask_url(settings.database_url))
    logger.info("event_loop=%s psycopg_compatible=%s allow_local_base_url=%s",
                loop_name, loop_ok, settings.allow_local_base_url)

    if engine.dialect.name == "postgresql" and sys.platform == "win32" and not loop_ok:
        logger.error(
            "Windows 下使用 PostgreSQL 必须跑 SelectorEventLoop（当前 %s），"
            "否则 psycopg 首次查询即失败。请带参数启动：--loop app.core.eventloop:selector_loop_factory",
            loop_name,
        )

    try:
        async with engine.connect() as conn:
            await conn.execute(text("select 1"))
        logger.info("db connectivity=ok")
    except Exception as e:  # 不中断启动，但必须显性可见（降级组件要留可观测痕迹）
        logger.error("db connectivity=FAILED %s: %s", type(e).__name__, str(e)[:200])


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    await _startup_selfcheck(settings)

    # 首次运行引导：建表 → 默认管理员 → 预置厂商目录（只铺接入商，模型池留空）。
    # 为什么放在启动路径而不是让人记得跑命令：交付态原先要跑
    # `llmbridge-seed` + `llmbridge-catalog` 两步，漏第二步打开控制台就是
    # 「一家厂商都没有」；而 catalog 依赖源码 scripts/ 目录，wheel 装完根本跑不了。
    # 三步都幂等、都不抛异常（失败只记 ERROR），不会阻塞启动。
    # AUTO_BOOTSTRAP=false 可整体关掉（生产不想让服务写库时用）。
    if settings.auto_bootstrap:
        from app.services.bootstrap import run_first_run

        result = await run_first_run()
        logger.info("bootstrap: schema_created=%s admin=%s eval_cases=%s providers=%s%s",
                    result["schema_created"], result["admin"], result["eval_cases"],
                    result["providers"],
                    f" counts={result.get('counts')}" if result.get("counts") else "")

    # 库级判定器配置（sys_config）：库 > .env > 默认。必须在 build_decider 之前加载，
    # 否则探活/看板仍按 .env 的旧值展示「配置值≠生效值」。表未迁移时不阻断启动。
    from app.services import sys_config as _syscfg
    from app.services.sys_config import refresh_decider_config

    try:
        await refresh_decider_config()
        logger.info("sys_config: decider overrides loaded keys=%s", sorted(_syscfg._db_keys))
    except Exception as e:
        logger.warning("sys_config load skipped（表未建或库不可用，回落 .env）: %s: %s",
                       type(e).__name__, str(e)[:200])
    # 全局共享 httpx 客户端（单例连接池，优化建议 B-02）
    app.state.http_client = httpx.AsyncClient(
        limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
    )
    # 决策器健康探测：不可达自动降级 warn（架构风险对策）
    from app.deciders import build_decider

    decider = build_decider()
    healthy = await decider.health_check()
    logger.info("decider=%s healthy=%s", decider.name, healthy)
    # 日志刷盘常驻任务
    writer = asyncio.create_task(logbuffer.log_writer_loop())
    yield
    writer.cancel()
    await app.state.http_client.aclose()
    await engine.dispose()
    logbuffer.flush_on_exit()


app = FastAPI(title="LLM 路由中转系统", version="1.0.0", lifespan=lifespan)

# CORS：仅控制台前端开发联调用；生产走同源部署，收紧 allow_origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["x-router-trace-id", "x-router-layer", "x-router-model",
                    "x-router-task-type", "x-router-confidence", "x-router-tools"],
)

# 双入口挂载（基线 3.11：对外/对内策略相反，永不合流）
app.include_router(v1_router)
app.include_router(admin_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
