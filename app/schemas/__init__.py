"""Pydantic 出入参模型：与接口设计说明书 §1~§3 一一对应。"""
from typing import Any

from pydantic import BaseModel, Field


# ---- 公共 ----
class ApiEnvelope(BaseModel):
    code: int = 0
    message: str = "ok"
    data: Any = None


class PageParams(BaseModel):
    page: int = Field(1, ge=1)
    page_size: int = Field(20, ge=1, le=100)


# ---- /v1 ----
class ChatMessage(BaseModel):
    role: str
    content: Any = None
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[dict] | None = None


class ChatCompletionRequest(BaseModel):
    model: str = "auto"
    messages: list[ChatMessage]
    stream: bool = False
    temperature: float | None = None
    max_tokens: int | None = None
    top_p: float | None = None
    tools: list[dict] | None = None
    tool_choice: Any = None

    def upstream_payload(self) -> dict:
        body: dict = {
            "messages": [m.model_dump(exclude_none=True) for m in self.messages],
            "stream": self.stream,
        }
        for k in ("temperature", "max_tokens", "top_p", "tools", "tool_choice"):
            if (v := getattr(self, k)) is not None:
                body[k] = v
        return body


# ---- /admin/auth ----
class LoginRequest(BaseModel):
    username: str
    password: str


# ---- /admin/providers ----
class ProviderIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    base_url: str = Field(min_length=8, max_length=255)
    api_key: str = Field(min_length=8)
    remark: str | None = Field(None, max_length=255)
    # 厂商官方条款警示。不设 max_length：条款原文常超 255 字符，
    # 截断会丢掉「不得作为应用后端」这类关键约束语义。
    terms_note: str | None = None
    # 一条 provider 记录 = 一条接入通道，不是一家厂商。
    # vendor 把同厂商的多条通道聚成一组（控制台按它分组展示）。
    vendor: str | None = Field(None, max_length=64)
    access_kind: str = Field("api", max_length=32)
    """api / package / batch / coding_plan / token_plan（见 catalog 的 ACCESS_KINDS）。"""
    protocol: str = Field("openai", max_length=32)      # openai / anthropic


class ProviderUpdate(BaseModel):
    name: str | None = None
    base_url: str | None = None
    api_key: str | None = None  # 不传 = 不修改
    enabled: bool | None = None
    remark: str | None = Field(None, max_length=255)
    terms_note: str | None = None
    vendor: str | None = Field(None, max_length=64)
    access_kind: str | None = Field(None, max_length=32)
    protocol: str | None = Field(None, max_length=32)


# ---- /admin/models ----
class ModelIn(BaseModel):
    provider_id: int
    model_name: str = Field(min_length=1, max_length=128)
    display_name: str = Field(min_length=1, max_length=128)
    capabilities: list[str] = []
    input_price: float = Field(0, ge=0)
    output_price: float = Field(0, ge=0)
    context_window: int = Field(8192, ge=1)
    priority: int = Field(100, ge=1)
    enabled: bool = True


class ModelUpdate(BaseModel):
    provider_id: int | None = None
    model_name: str | None = None
    display_name: str | None = None
    capabilities: list[str] | None = None
    input_price: float | None = None
    output_price: float | None = None
    context_window: int | None = None
    priority: int | None = None
    enabled: bool | None = None


# ---- /admin/rules ----
class RuleConditionClause(BaseModel):
    """condition_json 单条件。field 与 op 的合法组合见接口说明书 §3.4。"""

    field: str  # text / token_len
    op: str
    value: Any


class RuleCondition(BaseModel):
    all: list[RuleConditionClause] = Field(min_length=1)


class RuleIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    priority: int = Field(100, ge=1)
    type: str  # keyword/regex/token_len/tenant_whitelist/session_pin
    condition: RuleCondition
    target_model_id: int
    enabled: bool = True
    remark: str | None = None


class RuleUpdate(BaseModel):
    name: str | None = None
    priority: int | None = None
    type: str | None = None
    condition: RuleCondition | None = None
    target_model_id: int | None = None
    enabled: bool | None = None
    remark: str | None = None


class RulePrioritiesIn(BaseModel):
    ordered_ids: list[int] = Field(min_length=1)


# ---- /admin/samples ----
class SampleIn(BaseModel):
    input_text: str = Field(min_length=1)
    task_type: str
    probabilities_json: dict = {}
    chosen_model_id: int | None = None


# ---- /admin/decider/settings ----
class DeciderSettingsIn(BaseModel):
    """判定器 5 项配置（Jev）入参。全部可选 = partial 更新，None/缺省 = 不修改。

    jev_api_key 约定（安全方案 §2.2，与 providers.api_key 同口径）：
    明文提交才落库（AES-GCM 加密存储）；"" = 显式清空（删行回落 .env）；
    含 "****" 的掩码值 = 用户未改动，忽略不写。
    """

    judge_provider: str | None = None       # mock / jev（枚举在路由层校验）
    jev_api_key: str | None = Field(None, max_length=512)
    jev_base_url: str | None = Field(None, min_length=8, max_length=255)
    decider_timeout_ms: int | None = Field(None, ge=100, le=60000)
    route_confidence_threshold_t2: float | None = Field(None, ge=0, le=1)


# ---- /admin/route/preview ----
class PreviewRequest(BaseModel):
    text: str = Field(min_length=1, max_length=50000)
    session_id: str | None = None
    # execute=true 时，除决策外**真实调用**选中模型并把输出带回（会产生真实费用）。
    # 默认 false，保持「零成本试跑」为默认行为。
    execute: bool = False
    max_tokens: int | None = Field(default=512, ge=1, le=4096)
