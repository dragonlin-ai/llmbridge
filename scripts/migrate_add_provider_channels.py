"""幂等迁移：provider 表支持「一厂商多接入通道」的全部列与约束。

背景
----
同一家厂商往往同时提供多种互不相通的接入方式——密钥、端点、计费、限流各不相同，
**密钥互不通用**（拿 A 的 Key 打 B 的端点会 401）：

  | 形态 | 含义 | 密钥 | 计费 |
  |---|---|---|---|
  | api          | 按量 API        | 开放平台通用 Key | 按 token 后付费 |
  | package      | 预付费资源包     | **与 api 同一个 Key** | 先充值后抵扣 |
  | batch        | 批处理           | **与 api 同一个 Key** | 按批优惠价 |
  | coding_plan  | 编程订阅套餐     | 订阅专属 Key（前缀各异） | 包月积分/次数 |
  | token_plan   | 通用 Token 订阅  | 订阅专属 Key | 包月 Token/Credits |

因此 provider 表的一行不再代表「一家厂商」，而是「一条接入通道」；
同一厂商的多条通道靠 `vendor` 聚合，控制台按厂商分组展示。

新增列
------
  vendor       VARCHAR(64)  NULL     厂商标识（分组键），如 moonshot
  access_kind  VARCHAR(32)  NOT NULL DEFAULT 'api'      接入形态
  protocol     VARCHAR(32)  NOT NULL DEFAULT 'openai'   上游协议
  terms_note   TEXT         NULL     厂商官方条款警示（订阅类通道用；remark 只有 255，装不下原文）

约束
----
  ck_provider_access_kind : access_kind IN ('api','package','token_plan','coding_plan','batch')
  ck_provider_protocol    : protocol    IN ('openai','anthropic')

⚠️ 约束的**表达式**会演进，只按约束名判断存在性会静默跳过更新
--------------------------------------------------------------
`ck_provider_access_kind` 在上一版只允许 4 个取值。加了 `token_plan` 之后，
约束名没变、表达式变了。若仍按「名字在不在」判断，就会打印 skip 然后放行——
库里留着一个拒绝写入 `token_plan` 的旧约束，表现为**预置时报 CheckViolation**，
而脚本自己说「已经是最新」。所以这里比对的是**表达式里的字面量集合**，
发现缺字面量就 DROP + ADD 重建。

用法：
    python scripts/migrate_add_provider_channels.py --dry-run
    python scripts/migrate_add_provider_channels.py
"""
import argparse
import asyncio
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # 直接运行脚本时 sys.path[0] 是 scripts/，需补项目根才能 import app

from sqlalchemy import inspect, text  # noqa: E402

from app.core.eventloop import selector_loop_factory  # noqa: E402
from app.db.session import engine  # noqa: E402

TABLE = "provider"

NEW_COLUMNS: list[tuple[str, str]] = [
    ("vendor", "VARCHAR(64)"),
    ("access_kind", "VARCHAR(32) NOT NULL DEFAULT 'api'"),
    ("protocol", "VARCHAR(32) NOT NULL DEFAULT 'openai'"),
    ("terms_note", "TEXT"),
]

CHECKS: list[tuple[str, str]] = [
    ("ck_provider_access_kind",
     "access_kind IN ('api','package','token_plan','coding_plan','batch')"),
    ("ck_provider_protocol", "protocol IN ('openai','anthropic')"),
]

INDEX = ("ix_provider_vendor", f"CREATE INDEX ix_provider_vendor ON {TABLE} (vendor)")


def _literals(expr: str) -> set[str]:
    """取出 CHECK 表达式里的字符串字面量，用于判断约束定义是否已过时。"""
    return set(re.findall(r"'([^']*)'", expr))


async def _columns(conn) -> list[str]:
    return await conn.run_sync(lambda sc: [c["name"] for c in inspect(sc).get_columns(TABLE)])


