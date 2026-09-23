"""幂等迁移：provider 表新增 remark 列（接入备注）。

为什么需要手写迁移：项目虽然建了 alembic/ 目录，但没有可用的迁移版本，
表结构一直靠 `Base.metadata.create_all` 建立——而 create_all **只建缺失的表，不会给已存在的表加列**。
所以每次结构变更都要配一个幂等脚本，重复执行不报错。

用法：
    python scripts/migrate_add_provider_remark.py            # 执行
    python scripts/migrate_add_provider_remark.py --dry-run  # 只看当前状态
"""
import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # 直接运行脚本时 sys.path[0] 是 scripts/，需补项目根才能 import app

from sqlalchemy import inspect, text  # noqa: E402

from app.core.eventloop import selector_loop_factory  # noqa: E402
from app.db.session import engine  # noqa: E402

TABLE = "provider"
COLUMN = "remark"
DDL = f"ALTER TABLE {TABLE} ADD COLUMN {COLUMN} VARCHAR(255)"


async def _columns(conn) -> list[str]:
    return await conn.run_sync(lambda sc: [c["name"] for c in inspect(sc).get_columns(TABLE)])


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只检查，不修改")
    args = ap.parse_args()

    async with engine.begin() as conn:
        cols = await _columns(conn)
        has = COLUMN in cols
        print(f"dialect={conn.dialect.name} table={TABLE} column_exists={has}")
        print(f"existing_columns={cols}")
        if has:
            print("skip: 列已存在，无需迁移")
            return
        if args.dry_run:
            print(f"dry-run: 将执行 {DDL}")
            return
        await conn.execute(text(DDL))
        cols_after = await _columns(conn)
        print(f"done: {DDL}")
        print(f"columns_after={cols_after}")
        print(f"verify={COLUMN in cols_after}")


if __name__ == "__main__":
    asyncio.run(main(), loop_factory=selector_loop_factory)
