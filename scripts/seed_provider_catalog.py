"""CLI 薄壳：把内置厂商目录预置进库（逻辑在 `app/data/catalog_seed.py`）。

本脚本只做**参数解析 + 报告落盘**；真正的预置逻辑已搬进包内，因此
`llmbridge-catalog` 与启动自动引导走的是**同一份实现**，不会出现两套行为。

用法：
    python scripts/seed_provider_catalog.py                    # 只铺接入通道（默认）
    python scripts/seed_provider_catalog.py --with-models       # 连目录参考模型（含参考单价）一起灌
    python scripts/seed_provider_catalog.py --dry-run           # 只看会做什么，不写库
    python scripts/seed_provider_catalog.py --overwrite         # 覆盖已存在记录的说明/base_url 与模型参考价
    python scripts/seed_provider_catalog.py --prune-orphans     # 清理目录残留行（三重条件同时满足才删）

详见模块 docstring：`app/data/catalog_seed.py`。
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # 直接运行脚本时 sys.path[0] 是 scripts/，需补项目根才能 import app

from app.core.eventloop import selector_loop_factory  # noqa: E402
from app.data.catalog_seed import seed_catalog  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402


def _build_parser(prog: str = "seed_provider_catalog") -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog=prog)
    ap.add_argument("--with-models", action="store_true",
                    help="连目录参考模型一并预置（默认只铺接入通道，模型池留空待手工添加）")
    ap.add_argument("--dry-run", action="store_true", help="只打印将要执行的操作，不提交")
    ap.add_argument("--overwrite", action="store_true",
                    help="覆盖已存在通道的 remark/base_url，以及已存在模型的参考价与能力标签")
    ap.add_argument("--keep-names", action="store_true",
                    help="保留库里已有的通道名，不按目录规范化（适合手工改过名的场景）")
    ap.add_argument("--prune-orphans", action="store_true",
                    help="清理目录残留行：仍用占位密钥、且没有挂任何模型、且 base_url 不在当前目录里的通道"
                         "（目录改了端点后留下的旧行）。三重条件同时满足才删，绝不碰真实数据")
    ap.add_argument("--report", default="_catalog_report.txt", help="报告落盘路径")
    return ap


async def run(args: argparse.Namespace) -> list[str]:
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


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    lines = asyncio.run(run(args), loop_factory=selector_loop_factory)
    report = "\n".join(lines)
    # 结果同时打印并落盘 —— 宿主环境经常吞掉 PowerShell 的 stdout。
    Path(args.report).write_text(report, encoding="utf-8")
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
