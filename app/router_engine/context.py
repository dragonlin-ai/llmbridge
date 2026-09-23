"""路由引擎核心数据结构：RouterContext 与 Decision。

Decision 是 BaseDecider 的统一输出契约——Jev 官方版与 Mock 版输出同构，
由同一组契约测试约束（阶段三 C-11）。
"""
from dataclasses import dataclass, field
from time import monotonic


@dataclass
class Decision:
    """判定器输出（基线 3.2-5/6 契约）。"""

    task_type: str
    confidence: float
    probabilities: dict[str, float]
    features: dict[str, float]  # complexity/has_code/is_sensitive
    decider: str  # jev / mock


@dataclass
class ModelRef:
    """模型池条目的运行时只读引用（adapters/deciders 禁止 import db）。"""

    id: int
    provider_id: int
    model_name: str
    display_name: str
    capabilities: list[str]
    input_price: float
    output_price: float
    priority: int


@dataclass
class RouterContext:
    trace_id: str
    input_text: str
    token_len: int
    session_id: str | None = None
    candidates: list[ModelRef] = field(default_factory=list)
    hit_layer: str | None = None  # L1 / L2 / L3
    decision: Decision | None = None
    hit_rule: dict | None = None  # L1 命中的规则快照
    final_model: ModelRef | None = None
    fallback_reason: str | None = None
    route_started_at: float = field(default_factory=monotonic)

    @property
    def route_latency_ms(self) -> int:
        return int((monotonic() - self.route_started_at) * 1000)
