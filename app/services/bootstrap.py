"""首次运行引导：让「装完直接开界面」这件事成立。

问题
----
交付态原先的三步是 `llmbridge-seed` → `llmbridge-catalog` → `llmbridge-serve`。
只要漏掉第二步（或根本没源码目录、跑不了 `scripts/`），
使用者打开控制台看到的就是「一家厂商都没有」——不知道从哪接入，产品像坏的。
实测：只跑 seed 时库里只有 2 个开发用厂商，13 家主流接入商**一个都不出现**。

所以把这三件事收成一条启动路径，幂等、失败不阻塞启动：

1. `ensure_schema`    —— 建表（`create_all`，已存在则空操作）
2. `ensure_admin`     —— 管理员为空时建默认账号，否则连登录页都过不去
3. `ensure_eval_cases`—— 评测样本为空时写入 4 条内置样本（评测看板没有新增接口，
   不预置该页面对普通使用者永久空白；模型真值留空，见下方常量注释）
4. `ensure_providers` —— **只预置接入商**（模型池留空，由使用者在「模型池」页手工添加）

`llmbridge-seed` 调的也是这一套，两条路径行为完全一致 ——
同一个全新安装不该因为「跑没跑某条命令」而长得不一样。

三个刻意的取舍
--------------
- **只铺接入商，不铺模型**。接入商是客观、可枚举的，必须先摆出来；
  而「你的账号能用哪些模型、什么价」因账号而异，预置一份参考列表会让人误以为已配置。
  需要参考目录时用 `llmbridge-catalog --with-models` 显式灌入。
- **用标记而不是「表为空」判重**。`sys_config.catalog_seed_version` 记录已预置到的目录版本：
  使用者把目录清空了，重启不会被"复活"；目录升级了（版本号变化）才重新预置，
  于是老装机也能拿到新增的厂商通道。
- **多 worker 并发下靠唯一约束兜底**。`provider.name` / `admin_user.username` 都是有唯一约束的，
  多个 worker 同时启动时后者会撞约束 —— 那不是故障，回滚并记为「已由其他进程完成」即可。
"""
from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.core.security import hash_password
from app.data.catalog_seed import catalog_stats, seed_catalog
from app.data.provider_catalog import CATALOG_VERSION
from app.db.session import SessionLocal, engine
from app.db.tables import AdminUser, Base, EvalCase, Provider, SysConfig

logger = logging.getLogger("bootstrap")

# 预置进度标记：值为已预置到的目录版本（app/data/provider_catalog.py 的 CATALOG_VERSION）。
MARKER_KEY = "catalog_seed_version"

DEFAULT_ADMIN_USERNAME = "admin"
DEFAULT_ADMIN_PASSWORD = "admin123"
"""默认管理员口令。首次登录后必须改 —— 启动日志与登录页都会提示。"""

# 评测样本：只带**任务类型真值**，模型真值（expected_model_id）留空。
# 为什么引导里要写它：`eval_case` 是交付菜单「分析与优化 → 评测看板」的数据源，
# 而项目里**没有任何接口能新增评测样本**（`POST /admin/samples` 写的是
# decision_sample，另一张表）。不预置 = 该页面对普通使用者永久空白。
# 模型真值留空是有意为之 —— 评测看板对此有明确口径：model_ok=None、
# 汇总时跳过模型维度、并另外回传 model_truth_cases 说明有几条没有模型真值；
# 任务类型准确率与混淆矩阵不受影响。使用者加了模型后可以自行补上真值。
_EVAL_CASES = [
    ("帮我写一个 Python 函数，计算两个日期之间的工作日", "code_generation"),
    ("把下面这段话翻译成英文：今天天气很好", "translation"),
    ("总结这篇文章的核心观点，控制在 200 字以内", "summarize"),
    ("用通俗语言解释一下什么是量子纠缠", "general"),
]


async def ensure_schema() -> bool:
    """建表。返回是否真的创建了新表（已存在则为 False）。"""
    existed = await _table_exists("provider")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return not existed


async def _table_exists(name: str) -> bool:
    """检查表是否存在。用 SQLAlchemy 的 inspector 而不是方言专有 SQL，
    以便 PostgreSQL / SQLite 两种后端共用同一段判断。"""
    from sqlalchemy import inspect

    async with engine.connect() as conn:
        tables = await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_table_names())
    return name in tables


async def ensure_admin(session) -> str:
    """管理员为空时建默认账号。返回 `created` / `exists` / `race`。"""
    existing = (await session.execute(
        select(func.count(AdminUser.id))
    )).scalar_one()
    if existing:
        return "exists"
    session.add(AdminUser(username=DEFAULT_ADMIN_USERNAME,
                          password_hash=hash_password(DEFAULT_ADMIN_PASSWORD),
                          role="admin"))
    try:
        await session.commit()
    except IntegrityError:
        # 多 worker 同时启动时可能撞 username 唯一约束 —— 别人已经建好了，不算失败
        await session.rollback()
        return "race"
    logger.warning(
        "已创建默认管理员 %s / %s —— 首次登录后请立即修改口令",
        DEFAULT_ADMIN_USERNAME, DEFAULT_ADMIN_PASSWORD,
    )
    return "created"


async def ensure_eval_cases(session) -> str:
    """评测样本为空时写入内置样本。返回 `created` / `exists`。

    只在表为空时写 —— 使用者自己准备的样本永远不被覆盖。
    """
    existing = (await session.execute(select(func.count(EvalCase.id)))).scalar_one()
    if existing:
        return "exists"
    session.add_all([
        EvalCase(input_text=text, expected_task_type=task_type, expected_model_id=None)
        for text, task_type in _EVAL_CASES
    ])
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        return "race"
    return "created"


