"""SQLite → PostgreSQL 一次性数据迁移（8 表全量）。

用法：
    python scripts/migrate_sqlite_to_pg.py            # 建表(已存在则跳过) + 灌数据
    python scripts/migrate_sqlite_to_pg.py --reset    # 先 drop 全部表再重建（会清空目标库！）
    python scripts/migrate_sqlite_to_pg.py --dry-run  # 只打印行数对比，不写目标库

设计要点：
- 表顺序严格按外键依赖：被引用行必须先插入，否则 PG 外键立即报错（SQLite 靠 PRAGMA 才管）。
- 逐表 TRUNCATE 后插入，脚本可重复执行（幂等）。
- 迁移后重置自增序列（setval），否则新插入会撞主键——SQLite 的 autoincrement 语义与 PG 序列不同。
- 结束时逐表校验行数，并把对比结果落到 _migrate_report.txt（PowerShell 常吞 stdout）。
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.core.config import get_settings  # noqa: E402

# 严格按外键依赖排序：provider → model → (依赖 model 的几张表)
TABLES = [
    "provider",
    "admin_user",
    "prompt_template",
    "model",
    "route_rule",
    "decision_sample",
    "request_log",
    "eval_case",
]


def _convert(value, data_type: str | None):
    """把 SQLite 取出的值转成 PG 列期望的 Python 类型。

    SQLite 没有原生 BOOLEAN / DATETIME：`enabled` 存的是整数 0/1，时间列存的是字符串。
    psycopg **不会**替我们做方言转换（那是 SQLAlchemy 的职责），裸 INSERT 直接传会报：

        DatatypeMismatch: column "enabled" is of type boolean
                          but expression is of type smallint

    PG 也不允许 smallint→boolean 的隐式赋值转换，所以必须在 Python 侧显式转。
    """
    if value is None:
        return None
    if data_type == "boolean":
        return bool(value)
    if data_type and (data_type.startswith("timestamp") or data_type == "date"):
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                return value  # 无法解析就原样传，让 PG 报明确的错，别静默吞掉
    return value


def _pg_dsn(url: str) -> str:
    """转成 psycopg 可用的 DSN（去掉 SQLAlchemy 驱动前缀）。"""
    for prefix in ("postgresql+psycopg://", "postgresql+asyncpg://", "postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql://" + url[len(prefix):]
    raise SystemExit(f"DATABASE_URL 不是 PostgreSQL：{url}")


def _sqlite_path(url: str) -> Path:
    for prefix in ("sqlite+aiosqlite:///", "sqlite:///"):
        if url.startswith(prefix):
            return (ROOT / url[len(prefix):]).resolve()
    raise SystemExit(f"找不到源 SQLite 路径：{url}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true", help="先 drop 全部表再重建")
    ap.add_argument("--dry-run", action="store_true", help="只对比行数，不写目标库")
    args = ap.parse_args()

    settings = get_settings()
    pg_url = settings.database_url

    # 源库定位：优先 SQLITE_SOURCE 环境变量；当前 URL 若仍是 sqlite 就用它；否则用默认文件。
    # （切到 PG 之后 settings.database_url 已经是 PG，不能再拿它当源库路径。）
    src_env = os.getenv("SQLITE_SOURCE")
    if src_env:
        src_file = Path(src_env)
    elif settings.database_url.startswith("sqlite"):
        src_file = _sqlite_path(settings.database_url)
    else:
        src_file = ROOT / "llmbridge.db"

    import re

    safe_url = re.sub(r"://([^:@/]+):[^@]+@", r"://\1:***@", pg_url)

    lines: list[str] = []
    lines.append(f"source sqlite : {src_file}")
    lines.append(f"target pg     : {safe_url}")
    lines.append("")

    if not src_file.exists():
        raise SystemExit(f"源 SQLite 不存在：{src_file}")
    if not pg_url.startswith(("postgresql", "postgres://")):
        raise SystemExit(f"DATABASE_URL 不是 PostgreSQL，拒绝迁移：{safe_url}")

    src = sqlite3.connect(str(src_file))
    src.row_factory = sqlite3.Row

    if args.dry_run:
        for t in TABLES:
            n = src.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            lines.append(f"[dry-run] {t:<18} sqlite={n}")
        (ROOT / "_migrate_report.txt").write_text("\n".join(lines), encoding="utf-8")
        print("\n".join(lines))
        return

    import psycopg

    # 建表：复用 ORM 元数据，保证 DDL 与代码完全一致（不用手写 SQL，避免两边漂移）
    from sqlalchemy import create_engine

    from app.db.tables import Base

    sync_url = "postgresql+psycopg://" + pg_url[len("postgresql://"):] if pg_url.startswith("postgresql://") else pg_url
    if sync_url.startswith("postgresql+asyncpg://"):
        sync_url = sync_url.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)
    engine = create_engine(sync_url)

    if args.reset:
        Base.metadata.drop_all(engine)
        lines.append("已 drop 全部表（--reset）")
    Base.metadata.create_all(engine)
    lines.append("表结构就绪（create_all，已存在则跳过）")
    lines.append("")

    with psycopg.connect(_pg_dsn(pg_url)) as dst:
        with dst.cursor() as cur:
            # 目标表清空（保留结构），使脚本可重复执行
            for t in reversed(TABLES):
                cur.execute(f'TRUNCATE TABLE "{t}" RESTART IDENTITY CASCADE')

            # 读目标库真实列类型，据此做值转换（不硬编码，避免两边类型漂移）
            cur.execute(
                "select table_name, column_name, data_type from information_schema.columns "
                "where table_schema = 'public'"
            )
            col_types: dict[str, dict[str, str]] = {}
            for t_name, c_name, d_type in cur.fetchall():
                col_types.setdefault(t_name, {})[c_name] = d_type

            for t in TABLES:
                rows = src.execute(f'SELECT * FROM "{t}"').fetchall()
                if not rows:
                    lines.append(f"{t:<18} 0 行（跳过）")
                    continue
                cols = rows[0].keys()
                col_sql = ", ".join(f'"{c}"' for c in cols)
                ph = ", ".join(["%s"] * len(cols))
                types = col_types.get(t, {})
                cur.executemany(
                    f'INSERT INTO "{t}" ({col_sql}) VALUES ({ph})',
                    [tuple(_convert(r[c], types.get(c)) for c in cols) for r in rows],
                )
                # 重置主键序列
                cur.execute(
                    "SELECT setval(pg_get_serial_sequence(%s, 'id'), "
                    f"COALESCE((SELECT MAX(id) FROM \"{t}\"), 1), true)",
                    (t,),
                )
                lines.append(f"{t:<18} 写入 {len(rows)} 行")
        dst.commit()

        lines.append("")
        lines.append("=== 行数校验（sqlite vs pg）===")
        ok = True
        with dst.cursor() as cur:
            for t in TABLES:
                n_src = src.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
                cur.execute(f'SELECT COUNT(*) FROM "{t}"')
                n_dst = cur.fetchone()[0]
                flag = "OK " if n_src == n_dst else "差异"
                if n_src != n_dst:
                    ok = False
                lines.append(f"{flag} {t:<18} {n_src} -> {n_dst}")
        lines.append("")
        lines.append("结果：" + ("全部一致" if ok else "存在差异，请检查"))

    src.close()
    report = ROOT / "_migrate_report.txt"
    report.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
