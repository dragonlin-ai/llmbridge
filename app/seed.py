"""建表 + 首次运行引导（等价于服务启动时自动做的那几件事）。

用法：`python -m app.seed` 或 `llmbridge-seed`

做四件事，全部幂等：
1. 建表（`create_all`，已存在则空操作）
2. 无管理员时创建默认管理员 `admin` / `admin123`（**登录后请立即改**）
3. 无评测样本时写入 4 条内置样本（模型真值留空）
4. 预置厂商接入目录 —— **只铺接入商**；模型池留空，由使用者在「模型池」页手工添加

实现上直接复用 `app/services/bootstrap.py`，与服务启动自动引导**同源** ——
同一个全新安装不该因为「跑没跑这条命令」而长得不一样。

为什么不在这里塞「示例厂商 / 示例模型 / 示例规则」
------------------------------------------------
早期版本会写 2 家开发用厂商（DeepSeek、OpenAI）、4 个示例模型、2 条示例路由规则。
现在这些已是**脏数据**：

- 与内置厂商目录冲突 —— 目录里本来就有 DeepSeek 的「按量 API」通道，
  再写一行裸名「DeepSeek」会让同一家厂商出现两条通道；
- 示例模型名（`deepseek-chat` / `gpt-4o` / `gpt-4o-mini`）已不在当前目录里，
  单价也是旧口径，交付态看到会以为是目录配错了；
- `RouteRule.target_model_id` 是**非空外键**，模型池留空时示例规则根本写不进去 ——
  所以「不预置模型」与「不预置示例规则」是同一件事，不是两个取舍。

需要一份**可路由**的演示数据时，用 `llmbridge-catalog --with-models`
把目录里的参考模型（含官方参考单价）显式灌进去。
"""
from __future__ import annotations

import argparse
import asyncio

from app.core.eventloop import selector_loop_factory
from app.services.bootstrap import (
    DEFAULT_ADMIN_PASSWORD,
    DEFAULT_ADMIN_USERNAME,
    run_first_run,
)


def _describe(summary: dict) -> list[str]:
    lines: list[str] = []
    if summary.get("schema_created"):
        lines.append("seed: 已建表")
    else:
        lines.append("seed: 表已存在，跳过建表")

    admin = summary.get("admin")
    if admin == "created":
        lines.append(f"seed: 已创建默认管理员 {DEFAULT_ADMIN_USERNAME} / "
                     f"{DEFAULT_ADMIN_PASSWORD}（首次登录后请立即修改）")
    elif admin == "race":
        lines.append("seed: 管理员已由其他进程创建")
    else:
        lines.append("seed: 管理员已存在，跳过")

    cases = summary.get("eval_cases")
    lines.append("seed: 已写入内置评测样本" if cases == "created"
                 else "seed: 评测样本已存在，跳过")

    providers = summary.get("providers")
    if providers == "seeded":
        counts = summary.get("counts") or {}
        lines.append(f"seed: 已预置厂商接入目录（通道 {counts.get('providers')} 条 / "
                     f"厂商 {counts.get('vendors')} 家）—— 模型池留空，请在「模型池」页手工添加")
    elif providers == "legacy-skipped":
        lines.append("seed: 检测到既有安装（库中已有接入通道）且无预置标记 —— "
                     "判定为老库，一条都没动。如需同步目录请显式执行 llmbridge-catalog")
    elif providers == "race":
        lines.append("seed: 厂商目录预置与其他进程并发，已跳过")
    else:
        lines.append("seed: 厂商接入目录已是最新版本，跳过（--force 可强制重新预置）")

    for err in summary.get("errors") or []:
        lines.append(f"seed: [ERROR] {err}")
    return lines


async def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="llmbridge-seed",
        description="建表 + 默认管理员 + 内置评测样本 + 预置厂商接入目录（幂等）",
    )
    parser.add_argument("--force", action="store_true",
                        help="即使目录版本未变也重新预置接入通道")
    args = parser.parse_args(argv)

    summary = await run_first_run(force=args.force)
    print("\n".join(_describe(summary)))
    if report := summary.get("report"):
        print()
        print("\n".join(report))


if __name__ == "__main__":
    asyncio.run(main(), loop_factory=selector_loop_factory)