async def _indexes(conn) -> list[str]:
    return await conn.run_sync(lambda sc: [i["name"] for i in inspect(sc).get_indexes(TABLE)])


async def _checks(conn, dialect: str) -> dict[str, str]:
    """约束名 -> 定义文本。"""
    if dialect == "postgresql":
        rows = (await conn.execute(text(
            "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid = 'provider'::regclass AND contype = 'c'"
        ))).all()
        return {r[0]: r[1] for r in rows}
    items = await conn.run_sync(
        lambda sc: inspect(sc).get_check_constraints(TABLE) or []
    )
    return {(c.get("name") or ""): (c.get("sqltext") or "") for c in items}


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只检查，不修改")
    ap.add_argument("--no-rebuild-checks", action="store_true",
                    help="不重建已存在的 CHECK 约束（仅用于排查）")
    args = ap.parse_args()

    async with engine.begin() as conn:
        dialect = conn.dialect.name
        print(f"dialect={dialect} table={TABLE}")

        cols = await _columns(conn)
        print(f"existing_columns={cols}")

        pending = [(n, t) for n, t in NEW_COLUMNS if n not in cols]
        if not pending:
            print(f"skip: {len(NEW_COLUMNS)} 个列均已存在")
        for name, typ in pending:
            ddl = f"ALTER TABLE {TABLE} ADD COLUMN {name} {typ}"
            if args.dry_run:
                print(f"dry-run: 将执行 {ddl}")
                continue
            await conn.execute(text(ddl))
            print(f"done: {ddl}")
        if args.dry_run and pending:
            print("dry-run: 约束与索引一并跳过，未做任何修改")
            return

        cols_after = await _columns(conn)

        # 约束：SQLite 不支持 ALTER TABLE ADD CONSTRAINT（SQLite 下建表时由 ORM 携带）
        if dialect == "sqlite":
            print("skip: SQLite 不支持 ADD CONSTRAINT（新建表时由 ORM 定义携带）")
        else:
            defs = await _checks(conn, dialect)
            for cname, expr in CHECKS:
                existing = defs.get(cname)
                want = _literals(expr)
                if existing is None:
                    await conn.execute(text(
                        f"ALTER TABLE {TABLE} ADD CONSTRAINT {cname} CHECK ({expr})"))
                    print(f"done: 约束 {cname}")
                elif want.issubset(_literals(existing)):
                    print(f"skip: 约束 {cname} 已存在且字面量齐备 {sorted(want)}")
                elif args.no_rebuild_checks:
                    print(f"warn: 约束 {cname} 定义过时，但 --no-rebuild-checks 指示跳过")
                else:
                    # 名字在、表达式旧 —— 正是最容易被误判为「已迁移」的情形
                    missing = sorted(want - _literals(existing))
                    await conn.execute(text(
                        f"ALTER TABLE {TABLE} DROP CONSTRAINT {cname}"))
                    await conn.execute(text(
                        f"ALTER TABLE {TABLE} ADD CONSTRAINT {cname} CHECK ({expr})"))
                    print(f"done: 约束 {cname} 已重建（缺失字面量 {missing}）")

        idx = await _indexes(conn)
        if INDEX[0] in idx:
            print(f"skip: 索引 {INDEX[0]} 已存在")
        else:
            await conn.execute(text(INDEX[1]))
            print(f"done: {INDEX[1]}")

        print(f"columns_after={cols_after}")
        print(f"verify_columns={[n for n, _ in NEW_COLUMNS]}")
        final_defs = await _checks(conn, dialect)
        for cname, expr in CHECKS:
            got = final_defs.get(cname, "<缺失>")
            ok = _literals(expr).issubset(_literals(got))
            print(f"verify_check {cname}: {'OK' if ok else 'MISMATCH'} :: {got}")


if __name__ == "__main__":
    asyncio.run(main(), loop_factory=selector_loop_factory)
