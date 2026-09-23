"""ORM 表定义（9 张，与 docs/阶段二-设计与架构/05-数据库设计.sql 一一对应）。

命名约定（基线 3.11）：下游大模型业务概念叫 Model（模型池条目）；
本目录一律称「表」，避免 models/ 撞名歧义。
"""
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), onupdate=func.current_timestamp()
    )


class Provider(Base, TimestampMixin):
    """厂商接入通道。

    一行 = **一条可独立配置的接入通道**，不是「一家厂商」。
    同一家厂商常有多种互不相通的接入方式（按量 API / 编程订阅套餐 / 资源包），
    它们各有自己的密钥申请入口、base_url、计费口径与限流规则，密钥也互不通用。
    因此一家厂商在库中可以是多行，靠 `vendor` 字段聚成一组，控制台按厂商分组展示。

    ⚠️ 这条区分必须落在数据上而不是靠人记住：
    「同一家厂商」不等于「同一套凭证」，把两者混为一谈会导致填了 Key 却调不通。
    """

    __tablename__ = "provider"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    """通道显示名，如「月之暗面 Kimi · 按量 API」。全库唯一。"""

    vendor: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    """厂商标识（分组键），如 `moonshot`。同厂商的多条通道共用此值。
    手工录入可为空——为空时界面把它当作独立厂商，不做分组。"""

    access_kind: Mapped[str] = mapped_column(String(32), default="api", server_default="api")
    """接入形态：api 按量后付费 / package 预付费资源包 / batch 批处理 /
    coding_plan 编程订阅套餐 / token_plan 通用 Token 订阅套餐。
    决定「是否参与路由」：见 services/provider_access.py 的 ROUTABLE_ACCESS_KINDS。"""

    protocol: Mapped[str] = mapped_column(String(32), default="openai", server_default="openai")
    """上游协议：openai / anthropic。
    只有已实现适配器的协议才可路由——登记一个没有适配器的协议，
    等于让候选池里躺着必然失败的模型（D-25 的同类错误）。
    本项目的 base_url 一律优先取**OpenAI 兼容**端点，因为目前只实现了
    `adapters/openai_compat.py`；厂商另提供的 Anthropic 端点在 remark 中说明。"""

    base_url: Mapped[str] = mapped_column(String(255))
    api_key_encrypted: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # 接入备注（可空）：主要由内置厂商目录写入，内容为「密钥申请地址 + 接入注意事项」。
    # 解决的是「使用者不知道该去哪拿 Key」——把申请入口放在控制台里，
    # 使接入成本从「翻文档」降为「点链接、复制 Key、粘贴」。
    remark: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # 厂商官方条款警示（可空）：订阅类套餐（coding_plan / token_plan）普遍在官方文档里
    # 明确限定「仅可在官方支持的编程/智能体工具内交互式使用，不得作为应用后端」。
    # 本网关从上游看正是应用后端，因此这类通道**可用但需知情**。
    # 单独成列而非塞进 remark（255 上限）——条款原文通常超过 255 字符，截断会丢失约束语义。
    terms_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "access_kind IN ('api','package','token_plan','coding_plan','batch')",
            name="ck_provider_access_kind",
        ),
        CheckConstraint("protocol IN ('openai','anthropic')", name="ck_provider_protocol"),
    )


class Model(Base, TimestampMixin):
    """模型池条目 = 下游大模型（业务术语 Model）。"""

    __tablename__ = "model"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("provider.id"))
    model_name: Mapped[str] = mapped_column(String(128))
    display_name: Mapped[str] = mapped_column(String(128))
    capabilities: Mapped[str] = mapped_column(Text, default="[]")  # JSON 数组
    input_price: Mapped[float] = mapped_column(Float, default=0)  # 元/百万 token
    output_price: Mapped[float] = mapped_column(Float, default=0)
    context_window: Mapped[int] = mapped_column(Integer, default=8192)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    priority: Mapped[int] = mapped_column(Integer, default=100)  # 越小越优先 = 降级顺序


class RouteRule(Base, TimestampMixin):
    __tablename__ = "route_rule"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128))
    priority: Mapped[int] = mapped_column(Integer, default=100)
    type: Mapped[str] = mapped_column(String(32))
    condition_json: Mapped[str] = mapped_column(Text)
    target_model_id: Mapped[int] = mapped_column(ForeignKey("model.id"))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    remark: Mapped[str | None] = mapped_column(String(255), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "type IN ('keyword','regex','token_len','tenant_whitelist','session_pin')",
            name="ck_rule_type",
        ),
    )


class DecisionSample(Base):
    __tablename__ = "decision_sample"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    input_text: Mapped[str] = mapped_column(Text)
    task_type: Mapped[str] = mapped_column(String(64))
    probabilities_json: Mapped[str] = mapped_column(Text, default="{}")
    chosen_model_id: Mapped[int | None] = mapped_column(ForeignKey("model.id"), nullable=True)
    actual_model_id: Mapped[int | None] = mapped_column(ForeignKey("model.id"), nullable=True)
    source: Mapped[str] = mapped_column(String(32), default="manual")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())


