"""请求日志异步批量写：内存队列 + 定时 flush。

设计依据（后端技术设计说明书 §四）：request_log 是增长最快的表，
逐条同步 INSERT 在 SQLite 阶段就会卡路由主链路——批量写是 SQLite 能撑住的前提。
进程退出时 atexit 冲洗（代码审查 C-09）。
"""
import asyncio
import atexit
import json
import logging
import threading

from app.core.config import get_settings

logger = logging.getLogger("services.logbuffer")

_queue: list[dict] = []
_lock = threading.Lock()
_task: asyncio.Task | None = None


def enqueue(entry: dict) -> None:
    settings = get_settings()
    entry["input_text"] = (entry.get("input_text") or "")[:2000]  # 落库截断
    with _lock:
        _queue.append(entry)
        if len(_queue) >= settings.log_batch_size:
            _spawn_flush()


def _spawn_flush() -> None:
    global _task
    try:
        loop = asyncio.get_running_loop()
        if _task is None or _task.done():
            _task = loop.create_task(_flush())
    except RuntimeError:
        _flush_sync()


async def _flush() -> None:
    settings = get_settings()
    await asyncio.sleep(settings.log_flush_seconds)
    await _write()


def _flush_sync() -> None:
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(_write())
        else:
            loop.run_until_complete(_write())
    except RuntimeError:
        pass


async def _write() -> None:
    global _queue
    with _lock:
        batch, _queue = _queue, []
    if not batch:
        return
    try:
        from app.db.session import SessionLocal
        from app.db.tables import RequestLog

        async with SessionLocal() as session:
            for e in batch:
                session.add(RequestLog(**e))
            await session.commit()
    except Exception:
        logger.exception("request_log flush failed, %d entries dropped", len(batch))


async def log_writer_loop() -> None:
    """lifespan 启动的常驻刷盘循环。"""
    settings = get_settings()
    while True:
        await asyncio.sleep(settings.log_flush_seconds)
        await _write()


def flush_on_exit() -> None:
    """atexit 钩子：尽力冲洗剩余条目。"""
    with _lock:
        pending = len(_queue)
    if pending:
        logger.warning("exit with %d pending log entries, best-effort flush", pending)
        _flush_sync()
    dump_path = "request_log_dropped.json"
    with _lock:
        if _queue:
            with open(dump_path, "w", encoding="utf-8") as f:
                json.dump(_queue, f, ensure_ascii=False)


atexit.register(flush_on_exit)
