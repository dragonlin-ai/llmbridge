"""trace_id 生成与上下文贯穿（contextvars，异步安全）。"""
import uuid
from contextvars import ContextVar

_trace_id: ContextVar[str | None] = ContextVar("trace_id", default=None)


def new_trace_id(prefix: str = "") -> str:
    tid = f"{prefix}{uuid.uuid4().hex[:16]}"
    _trace_id.set(tid)
    return tid


def current_trace_id() -> str | None:
    return _trace_id.get()
