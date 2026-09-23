"""应用配置：pydantic-settings 统一管理，环境变量优先。

库级覆盖（sys_config 表）：读取顺序 **库 > .env > 代码默认**。
Settings() 构造时已吸收 .env，`apply_db_overrides` 再把库里有值的键盖上去；
写入后清 lru_cache —— 判定器切换（mock/jev）免重启即时生效。
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

# 仅由 services/sys_config 在启动加载与保存后写入；键必须是 Settings 已声明的字段。
_db_overrides: dict[str, object] = {}


def apply_db_overrides(overrides: dict[str, object]) -> None:
    """写入库级配置覆盖并使 get_settings 缓存失效（覆盖为空 = 全部回落 .env）。"""
    _db_overrides.clear()
    _db_overrides.update(overrides)
    get_settings.cache_clear()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # 数据库与缓存
    # 主用 PostgreSQL（.env 配 DATABASE_URL=postgresql://...）；此处保留 SQLite 仅作
    # 「没有 .env 也能起来」的兜底，不代表当前生效值——以启动日志打印的实际 URL 为准。
    database_url: str = "sqlite:///./llmbridge.db"
    redis_url: str | None = None

    # SSRF 白名单开关：是否允许厂商 base_url 使用 http:// 及 localhost/私网地址。
    # 必须独立配置：曾用 database_url.startswith("sqlite") 来判断「是不是开发环境」，
    # 换成 PostgreSQL 后该判断**静默变成 False**，会导致本地/内网厂商地址被 422 拒绝。
    # 开发机置 True，生产必须 False（安全方案 §7）。
    allow_local_base_url: bool = False

    # 首次运行引导：启动时自动「建表 + 建默认管理员 + 预置厂商接入目录」（均幂等）。
    # 关掉它的场景：生产环境由 DBA 管库、不希望服务进程写 schema / 改目录数据。
    # 关掉后需手工执行 `llmbridge-seed`（等价动作）。
    auto_bootstrap: bool = True

    # 安全
    jwt_secret: str = "dev-only-change-me"
    jwt_expire_seconds: int = 86400
    encryption_master_key: str = "dev-only-change-me-32bytes-min!!"

    # 判定器
    judge_provider: str = "mock"  # mock / jev
    jev_api_key: str | None = None
    jev_base_url: str = "https://api.typesafe.ai/v1/systemone"
    decider_timeout_ms: int = 3000
    route_confidence_threshold_t2: float = 0.5

    # 路由
    default_model_id: int = 1
    request_timeout_ms: int = 30000
    route_cache_ttl: int = 3600

    # 工具调用（WebFetch）
    # 抓回正文的字符上限。默认 8000：实测某新闻页原始 HTML 达 120KB，
    # 不做清洗与截断会把单次请求 prompt 从 500 撑到 18800 token（成本 ×30，信息密度极低）。
    tool_result_max_chars: int = 8000
    # 是否由网关**代执行**工具。**默认关** —— 网关的职责是转发，不是替调用方编排。
    #
    # 关（默认）= 纯透传：`tools` 照原样转发给下游，上游返回什么就回什么；
    #   正文、`tool_calls`、SSE 字节一律不做改写，工具交给调用方（前端 / Agent 客户端）执行。
    # 开 = 网关认出白名单工具后自己执行并续写多轮，只适用于「调用方完全没有工具循环」的场景。
    #
    # 为什么默认关：打开时网关会吞掉中间轮、改写正文、并把「模型只说了一句话」当成
    #   一次正常收尾 —— 现象与「上游根本没执行工具」完全无法区分，排查成本极高。
    enable_tool_execution: bool = False

    # 日志批量写
    log_batch_size: int = 50
    log_flush_seconds: float = 1.0


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    # 库 > .env > 代码默认：Settings() 已吸收 .env/默认，此处把库里有值的键盖上去。
    # 不在这里消费 _db_overrides 的话，apply_db_overrides 清缓存也只会重建出 .env 值 ——
    # 「写库成功但生效值不变」（sources=db 而值仍是旧的）就是漏了这一步。
    for k, v in _db_overrides.items():
        setattr(s, k, v)
    return s
