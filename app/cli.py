"""命令行入口：`llmbridge-serve` / `llmbridge-seed` / `llmbridge-catalog`。

为什么需要这三条命令
--------------------
1. **`uvicorn app.main:app` 在 Windows 上必然连不上 PostgreSQL**：
   uvicorn 的默认 loop 工厂返回 `ProactorEventLoop`，而 psycopg3 主动拒绝它
   （完整踩坑记录见 `app/core/eventloop.py`）。省略 `--loop app.core.eventloop:selector_loop_factory`
   的症状是「服务起来了、/health 也 200，但一访问数据库就 500」——极难排查。
   `llmbridge-serve` 把正确的事件循环固化进入口，任何平台一条命令即可起对。

2. **初始化顺序容易搞错**：先建表/种子（`llmbridge-seed`），再灌厂商目录
   （`llmbridge-catalog`）。少了第二步会出现「控制台里一家厂商都没有、不知道从哪接入」。
"""
from __future__ import annotations

import argparse
import asyncio
import os
import runpy
import sys
from pathlib import Path

from app.core.eventloop import selector_loop_factory

# uvicorn 用「导入字符串」而不是实例，这样多 worker 与 --reload 才能被子进程正确重建。
_APP = "app.main:app"
_LOOP = "app.core.eventloop:selector_loop_factory"


def _repo_root() -> Path | None:
    """定位源码根目录（含 `scripts/seed_provider_catalog.py` 的那一层）。

    三种安装方式下 `app/cli.py` 的位置不同，所以按可靠性依次尝试：
    1. `LLMBRIDGE_REPO_ROOT` —— 容器/自定义布局时的显式出口；
    2. `app/cli.py` 的上两级 —— 源码运行或 `pip install -e .` 的情况；
    3. 当前工作目录 —— `pip install .` 装进 site-packages 后，从仓库根执行命令的兜底。

    找不到返回 None，由调用方给出可执行提示，而不是抛一个看不懂的 FileNotFoundError。
    """
    candidates: list[Path] = []
    if env := os.environ.get("LLMBRIDGE_REPO_ROOT"):
        candidates.append(Path(env))
    candidates.append(Path(__file__).resolve().parent.parent)
    candidates.append(Path.cwd())
    for candidate in candidates:
        if (candidate / "scripts" / "seed_provider_catalog.py").is_file():
            return candidate
    return None


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
    """建表 + 写入最小可跑集（厂商/模型/规则/管理员/评测集）。已有数据则跳过。"""
    parser = argparse.ArgumentParser(
        prog="llmbridge-seed", description="建表并写入最小种子数据（幂等：已有数据则跳过）"
    )
    parser.parse_args(argv)

    from app.seed import main as seed_main

    # loop_factory 传的是**函数本身**，不能加括号 —— 加了会得到一个 loop 实例，
    # 再被 asyncio 当可调用对象使用，直接 TypeError。
    asyncio.run(seed_main(), loop_factory=selector_loop_factory)
    return 0


def catalog(argv: list[str] | None = None) -> int:
    """预置内置厂商目录（13 家厂商的全部接入通道），幂等，支持 --dry-run。

    目录脚本位于源码树的 `scripts/`，因此**必须在源码 checkout 内运行**；
    wheel 安装后该目录不存在，会给出明确提示而不是栈回溯。
    """
    parser = argparse.ArgumentParser(
        prog="llmbridge-catalog", description="预置内置厂商目录（幂等，可重复执行）"
    )
    parser.add_argument("--dry-run", action="store_true", help="只看会做什么，不写库")
    parser.add_argument("--overwrite", action="store_true", help="覆盖已存在记录的说明/base_url 与模型参考价")
    parser.add_argument("--prune-orphans", action="store_true", help="删除已不在目录中的通道行")
    parser.add_argument("--report", default="seed_provider_catalog_report.txt", help="报告落盘路径")
    args, passthrough = parser.parse_known_args(argv)

    root = _repo_root()
    if root is None:
        print(
            "找不到 scripts/seed_provider_catalog.py。\n"
            "该命令需要源码 checkout（git clone 后的完整目录），"
            "当前看起来是以 wheel 方式安装的。\n"
            "请改用源码安装：pip install -e .  或直接运行 "
            "python scripts/seed_provider_catalog.py",
            file=sys.stderr,
        )
        return 2

    script = root / "scripts" / "seed_provider_catalog.py"
    script_argv = [str(script)]
    if args.dry_run:
        script_argv.append("--dry-run")
    if args.overwrite:
        script_argv.append("--overwrite")
    if args.prune_orphans:
        script_argv.append("--prune-orphans")
    script_argv += ["--report", args.report, *passthrough]

    saved_argv = sys.argv
    sys.argv = script_argv
    try:
        # run_path 会执行脚本的 `if __name__ == "__main__":` 分支，
        # 其中的 asyncio.run(..., loop_factory=...) 已按项目约定写好，此处不重复实现。
        runpy.run_path(str(script), run_name="__main__")
    finally:
        sys.argv = saved_argv
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
