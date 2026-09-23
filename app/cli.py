"""命令行入口：`llmbridge-serve` / `llmbridge-seed` / `llmbridge-catalog`。

为什么需要这三条命令
--------------------
1. **`uvicorn app.main:app` 在 Windows 上必然连不上 PostgreSQL**：
   uvicorn 的默认 loop 工厂返回 `ProactorEventLoop`，而 psycopg3 主动拒绝它
   （完整踩坑记录见 `app/core/eventloop.py`）。省略 `--loop app.core.eventloop:selector_loop_factory`
   的症状是「服务起来了、/health 也 200，但一访问数据库就 500」——极难排查。
   `llmbridge-serve` 把正确的事件循环固化进入口，任何平台一条命令即可起对。

2. **初始化不再是必须的手工步骤**：服务启动时会自动「建表 + 建默认管理员 + 写内置评测样本 +
   预置厂商目录」（见 `app/services/bootstrap.py`），所以 `llmbridge-serve` 一条命令就能开出一个
   可登录、有全部主流接入商的控制台。
   本文件的 `seed` / `catalog` 是**手工等价物**，适用场景：
   想先看预置报告再决定、想 `--dry-run` 试算、或生产环境用 `AUTO_BOOTSTRAP=false`
   关掉自动引导后由运维显式执行。

3. **`llmbridge-catalog` 曾经只能在源码 checkout 内运行** —— 逻辑放在 `scripts/`，
   而 `scripts/` 不进 wheel（`MANIFEST.in` 只管 sdist），`pip install .` 之后该命令
   会直接提示「找不到脚本」并退出 2。
   逻辑现已搬进包内 `app/data/catalog_seed.py`，wheel / 容器整包安装同样可用。
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from app.core.eventloop import selector_loop_factory

# uvicorn 用「导入字符串」而不是实例，这样多 worker 与 --reload 才能被子进程正确重建。
_APP = "app.main:app"
_LOOP = "app.core.eventloop:selector_loop_factory"


def serve(argv: list[str] | None = None) -> int:
    """启动网关。等价于带正确 `--loop` 的 uvicorn，但不会忘。"""
    parser = argparse.ArgumentParser(
        prog="llmbridge-serve", description="启动 LLM 路由中转网关（自动使用 psycopg3 兼容的事件循环）"
    )
    parser.add_argument("--host", default="127.0.0.1", help="监听地址（对外提供建议 0.0.0.0）")
    parser.add_argument("--port", type=int, default=8000, help="监听端口")
    parser.add_argument("--workers", type=int, default=1, help="worker 进程数，>1 时不可与 --reload 同用")
    parser.add_argument("--reload", action="store_true", help="开发用：代码变更自动重启")
    parser.add_argument("--log-level", default="info", help="uvicorn 日志级别")
    args = parser.parse_args(argv)

    if args.reload and args.workers > 1:
        parser.error("--reload 与 --workers>1 不能同时使用")

    import uvicorn

    uvicorn.run(
        _APP,
        host=args.host,
        port=args.port,
        workers=args.workers,
        reload=args.reload,
        log_level=args.log_level,
        loop=_LOOP,
    )
    return 0


def seed(argv: list[str] | None = None) -> int:
    """建表 + 默认管理员 + 预置厂商接入目录（幂等）。

    与启动自动引导同源（`app/services/bootstrap.py`），不会出现两套行为。
    """
    from app.seed import main as seed_main

    # loop_factory 传的是**函数本身**，不能加括号 —— 加了会得到一个 loop 实例，
    # 再被 asyncio 当可调用对象使用，直接 TypeError。
    asyncio.run(seed_main(argv), loop_factory=selector_loop_factory)
    return 0


def catalog(argv: list[str] | None = None) -> int:
    """预置内置厂商目录（13 家厂商的全部接入通道），幂等，支持 --dry-run。

    默认**只铺接入通道**：模型池初始为空，由使用者在「模型池」页按自己账号
    实际可用的 Model ID 手工添加。要连目录参考模型（含官方参考单价）一起灌入，
    显式加 `--with-models`。
    """
    from app.data.catalog_seed import seed_catalog
    from app.db.session import SessionLocal

    parser = argparse.ArgumentParser(
        prog="llmbridge-catalog", description="预置内置厂商目录（幂等，可重复执行）"
    )
    parser.add_argument("--with-models", action="store_true",
                        help="连目录参考模型一并预置（默认只铺接入通道）")
    parser.add_argument("--dry-run", action="store_true", help="只看会做什么，不写库")
    parser.add_argument("--overwrite", action="store_true",
                        help="覆盖已存在记录的说明/base_url 与模型参考价")
    parser.add_argument("--keep-names", action="store_true",
                        help="保留库里已有的通道名，不按目录规范化")
    parser.add_argument("--prune-orphans", action="store_true",
                        help="删除已不在目录中的通道行（三重条件同时满足才删）")
    parser.add_argument("--report", default="seed_provider_catalog_report.txt",
                        help="报告落盘路径")
    args = parser.parse_args(argv)

    async def _run() -> list[str]:
        async with SessionLocal() as session:
            lines = await seed_catalog(
                session,
                with_models=args.with_models,
                overwrite=args.overwrite,
                keep_names=args.keep_names,
                prune_orphans=args.prune_orphans,
            )
            if args.dry_run:
                await session.rollback()
                lines.append("（dry-run：已回滚，未写库）")
            else:
                await session.commit()
                lines.append("（已提交）")
        return lines

    lines = asyncio.run(_run(), loop_factory=selector_loop_factory)
    report = "\n".join(lines)
    # 报告同时落盘 —— 宿主环境（如 PowerShell）经常吞掉 stdout。
    Path(args.report).write_text(report, encoding="utf-8")
    print(report)
    return 0


_COMMANDS = {"serve": serve, "seed": seed, "catalog": catalog}


if __name__ == "__main__":
    # 兜底入口：console script 不在 PATH 上（未装包 / 只解压了源码）时可用
    #   python -m app.cli serve --port 8000
    # 注意不能直接 `python app/cli.py` —— 那样 sys.path[0] 是 app/ 而非仓库根，
    # 连 `import app.core.eventloop` 都会失败。
    if len(sys.argv) < 2 or sys.argv[1] not in _COMMANDS:
        print(f"用法：python -m app.cli {{{'|'.join(_COMMANDS)}}} [选项]", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(_COMMANDS[sys.argv.pop(1)]())