async def ensure_providers(session, *, force: bool = False) -> list[str] | str:
    """预置接入通道。

    返回**报告行列表**表示已预置；返回**状态字符串**表示未预置，取值：
    `up-to-date`（版本一致） / `legacy-skipped`（既有安装，刻意不动） / `race`（并发冲突）。

    判定顺序（刻意保守 —— 这是**唯一**会改动 provider 行的自动步骤）：

    ==================  ==================================================
    库状态              行为
    ==================  ==================================================
    全新库（0 条通道）  立即预置。**这条是本次需求的全部意义**
    既有库且无标记      只补标记 + 记日志，**一条都不动**
    既有库且版本不一致  重新预置（目录升级，新增/变更的通道会被补上）
    既有库且版本一致    跳过
    显式 ``force=True``  无条件预置（手工命令走这条）
    ==================  ==================================================

    「既有库且无标记」为什么不预置：那是**早于本引导存在**的库（例如线上 PG），
    它可能已被手工 `llmbridge-catalog` 处理过、甚至被改过通道名。
    对这类库自动跑一遍预置，虽然幂等且不碰密钥，但**改名/改端点/补说明**都是
    对使用者数据的静默写操作 —— 而使用者的预期是「启动服务」，不是「顺手改我的配置」。
    所以只记标记，把选择权留给 `llmbridge-catalog`（它带 `--keep-names` 等开关）。
    """
    marker = await session.get(SysConfig, MARKER_KEY)
    provider_count = (await session.execute(select(func.count(Provider.id)))).scalar_one()

    if not force:
        if marker is None:
            if provider_count:
                session.add(SysConfig(key=MARKER_KEY, value=CATALOG_VERSION, encrypted=False))
                await session.commit()
                logger.info(
                    "检测到既有安装（%d 条接入通道）且无预置标记：判定为老库，"
                    "跳过自动预置、一条都不动，仅记录标记 version=%s。"
                    "如需同步目录请显式执行 llmbridge-catalog",
                    provider_count, CATALOG_VERSION,
                )
                return "legacy-skipped"
        elif marker.value == CATALOG_VERSION:
            return "up-to-date"
        # 其余情况（库为空 / 目录版本变化）继续走预置

    lines = await seed_catalog(session, with_models=False)
    if marker is not None:
        marker.value = CATALOG_VERSION
    else:
        session.add(SysConfig(key=MARKER_KEY, value=CATALOG_VERSION, encrypted=False))
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        logger.info("厂商目录预置与其他进程并发，已跳过（唯一约束兜底）")
        return "race"
    stats = catalog_stats()
    logger.info("厂商目录预置完成 version=%s 厂商=%d 通道=%d（模型池留空，待手工添加）",
                CATALOG_VERSION, stats["vendors"], stats["channels"])
    return lines


async def run_first_run(*, force: bool = False) -> dict:
    """编排三步引导。**任何一步失败都不抛异常**（只记 ERROR），绝不阻塞服务启动。

    返回各类结果摘要，供调用方日志化（测试脚本也据此断言）。
    """
    summary: dict[str, object] = {"schema_created": None, "admin": None,
                                  "eval_cases": None, "providers": None, "errors": []}

    try:
        summary["schema_created"] = await ensure_schema()
    except Exception as e:  # noqa: BLE001 启动引导失败必须显性可见但不致命
        logger.error("bootstrap: 建表失败 %s: %s", type(e).__name__, str(e)[:200])
        summary["errors"].append(f"schema: {type(e).__name__}: {str(e)[:120]}")
        return summary

    async with SessionLocal() as session:
        try:
            summary["admin"] = await ensure_admin(session)
        except Exception as e:  # noqa: BLE001
            await session.rollback()
            logger.error("bootstrap: 创建管理员失败 %s: %s", type(e).__name__, str(e)[:200])
            summary["errors"].append(f"admin: {type(e).__name__}: {str(e)[:120]}")

        try:
            summary["eval_cases"] = await ensure_eval_cases(session)
        except Exception as e:  # noqa: BLE001
            await session.rollback()
            logger.error("bootstrap: 写入评测样本失败 %s: %s", type(e).__name__, str(e)[:200])
            summary["errors"].append(f"eval_cases: {type(e).__name__}: {str(e)[:120]}")

        try:
            result = await ensure_providers(session, force=force)
        except Exception as e:  # noqa: BLE001
            await session.rollback()
            logger.error("bootstrap: 预置厂商目录失败 %s: %s", type(e).__name__, str(e)[:200])
            summary["errors"].append(f"providers: {type(e).__name__}: {str(e)[:120]}")
            return summary

    if isinstance(result, str):
        summary["providers"] = result
    else:
        summary["providers"] = "seeded"
        summary["counts"] = await _current_counts()
        # 完整报告留在摘要里由调用方决定是否打印：
        # 手工执行 llmbridge-seed 时想看到「哪条通道被新增/端点被修正」，
        # 而服务启动时打 130 行到日志是噪音，只记一行摘要。
        summary["report"] = result
    return summary


async def _current_counts() -> dict[str, int]:
    async with SessionLocal() as session:
        providers = (await session.execute(select(func.count(Provider.id)))).scalar_one()
        vendors = (await session.execute(
            select(func.count(func.distinct(Provider.vendor)))
        )).scalar_one()
    return {"providers": providers, "vendors": vendors}
