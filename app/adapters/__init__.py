"""适配器注册表：按厂商协议选择实现。"""
from app.adapters.base import BaseAdapter, UpstreamError
from app.adapters.openai_compat import OpenAICompatAdapter

_registry: dict[str, BaseAdapter] = {}


def get_adapter(protocol: str = "openai_compat") -> BaseAdapter:
    if protocol not in _registry:
        _registry[protocol] = OpenAICompatAdapter()
    return _registry[protocol]