class PromptTemplate(Base):
    __tablename__ = "prompt_template"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scene: Mapped[str] = mapped_column(String(64))
    content: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())


class RequestLog(Base):
    """调用日志：每次请求一行；input_text 应用层截断 2000 字符。"""

    __tablename__ = "request_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trace_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    input_text: Mapped[str] = mapped_column(Text)
    router_output_json: Mapped[str] = mapped_column(Text, default="{}")
    router_layer: Mapped[str] = mapped_column(String(8))  # L1/L2/L3
    final_model_id: Mapped[int | None] = mapped_column(ForeignKey("model.id"), nullable=True, index=True)
    # 模型名快照（落库当时的 model_name）。
    # 为什么不只靠外键：模型删除时外键会被解绑成 NULL（删除被历史日志阻塞不可接受），
    # 于是「这次请求到底调了哪个模型」这个既成事实会永久丢失——日志里只剩空白，
    # 看起来就像「日志显示的模型和真实调用的不一致」。快照让事实不随配置变更而蒸发。
    final_model_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    route_latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost: Mapped[float] = mapped_column(Float, default=0)
    status: Mapped[str] = mapped_column(String(16), default="success")
    fallback_reason: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp(), index=True)

    __table_args__ = (CheckConstraint("router_layer IN ('L1','L2','L3')", name="ck_log_layer"),)


class EvalCase(Base):
    __tablename__ = "eval_case"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    input_text: Mapped[str] = mapped_column(Text)
    expected_task_type: Mapped[str] = mapped_column(String(64))
    expected_model_id: Mapped[int | None] = mapped_column(ForeignKey("model.id"), nullable=True)
    remark: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())


class AdminUser(Base):
    __tablename__ = "admin_user"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default="admin")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())

    __table_args__ = (CheckConstraint("role IN ('admin','readonly')", name="ck_user_role"),)


class ApiKey(Base, TimestampMixin):
    """第三方调用密钥：对外 `/v1` 入口的鉴权凭证（接口设计说明书 V2「独立 api_key 表」）。

    与 `provider.api_key_encrypted` 的区别（两者极易混淆，务必分清）：
    - `provider.api_key_encrypted` 是**上游厂商的 Key**——我们去调别人时出示的凭证；
    - 本表是**本网关发给第三方调用方的 Key**——别人来调我们时出示的凭证。
    方向相反，泄密后果与轮换策略都不同。

    存储策略：
    - `key_hash`：sha256 明文摘要，`/v1` 鉴权按它**等值查找**（有唯一索引，O(1)）。
      明文不落库——库被拖走也无法反推出可用 Key。
    - `key_encrypted`：AES-256-GCM 密文副本，仅供控制台「查看/复制」回显
      （第三方调用方需要把完整 Key 配进自己的系统，只给 hash 不可用）。
      与 provider 同一套 `core/crypto.py`，主密钥轮换时两处一起轮。
    - `key_prefix`：明文前 12 位，列表页做掩码展示与人工对账用。
    """

    __tablename__ = "api_key"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64))
    """用途备注，如「订单系统-生产」。第三方接入是按调用方分发的，没有名字就分不清谁在用。"""

    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    """sha256(明文) 十六进制。鉴权唯一判据。"""

    key_prefix: Mapped[str] = mapped_column(String(16))
    """明文前缀（如 `sk-lb-a1b2c3`），供列表掩码展示，不含足以碰撞的熵。"""

    key_encrypted: Mapped[str] = mapped_column(Text)
    """明文的 AES-GCM 密文，仅用于控制台回显完整 Key。"""

    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    """停用后立刻 401，但记录保留 —— 轮换/吊销不应抹掉「谁曾经用过」的审计价值。"""

    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    """最近一次鉴权成功时间。用于识别「发出去再也没用过」与「吊销了还在被尝试」的 Key。"""

    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    """可选过期时间；NULL = 长期有效。"""


class SysConfig(Base, TimestampMixin):
    """系统配置（键值对）：判定器等可界面化配置的持久化存储。

    读取顺序 **库 > .env > 代码默认**（app/core/config.apply_db_overrides）：
    库里没有该键时自然回落 .env —— 保留零依赖部署与容器 env 注入两种方式，
    迁移不是替换而是叠加一层可编辑的覆盖。

    值一律按字符串存，数值型在读取时按 key 强制转型（sys_config._COERCE）；
    密钥类（jev_api_key）`encrypted=True`，值为 AES-256-GCM 密文，
    明文永不落库、永不回显（界面只出掩码，见 get_decider_display）。
    """

    __tablename__ = "sys_config"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    """配置键，如 `judge_provider`。主键天然去重，upsert 按它定位。"""

    value: Mapped[str] = mapped_column(Text)
    """配置值（字符串）。密钥类存密文 `v1:<nonce>:<ct>`。"""

    encrypted: Mapped[bool] = mapped_column(Boolean, default=False)
    """是否密文存储。只由 sys_config 服务按 SECRET_KEYS 写入，读取时据此解密。"""
