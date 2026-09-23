"""迁移 D-19：request_log 增加 final_model_key（模型名快照）。

背景：request_log.final_model_id 是指向 model(id) 的外键。删除模型时应用层会把
引用解绑为 NULL（历史类引用不该阻塞模型下线），代价是「这条日志当时调用的是哪个模型」
永久丢失 —— 日志页面上只剩空白，看起来就像「日志显示的模型与真实调用的不一致」。
本迁移给 request_log 加一个模型名快照列，让既成事实不随配置变更蒸发。

幂等：重复执行安全（列已存在则跳过）。SQLite 用 ALTER TABLE ADD COLUMN；
PostgreSQL 语法相同（V1.1 换库时可直接复用本语句）。

用法：
    .venv/Scripts/python.exe scripts/migrate_d19_model_key_snapshot.py
"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402

COLUMN = "final_model_key"
DDL = f"ALTER TABLE request_log ADD COLUMN {COLUMN} VARCHAR(128)"


def _db_path() -> str:
    url = get_settings().database_url
    for prefix in ("sqlite+aiosqlite:///", "sqlite:///"):
        if url.startswith(prefix):
            return url[len(prefix):]
    raise SystemExit(f"本迁移仅处理 SQLite 开发库，当前 URL 不支持：{url}")


def main() -> None:
    path = _db_path()
    con = sqlite3.connect(path)
    try:
        cols = [row[1] for row in con.execute("PRAGMA table_info(request_log)")]
        if not cols:
            raise SystemExit("request_log 表不存在，请先初始化数据库")
        if COLUMN in cols:
            print(f"SKIP: {COLUMN} 已存在（迁移已执行过）")
            return
        con.execute(DDL)
        con.commit()
        after = [row[1] for row in con.execute("PRAGMA table_info(request_log)")]
        print(f"OK: 已新增 {COLUMN}，当前列数 {len(cols)} -> {len(after)}")
        # 历史行保持 NULL：模型已删的旧日志无法回溯取名，读接口会自动回退到外键 join
        nulls = con.execute(
            f"SELECT COUNT(*) FROM request_log WHERE {COLUMN} IS NULL").fetchone()[0]
        print(f"NOTE: 历史行 {nulls} 条保持 NULL（快照只对迁移后的新日志生效）")
    finally:
        con.close()


if __name__ == "__main__":
    main()
