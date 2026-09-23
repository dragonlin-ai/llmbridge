"""数据库会话：异步 engine + sessionmaker。

生产/主用 **PostgreSQL**（异步驱动 `psycopg3`，URL 前缀 `postgresql+psycopg://`）。

为什么是 psycopg 而不是 asyncpg：本项目开发机为 Windows，asyncpg 依赖 C 扩展编译，
旧的依赖声明用 `sys_platform != 'win32'` 把它排除在 Windows 之外，等于绑死了 SQLite。
psycopg3 有免编译 wheel，开发与生产同一套驱动，避免「开发库 SQLite / 生产库 PG」两套语义。

SQLite 仅作**零依赖兜底**（无 .env 时仍可启动）：连接事件里启用 WAL + NORMAL 同步。
"""
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings


def _to_async_url(url: str) -> str:
    """把同步 URL 规范成 SQLAlchemy 异步驱动 URL（已是异步前缀则原样返回）。"""
    if url.startswith("sqlite:///"):
        return url.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
    if url.startswith(("postgresql+psycopg://", "postgresql+asyncpg://")):
        return url
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    if url.startswith("postgres://"):  # 云厂商常见简写（Heroku/Render 等）
        return url.replace("postgres://", "postgresql+psycopg://", 1)
    return url


_settings = get_settings()
engine = create_async_engine(_to_async_url(_settings.database_url), echo=False, pool_pre_ping=True)

if engine.dialect.name == "sqlite":

    @event.listens_for(engine.sync_engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db():
    """FastAPI 依赖：请求级会话。"""
    async with SessionLocal() as session:
        yield session
