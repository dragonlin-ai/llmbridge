"""事件循环工厂：为 psycopg3 在 Windows 上提供兼容的 SelectorEventLoop。

背景（本项目踩过的坑，改启动方式前务必读完）：
1. psycopg3 的 asyncio 实现**主动拒绝** ProactorEventLoop，直接抛
   `InterfaceError: Psycopg cannot use the 'ProactorEventLoop' to run in async mode`。
2. uvicorn(>=0.36) 的 `uvicorn/loops/asyncio.py::asyncio_loop_factory()` 在
   「Windows + 非子进程」时返回的正是 `asyncio.ProactorEventLoop`
   → 于是 `uvicorn app.main:app`（不带 --loop、不带 --reload）必然连不上 PostgreSQL。
3. 设 `asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())` **无效**：
   `uvicorn/server.py::Server.run()` 是 `asyncio_run(serve(), loop_factory=...)`，
   loop_factory 优先于 policy。
4. uvicorn 的 `Config.get_loop_factory()` 对不在内置表（auto/asyncio/uvloop）里的 `--loop` 值
   会 `import_from_string()` 并**直接当作工厂函数返回**。故官方支持的用法是：

       uvicorn app.main:app --loop app.core.eventloop:selector_loop_factory

   ⚠️ 该参数不可省略：省略即 Proactor，一访问数据库就 500。
5. Linux 生产环境不受影响（默认即 Selector/uvloop），本工厂在非 Windows 上退回默认实现。
"""
from __future__ import annotations

import asyncio
import selectors
import sys


def selector_loop_factory() -> asyncio.AbstractEventLoop:
    """返回一个 psycopg3 可用的事件循环。

    Windows 默认的 ProactorEventLoop 不支持 add_reader/add_writer（psycopg 的异步等待依赖它），
    必须显式用 SelectSelector 构造 SelectorEventLoop。
    """
    if sys.platform == "win32":
        return asyncio.SelectorEventLoop(selectors.SelectSelector())
    return asyncio.new_event_loop()
