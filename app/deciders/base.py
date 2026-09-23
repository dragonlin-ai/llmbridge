"""判定器抽象：路由层只依赖 BaseDecider，不耦合任何具体判定模型。

设计审核 R-03 / 基线 3.2-6 硬约束：至少两个实现（Jev 官方 + Mock），
通过同一组契约测试，否则抽象形同虚设。
"""
from abc import ABC, abstractmethod

from app.router_engine.context import Decision, RouterContext

# task_type 枚举：与模型池 capabilities 标签体系一致
TASK_TYPES = (
    "general",
    "code_generation",
    "translation",
    "summarize",
    "complex_reasoning",
    "long_context",
)


class BaseDecider(ABC):
    """判定器接口。decide 返回 None 表示判定不可用（上层落 L3 兜底）。"""

    name: str = "base"

    @abstractmethod
    async def decide(self, ctx: RouterContext) -> Decision | None:
        """对输入做任务类别判定。实现必须自带超时控制，不得无限等待。"""

    @abstractmethod
    async def health_check(self) -> bool:
        """健康探测：启动时与运行期探活。"""
