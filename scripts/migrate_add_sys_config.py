"""幂等迁移：新建 `sys_config` 表（判定器 5 项配置入界面的存储层）。

表结构由 ORM 定义（app/db/tables/__init__.py: SysConfig），本脚本只负责
在既有库上把缺的表补出来 —— `Base.metadata.create_all` 本身幂等（缺则建、有则跳过），
这里包一层是为了统一给 dry-run 输出与列校验，与 scripts/migrate_add_api_key.py 口径一致。

用法：
    python scripts/migrate_add_sys_config.py --dry-run
    python scripts/migrate_add_sys_config.py
"""
import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import inspect, text  # noqa: E402

from app.core.eventloop import selector_loop_factory  # noqa: E402
from app.db.session import engine  # noqa: E402
from app.db.tables import Base, SysConfig  # noqa: E402

TABLE = "sys_config"
EXPECTED_COLUMNS = ["key", "value", "encrypted", "created_at", "updated_at"]


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只检查，不建表")
    args = ap.parse_args()

    async with engine.begin() as conn:
        dialect = conn.dialect.name
        print(f"dialect={dialect} table={TABLE}")

        exists = await conn.run_sync(
            lambda sc: TABLE in inspect(sc).get_table_names()
        )
        if exists:
            print(f"skip: 表 {TABLE} 已存在")
            cols = await conn.run_sync(
                lambda sc: [c["name"] for c in inspect(sc).get_columns(TABLE)]
            )
            print(f"columns={cols}")
            missing = [c for c in EXPECTED_COLUMNS if c not in cols]
            if missing:
                raise SystemExit(f"FAIL: 表存在但缺列 {missing}（需补列迁移，本脚本不处理）")
            print(f"verify_columns: OK（{len(EXPECTED_COLUMNS)} 列齐备）")
            return

        if args.dry_run:
            print(f"dry-run: 将创建表 {TABLE}，列={EXPECTED_COLUMNS}")
            return

        await conn.run_sync(lambda sc: Base.metadata.create_all(
            sc, tables=[SysConfig.__table__]
        ))
        print(f"done: 表 {TABLE} 已创建")

    # 建表后独立校验（新开连接，确认对其他会话也可见）
    async with engine.connect() as conn:
        cols = await conn.run_sync(
            lambda sc: [c["name"] for c in inspect(sc).get_columns(TABLE)]
        )
        missing = [c for c in EXPECTED_COLUMNS if c not in cols]
        print(f"columns_after={cols}")
        if missing:
            raise SystemExit(f"FAIL: 建表后仍缺列 {missing}")
        n = (await conn.execute(text(f"SELECT count(*) FROM {TABLE}"))).scalar_one()
        print(f"verify: 表存在、列齐备、当前行数={n}")


if __name__ == "__main__":
    asyncio.run(main(), loop_factory=selector_loop_factory)
